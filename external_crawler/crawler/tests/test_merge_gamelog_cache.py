"""独立回归测试：merge_gamelog_cache 的 MERGE 语义 + 覆盖 bug 修复证明。

纯文件级测试，不依赖任何 DB 连接。每个 case 都使用独立的临时缓存目录
(tempfile.TemporaryDirectory)，case 结束自动清理，绝不触碰项目既有缓存。

运行：
    python -m pytest external_crawler/crawler/tests/test_merge_gamelog_cache.py -v
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# 让 crawler 包可被 import（tests/ 的父目录即 crawler 目录）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import crawl_br_gamelog as br_gamelog  # noqa: E402

SEASON = 2024
CACHE_FILE = f"gamelog_{SEASON}.json"


# ── 测试夹具构造 helpers ───────────────────────────────────────────────────

def _player(pid, games, name=None):
    """构造一个缓存球员条目。player_id 必须有，且作为 merge 去重键。"""
    return {"player": name or f"Player {pid}", "player_id": pid, "games": games}


def _write_old_cache(cache_dir, players):
    """把一批球员写成旧缓存文件 gamelog_<season>.json。"""
    path = os.path.join(cache_dir, CACHE_FILE)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"season": SEASON, "players": players}, fh, ensure_ascii=False)


def _read_cache(cache_dir):
    """读回合并后写出的缓存文件，返回其 JSON 字典。"""
    path = os.path.join(cache_dir, CACHE_FILE)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _index_by_id(players):
    return {p["player_id"]: p for p in players}


# ── 场景 1：空旧缓存（旧文件不存在）───────────────────────────────────────

def test_empty_old_cache_creates_file_with_new_players():
    """旧缓存文件不存在 → 直接创建并写入 new_players。"""
    new_players = [
        _player("aaa01", [{"game_id": "1", "pts": 10}]),
        _player("aaa02", [{"game_id": "2", "pts": 20}]),
    ]
    with tempfile.TemporaryDirectory() as cache_dir:
        out_path = br_gamelog.merge_gamelog_cache(SEASON, new_players, cache_dir)

        # 返回了正确的文件
        assert os.path.basename(out_path) == CACHE_FILE
        assert os.path.exists(out_path)

        data = _read_cache(cache_dir)
        players = data["players"]
        # 人数 == new 的人数（空旧缓存，没有额外内容）
        assert len(players) == len(new_players)
        indexed = _index_by_id(players)
        assert "aaa01" in indexed
        assert "aaa02" in indexed
        # games 内容被正确写入
        assert indexed["aaa01"]["games"] == [{"game_id": "1", "pts": 10}]


# ── 场景 2：完全无交集 ─────────────────────────────────────────────────────

def test_disjoint_sets_keep_both_sides():
    """old 与 new 集合不相交 → 合并后包含双方（人数 = old + new）。"""
    old_players = [_player("old001", [{"g": 1}]), _player("old002", [{"g": 2}])]
    new_players = [_player("new001", [{"g": 3}]), _player("new002", [{"g": 4}])]
    with tempfile.TemporaryDirectory() as cache_dir:
        _write_old_cache(cache_dir, old_players)

        br_gamelog.merge_gamelog_cache(SEASON, new_players, cache_dir)

        data = _read_cache(cache_dir)
        players = data["players"]
        # 关键断言：人数 = old + new，旧不曾丢失
        assert len(players) == len(old_players) + len(new_players)
        indexed = _index_by_id(players)
        assert set(indexed.keys()) == {"old001", "old002", "new001", "new002"}
        # 旧内容保留
        assert indexed["old001"]["games"] == [{"g": 1}]
        assert indexed["old002"]["games"] == [{"g": 2}]
        # 新内容追加
        assert indexed["new001"]["games"] == [{"g": 3}]
        assert indexed["new002"]["games"] == [{"g": 4}]


# ── 场景 3：完全重叠（新抓覆盖旧）─────────────────────────────────────────

def test_full_overlap_new_overrides_old():
    """new 的 player_id 全部在旧里 → 旧对应内容被新抓数据完全覆盖。"""
    old_players = [
        _player("ovr001", [{"g": 1, "pts": 999}], name="OLD A"),
        _player("ovr002", [{"g": 2, "pts": 888}], name="OLD B"),
    ]
    new_players = [
        _player("ovr001", [{"g": 1, "pts": 11}], name="NEW A"),
        _player("ovr002", [{"g": 2, "pts": 22}], name="NEW B"),
    ]
    with tempfile.TemporaryDirectory() as cache_dir:
        _write_old_cache(cache_dir, old_players)

        br_gamelog.merge_gamelog_cache(SEASON, new_players, cache_dir)

        data = _read_cache(cache_dir)
        players = data["players"]
        # 人数不变（全重叠，没有新增）
        assert len(players) == len(old_players)
        indexed = _index_by_id(players)
        # 关键断言：以新为准，绝非旧残余
        assert indexed["ovr001"] == new_players[0]
        assert indexed["ovr002"] == new_players[1]
        assert indexed["ovr001"]["games"] == [{"g": 1, "pts": 11}]


# ── 场景 4：部分重叠（混合）──────────────────────────────────────────────

def test_partial_overlap_mixed_merge():
    """混合：旧无交集的保留、新无交集的追加、重叠的以新为准。"""
    old_players = [
        _player("pA", [{"g": 1}], name="A-old"),   # 仅旧
        _player("pB", [{"g": 2}], name="B-old"),   # 重叠（被新覆盖）
        _player("pC", [{"g": 3}], name="C-old"),   # 仅旧
    ]
    new_players = [
        _player("pB", [{"g": 22}], name="B-new"),  # 重叠（覆盖）
        _player("pD", [{"g": 4}], name="D-new"),   # 仅新
    ]
    with tempfile.TemporaryDirectory() as cache_dir:
        _write_old_cache(cache_dir, old_players)

        br_gamelog.merge_gamelog_cache(SEASON, new_players, cache_dir)

        data = _read_cache(cache_dir)
        players = data["players"]
        # 人数：A, B, C（旧）+ D（新追加），B 重叠不增不减 → 4
        assert len(players) == 4
        indexed = _index_by_id(players)
        # 旧中无交集的保留
        assert indexed["pA"] == old_players[0]
        assert indexed["pC"] == old_players[2]
        # 新中无交集的追加
        assert indexed["pD"] == new_players[1]
        # 重叠的以新为准
        assert indexed["pB"] == new_players[0]
        assert indexed["pB"]["games"] == [{"g": 22}]


# ── 场景 5：回归 case（最关键）────────────────────────────────────────────

def test_regression_390_old_plus_1_new_gives_391_not_1():
    """原 bug 复现：390 人旧缓存 + 1 个新球员 → 应得 391 人，而非 1 人。

    该 bug 的根因是把 MERGE 写成了 OVERWRITE：每轮只回写本轮新抓的球员，
    旧缓存被削成仅本轮回新抓的内容。这里用大基数（390）放大验证——
    若仍是 OVERWRITE 语义，结果只会是 1 人（仅 new_players）。
    """
    old_ids = [f"r{i:04d}" for i in range(390)]  # r0000 .. r0389
    old_players = [_player(pid, [{"g": i}]) for i, pid in enumerate(old_ids)]
    new_players = [_player("rNEW1", [{"g": 9999}])]  # 1 个全新球员

    with tempfile.TemporaryDirectory() as cache_dir:
        _write_old_cache(cache_dir, old_players)

        out_path = br_gamelog.merge_gamelog_cache(SEASON, new_players, cache_dir)

        data = _read_cache(cache_dir)
        players = data["players"]
        # 反 bug 硬断言：绝不可能是 1 人（OVERWRITE 的错误结果）
        assert len(players) != 1, "BUG 复现：缓存被写成了仅本轮回新抓的 1 人"
        # 正确结果：390 旧 + 1 新 = 391
        assert len(players) == 391, f"期望 391 人，实际 {len(players)} 人"
        indexed = _index_by_id(players)
        # 旧缓存完整保留
        assert "r0000" in indexed and "r0389" in indexed
        assert indexed["r0000"]["games"] == [{"g": 0}]
        # 新球员正确追加
        assert "rNEW1" in indexed
        assert indexed["rNEW1"]["games"] == [{"g": 9999}]
        # season 字段保持正确
        assert data["season"] == SEASON
        assert os.path.exists(out_path)
