# tests/test_matcher.py
# ============================================================================
# 匹配器单元测试（纯函数，无需真实 DB / 网络）
# 覆盖三种样本：
#   1) 锚点命中（dim_games 双键齐全）→ method='dim_games', status='matched'
#   2) 孤儿靠 ESPN（nba_api_id NULL，但 ESPN summary 解析出 event）→
#      method='anchor+espn', status='partial'
#   3) 无法匹配（锚点无命中且无 ESPN）→ method='unmatched', status='unmatched'
# ============================================================================
from __future__ import annotations

import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from matcher import match_game, MatchResult, resolve_espn_event  # noqa: E402


# ---------------------------------------------------------------------------
# 测试替身（fake conn / fake cursor / fake session）
# ---------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._sql = sql
        self._params = params

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, rows=None):
        self._rows = rows or []

    def cursor(self):
        return FakeCursor(self._rows)


class FakeSession:
    """模拟 requests.Session：返回含 BOS/NYK 的 scoreboard。"""

    def get(self, url, headers=None, timeout=None):
        class _Resp:
            status_code = 200

            def json(self):
                # 注意：ESPN 用 'NY'（非 'NYK'），our_to_espn 会把 NYK→NY，故此处返回 ESPN 原样缩写
                return {
                    "events": [{
                        "id": "401585401",
                        "competitions": [{
                            "competitors": [
                                {"team": {"abbreviation": "BOS"}},
                                {"team": {"abbreviation": "NY"}},
                            ]
                        }]
                    }]
                }
        return _Resp()


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------
def test_anchor_hit_matched():
    """锚点精确命中，双键齐全 → dim_games / matched。"""
    conn = FakeConn(rows=[("202401010BOS", 22300001)])
    mr = match_game(date(2024, 1, 1), "BOS", "NYK", 112, 105,
                    conn=conn, espn_session=None)
    assert mr == MatchResult(
        br_gid="202401010BOS", nba_api_id="22300001", espn_event=None,
        method="dim_games", status="matched"), mr


def test_orphan_via_espn_partial():
    """孤儿（nba_api_id NULL）靠 ESPN 解析出 event → anchor+espn / partial。"""
    conn = FakeConn(rows=[("202601010BOS", None)])
    session = FakeSession()
    mr = match_game(date(2026, 1, 1), "BOS", "NYK", 110, 108,
                    conn=conn, espn_session=session)
    assert mr.br_gid == "202601010BOS"
    assert mr.nba_api_id is None
    assert mr.espn_event == "401585401"
    assert mr.method == "anchor+espn"
    assert mr.status == "partial", mr


def test_unmatched():
    """锚点无命中且无 ESPN 会话 → unmatched。"""
    conn = FakeConn(rows=[])
    mr = match_game(date(1999, 1, 1), "BOS", "NYK", 100, 99,
                    conn=conn, espn_session=None)
    assert mr == MatchResult(
        br_gid=None, nba_api_id=None, espn_event=None,
        method="unmatched", status="unmatched"), mr


def test_resolve_espn_event_offline_none():
    """无 session 时 resolve_espn_event 返回 None（离线安全）。"""
    assert resolve_espn_event(date(2024, 1, 1), "BOS", "NYK", None) is None


def test_resolve_espn_event_with_session():
    """有 session 时按 team pair 解析出 event id。"""
    got = resolve_espn_event(date(2024, 1, 1), "BOS", "NYK", FakeSession())
    assert got == "401585401"


if __name__ == "__main__":
    # 允许直接 `python tests/test_matcher.py` 运行
    test_anchor_hit_matched()
    test_orphan_via_espn_partial()
    test_unmatched()
    test_resolve_espn_event_offline_none()
    test_resolve_espn_event_with_session()
    print("ALL matcher tests passed")
