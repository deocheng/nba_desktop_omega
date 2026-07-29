"""test_br_player_onoff.py — 球员级 on-off 爬虫 QA。

🔴 纠错背景：on-off 是【球员级】页面（/players/{slug}/on-off/{year}），
与废弃的球队级 /teams/{abbr}/{year}/on-off/ 完全不同。本测试覆盖：

  1. 解析器 ``parse_player_onoff_html``：
     * 常规赛单表（antetgi01/2024）-> 恰好 3 行（On Court/Off Court/On-Off）
     * 含季后赛（jamesle01/2018）-> 6 行（Regular 3 + Playoffs 3）
  2. split 规范化：「On − Off」(U+2212) -> 「On-Off」；On/Off Court 原样。
  3. mp/min_pct 异构：On/Off Court 行 mp=分钟、min_pct=None；
     On-Off 行 mp=None、min_pct=百分比。
  4. 正负号解析：+.035 / -3.7 等原样进 float。
  5. ``build_url`` 格式 / ``build_rows`` 注入键。
  6. 404 隔离（运行时）：_crawl_player 命中 404 -> 隔离 player_onoff_404
     (复合 PK slug,year，note='http_404')，不写归档/不解析/不污染 crawl_failures。

夹具（离线，零 BR 网络）：
  * 常规赛样本：raw_archive/br_players/antetgi01/on_off_2024.html
  * 季后赛样本：raw_archive/br_players/jamesle01/on_off_2018.html
  * 404 页：raw_archive/br_players/alexaga01/shooting.html（复用既有 404 夹具；
    fetch_team_page 的 404 检测与页面类型无关，复用安全）
DB 相关用例全部用 MockConn（不连真实库），sandbox 离线跑、零回归风险。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common.br_player_onoff import BRPlayerOnOffCrawlerBase  # noqa: E402
from external_crawler.crawler.crawl_br_player_onoff import (  # noqa: E402
    PlayerOnOffCrawler,
    parse_player_onoff_html,
    _normalize_split,
    _parse_mp,
)

FIXTURE_REG = ROOT / "raw_archive" / "br_players" / "antetgi01" / "on_off_2024.html"
FIXTURE_PO = ROOT / "raw_archive" / "br_players" / "jamesle01" / "on_off_2018.html"
FIXTURE_404 = ROOT / "raw_archive" / "br_players" / "alexaga01" / "shooting.html"


def _load(f: Path) -> str:
    assert f.exists(), f"夹具缺失: {f}"
    return f.read_text(encoding="utf-8")


# ── FakeDriver（贴合 common.browser 的 .get(url) / .page_source）──────────────
class FakeDriver:
    def __init__(self, html: str) -> None:
        self._html = html
        self.last_url: str = ""

    def get(self, url: str) -> None:
        self.last_url = url

    @property
    def page_source(self) -> str:
        return self._html


# ── MockConn / MockCursor（离线，记录 INSERT 以便断言）────────────────────────
class _MockCursor:
    def __init__(self, router, log):
        self._router = router
        self._log = log

    def execute(self, sql: str, params=None):
        self._log.append((sql, params))
        self._rows = self._router(sql, params or ())

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _MockConn:
    def __init__(self, router):
        self._router = router
        self.log: list = []
        self.committed = 0

    def cursor(self):
        return _MockCursor(self._router, self.log)

    def commit(self):
        self.committed += 1


def _make_router(inserts: list):
    """SQL 路由：player_onoff_404 的 INSERT 记入 inserts，其余返回空。"""

    def router(sql: str, params):
        s = sql
        if s.strip().upper().startswith("INSERT"):
            m = re.search(r"INSERT INTO (\w+)", s)
            table = m.group(1) if m else "?"
            inserts.append((table, params))
            return []
        return []

    return router


# ═══════════════════════════════════════════════════════════════════════════
# 1. 解析器：行数（常规 3 / 含季后赛 6）
# ═══════════════════════════════════════════════════════════════════════════
def test_parse_regular_only_3_rows():
    recs = parse_player_onoff_html(_load(FIXTURE_REG), "antetgi01", 2024)
    assert len(recs) == 3, f"常规赛样本应得 3 行，实得 {len(recs)}"
    sts = {r["season_type"] for r in recs}
    assert sts == {"Regular"}, sts
    splits = {r["split"] for r in recs}
    assert splits == {"On Court", "Off Court", "On-Off"}, splits


def test_parse_with_playoffs_6_rows():
    recs = parse_player_onoff_html(_load(FIXTURE_PO), "jamesle01", 2018)
    assert len(recs) == 6, f"含季后赛样本应得 6 行，实得 {len(recs)}"
    from collections import Counter
    cnt = Counter(r["season_type"] for r in recs)
    assert cnt == {"Regular": 3, "Playoffs": 3}, dict(cnt)
    # 每组 3 行 split 齐全
    for st in ("Regular", "Playoffs"):
        sp = {r["split"] for r in recs if r["season_type"] == st}
        assert sp == {"On Court", "Off Court", "On-Off"}, sp


# ═══════════════════════════════════════════════════════════════════════════
# 2. split 规范化
# ═══════════════════════════════════════════════════════════════════════════
def test_normalize_split_onoff_u2212():
    assert _normalize_split("On − Off") == "On-Off"      # U+2212
    assert _normalize_split("On \u2212 Off") == "On-Off"


def test_normalize_split_ascii_and_variants():
    assert _normalize_split("On - Off") == "On-Off"      # ASCII 连字符
    assert _normalize_split("On-Off") == "On-Off"
    assert _normalize_split("On Court") == "On Court"
    assert _normalize_split("Off Court") == "Off Court"
    assert _normalize_split(None) is None


# ═══════════════════════════════════════════════════════════════════════════
# 3. mp / min_pct 异构
# ═══════════════════════════════════════════════════════════════════════════
def test_mp_min_pct_heterogeneous():
    recs = parse_player_onoff_html(_load(FIXTURE_REG), "antetgi01", 2024)
    by_split = {r["split"]: r for r in recs}
    # On/Off Court：mp 有值、min_pct 空
    assert by_split["On Court"]["mp"] == 2580.0
    assert by_split["On Court"]["min_pct"] is None
    assert by_split["Off Court"]["mp"] == 1384.0
    assert by_split["Off Court"]["min_pct"] is None
    # On-Off：mp 空、min_pct 有值（来自 "65%"）
    assert by_split["On-Off"]["mp"] is None
    assert by_split["On-Off"]["min_pct"] == 65.0


def test_parse_mp_helper():
    assert _parse_mp("On Court", "2580") == (2580.0, None)
    assert _parse_mp("Off Court", "1384") == (1384.0, None)
    assert _parse_mp("On-Off", "65%") == (None, 65.0)
    # 兜底：以 % 结尾也走 min_pct
    assert _parse_mp("On Court", "12%") == (None, 12.0)
    # 空值
    assert _parse_mp("On Court", "") == (None, None)
    assert _parse_mp("On Court", None) == (None, None)


# ═══════════════════════════════════════════════════════════════════════════
# 4. 正负号解析（On-Off 行三列组语义）
#    efg_pct(team 组)=+.035；opp_efg_pct(opp 组)=-.004；
#    diff_efg_pct(Diff 组)=+.039 = team − opp ✓
# ═══════════════════════════════════════════════════════════════════════════
def test_sign_parsing_onoff_row_three_groups():
    recs = parse_player_onoff_html(_load(FIXTURE_REG), "antetgi01", 2024)
    onoff = next(r for r in recs if r["split"] == "On-Off")
    assert onoff["efg_pct"] == 0.035      # +.035
    assert onoff["opp_efg_pct"] == -0.004  # -.004
    assert onoff["diff_efg_pct"] == 0.039  # +.039 = team - opp
    assert onoff["off_rtg"] == 8.7
    assert onoff["opp_off_rtg"] == -1.3
    assert onoff["diff_off_rtg"] == 9.9


def test_sign_parsing_oncourt_row():
    recs = parse_player_onoff_html(_load(FIXTURE_REG), "antetgi01", 2024)
    onc = next(r for r in recs if r["split"] == "On Court")
    assert onc["efg_pct"] == 0.58
    assert onc["opp_efg_pct"] == 0.537
    assert onc["diff_efg_pct"] == 0.043   # 0.580 - 0.537


# ═══════════════════════════════════════════════════════════════════════════
# 5. build_url / build_rows
# ═══════════════════════════════════════════════════════════════════════════
def test_build_url_format():
    c = PlayerOnOffCrawler()
    assert c.build_url("antetgi01", 2014) == (
        "https://www.basketball-reference.com/players/a/antetgi01/on-off/2014"
    )
    # 字母取自 slug 首字符
    assert c.build_url("jamesle01", 2018) == (
        "https://www.basketball-reference.com/players/j/jamesle01/on-off/2018"
    )


def test_build_rows_injects_keys():
    c = PlayerOnOffCrawler()
    rec = {
        "season_type": "Regular", "split": "On-Off", "team_id": "MIL",
        "mp": None, "min_pct": 65.0,
        "efg_pct": 0.035, "opp_efg_pct": -0.004, "diff_efg_pct": 0.039,
        "off_rtg": 8.7, "opp_off_rtg": -1.3, "diff_off_rtg": 9.9,
    }
    row = c.build_rows(None, "antetgi01", 2024, "Regular", rec)
    assert row["player_id"] == "antetgi01"
    assert row["season"] == 2024
    assert row["season_type"] == "Regular"
    assert row["split"] == "On-Off"
    assert row["team_id"] == "MIL"
    assert row["mp"] is None and row["min_pct"] == 65.0
    assert row["efg_pct"] == 0.035
    assert row["diff_off_rtg"] == 9.9


# ═══════════════════════════════════════════════════════════════════════════
# 6. 404 隔离（运行时）：复合 PK (slug, year)
# ═══════════════════════════════════════════════════════════════════════════
def test_crawl_player_quarantines_404_composite_pk():
    inserts: list = []
    conn = _MockConn(_make_router(inserts))
    crawler = PlayerOnOffCrawler()
    # 404 路径若错误地写归档/解析，直接炸，证明被跳过
    crawler.save_raw_html = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("404 不应写 raw_archive"))
    crawler._consume_html = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("404 不应解析"))

    n = crawler._crawl_player(conn, FakeDriver(_load(FIXTURE_404)), "ghostslug01", 2020)

    assert n == 0, "404 页应返回 0 行"
    q = [p for (t, p) in inserts if t == "player_onoff_404"]
    assert q, "必须把 404 (slug,year) 隔离进 player_onoff_404"
    assert ("ghostslug01", 2020, "http_404") in q, "复合 PK + note 应为 http_404"
    assert not any(t == "crawl_failures" for (t, _) in inserts), \
        "404 不应污染 crawl_failures"


def test_crawl_player_real_page_not_quarantined():
    """对照：真实页（非 404）不得进 404 隔离表。

    upsert 走 mock（避免真实 psycopg2.extras.execute_values 调用），
    但保留 _consume_html 全链路（parse -> build_rows -> upsert），
    核心是断言真实页绝不触发 404 隔离分支。
    """
    inserts: list = []
    conn = _MockConn(_make_router(inserts))
    crawler = PlayerOnOffCrawler()
    crawler.upsert = lambda conn, rows: len(rows)  # mock：不触真实 DB
    n = crawler._crawl_player(conn, FakeDriver(_load(FIXTURE_REG)), "antetgi01", 2024)
    assert n == 3, f"真实页应解析出 3 行，实得 {n}"
    assert not any(t == "player_onoff_404" for (t, _) in inserts), \
        "真实页不得进 404 隔离表"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
