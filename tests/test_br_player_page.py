"""test_br_player_page.py — player_shooting 解析 / 入库 QA。

历史沿革（重要，勿回退）
------------------------
本文件最初测的是**生涯页**（career page）口径的 ``parse_player_shooting_html``
——它同时解析 ``shooting`` 与 ``shooting_playoffs`` 双表，并从 ``href`` 反推
赛季结束年。commit ``78faa41``（赛季分层优先级统一 + EPM 三源接入编排器）
把口径**有意改为逐季页**（per-season page）：解析函数换成
``parse_per_season_shooting``（只取 ``table#shooting`` 单表），BR 的 Playoffs
生涯汇总页已 404，逐季页不再提供，故输出恒为 1 条 Regular Season 记录。

原测试未同步该重构 → pytest 在**收集阶段**即 ImportError，整套测试跑不起来。
本次重写把测试对齐到当前口径，并补上此前**完全无覆盖**的活跃解析器。

夹具策略
--------
- **合成夹具**（本文件内联）：覆盖解析器的确定性契约，**不依赖 raw_archive**，
  CI（无归档数据）也能实跑。
- **归档夹具**（raw_archive/br_players_shooting/）：本地有 30 个 slug 的逐季页，
  用于真实页面回归；缺失即 skip（CI 无 raw_archive）。

DB 端到端需 ``PGPASSWORD``，缺失则 skip，不污染真实 player_shooting。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common.br_player_page import BRPlayerPageCrawler  # noqa: E402
from external_crawler.crawler.crawl_br_player_shooting import (  # noqa: E402
    PlayerShootingCrawler,
    parse_per_season_shooting,
)

# 归档逐季页夹具（本地有，CI 无）
ARCHIVE_ROOT = ROOT / "raw_archive" / "br_players_shooting"
ARCHIVE_FIXTURES = sorted(ARCHIVE_ROOT.glob("*/shooting_*.html"))


# ── 合成夹具：最小 BR 逐季 shooting 表 ──────────────────────────────────────
# 结构契约（解析器依赖）：
#   ① <table id="shooting">，逐季页唯一命中的表
#   ② 每行 <th data-stat="split_id"> 标类别、<th data-stat="split_value"> 标具体值
#   ③ 续行不带 split_id → 沿用上一行的类别
#   ④ 数值在 <td data-stat="fga"> / <td data-stat="fg_pct"> / fg_ast_pct
_SYNTH_ROWS = [
    # (split_id, split_value, fga, fg_pct, fg_ast_pct)
    ("Season", "Regular Season", "100", "0.465", ""),
    ("Shot Distance", "At Rim", "5", "0.660", ""),
    ("", "3 to <10 ft", "25", "0.400", ""),
    ("", "10 to <16 ft", "20", "0.500", ""),
    ("", "16 ft to <3-pt", "10", "0.350", ""),
    ("Shot Points", "2", "60", "0.500", "0.600"),
    ("Shot Points", "3", "40", "0.375", "0.800"),
    ("Shot Type", "Dunk", "5", "", ""),
]


def _synth_html(rows=_SYNTH_ROWS) -> str:
    parts = ['<html><body><table id="shooting"><tbody>']
    for sid, sval, fga, fgpct, astpct in rows:
        cells = []
        if sid:
            cells.append(f'<th data-stat="split_id">{sid}</th>')
        cells.append(f'<th data-stat="split_value">{sval.replace("<", "&lt;")}</th>')
        cells.append(f'<td data-stat="fga">{fga}</td>')
        if fgpct:
            cells.append(f'<td data-stat="fg_pct">{fgpct}</td>')
        if astpct:
            cells.append(f'<td data-stat="fg_ast_pct">{astpct}</td>')
        parts.append("<tr>" + "".join(cells) + "</tr>")
    parts.append("</tbody></table></body></html>")
    return "".join(parts)


# ── 1) 解析纯函数：确定性契约（合成夹具，CI 可跑）──────────────────────────
def test_parse_synthetic_returns_single_regular_row():
    rows = parse_per_season_shooting(_synth_html())
    assert len(rows) == 1
    rec = rows[0]
    assert rec["lg"] == "NBA"
    assert rec["season_type"] == "Regular Season"


def test_parse_synthetic_ratio_fields():
    rec = parse_per_season_shooting(_synth_html())[0]
    # 分档占比 = 该桶 fga / Season 桶 fga(=100)
    assert rec["percent_fga_from_x3_10_range"] == 0.25
    assert rec["percent_fga_from_x10_16_range"] == 0.20
    assert rec["percent_fga_from_x16_3p_range"] == 0.10
    assert rec["percent_fga_from_x3p_range"] == 0.40
    assert rec["percent_fga_from_x2p_range"] == 0.60
    # 0-3ft 由补集推导：1 - (25+20+10+40)/100 = 0.05
    assert rec["percent_fga_from_x0_3_range"] == 0.05


def test_parse_synthetic_percent_fields():
    rec = parse_per_season_shooting(_synth_html())[0]
    assert rec["fg_percent"] == 0.465
    assert rec["fg_percent_from_x2p_range"] == 0.500
    assert rec["fg_percent_from_x3p_range"] == 0.375
    assert rec["fg_percent_from_x3_10_range"] == 0.400
    assert rec["fg_percent_from_x10_16_range"] == 0.500
    assert rec["fg_percent_from_x16_3p_range"] == 0.350
    # 0-3ft 命中率用 At Rim 近似
    assert rec["fg_percent_from_x0_3_range"] == 0.660
    assert rec["percent_assisted_x2p_fg"] == 0.600
    assert rec["percent_assisted_x3p_fg"] == 0.800


def test_parse_synthetic_dunks():
    rec = parse_per_season_shooting(_synth_html())[0]
    assert rec["percent_dunks_of_fga"] == 0.05
    assert rec["num_of_dunks"] == 5


def test_parse_synthetic_unavailable_fields_are_none():
    """逐季页没有的字段必须显式 None，不得留 0/空串冒充有效值。"""
    rec = parse_per_season_shooting(_synth_html())[0]
    for k in ("avg_dist_fga", "weight", "percent_corner_3s_of_3pa",
              "corner_3_point_percent", "num_heaves_attempted", "num_heaves_made"):
        assert rec[k] is None, k


# ── 2) 边界：空输入 / 缺表 / 缺 Season 桶 / fga=0 ────────────────────────────
@pytest.mark.parametrize("bad", ["", None])
def test_parse_empty_input(bad):
    assert parse_per_season_shooting(bad) == []


def test_parse_without_shooting_table():
    html = "<html><body><table id='per_game'><tr><td>x</td></tr></table></body></html>"
    assert parse_per_season_shooting(html) == []


def test_parse_missing_season_bucket():
    """有 shooting 表但没有 ('Season','Regular Season') 行 → 无记录。"""
    rows = [("Shot Distance", "At Rim", "5", "0.66", "")]
    assert parse_per_season_shooting(_synth_html(rows)) == []


def test_parse_zero_fga_returns_empty():
    """Season 桶 fga=0 → 占比无意义，返回空（不得除零）。"""
    rows = [("Season", "Regular Season", "0", "0.000", "")]
    assert parse_per_season_shooting(_synth_html(rows)) == []


def test_parse_partial_rows_keeps_none():
    """缺 fga_ast_pct 时 assisted 字段为 None，而不是 0。"""
    rows = [
        ("Season", "Regular Season", "100", "0.465", ""),
        ("Shot Points", "3", "40", "0.375", ""),
    ]
    rec = parse_per_season_shooting(_synth_html(rows))[0]
    assert rec["percent_assisted_x3p_fg"] is None
    assert rec["percent_assisted_x2p_fg"] is None
    # 3pt 桶存在 → 占比可算
    assert rec["percent_fga_from_x3p_range"] == 0.40


# ── 3) build_rows 注入 player_id / season / team ────────────────────────────
def test_build_rows_injects_identity():
    crawler = PlayerShootingCrawler()
    rec = parse_per_season_shooting(_synth_html())[0]
    row = crawler.build_rows(conn=None, slug="brownja02", season=2004,
                             team="BOS", rec=rec)
    assert row["player_id"] == "brownja02"
    assert row["season"] == 2004
    assert row["team"] == "BOS"
    # rec 原字段保留
    assert row["lg"] == "NBA"
    assert row["fg_percent"] == rec["fg_percent"]


def test_crawler_conflict_key_and_min_season():
    assert PlayerShootingCrawler.CONFLICT_COLS == (
        "player_id", "season", "season_type", "team")
    assert BRPlayerPageCrawler.MIN_SEASON == 1997


# ── 4) 归档夹具回归（本地有则跑，CI 无 raw_archive → skip）──────────────────
@pytest.mark.skipif(not ARCHIVE_FIXTURES,
                    reason=f"归档夹具缺失: {ARCHIVE_ROOT}（CI 无 raw_archive）")
def test_archive_fixture_parses_or_empty():
    """真实逐季页：要么解析出 1 条，要么因页面结构不符返回空——不得抛异常。"""
    for f in ARCHIVE_FIXTURES[:5]:
        rows = parse_per_season_shooting(f.read_text(encoding="utf-8", errors="ignore"))
        assert isinstance(rows, list)
        for r in rows:
            assert r["lg"] == "NBA"
            assert r["season_type"] == "Regular Season"


# ── 5) 端到端入库 + 幂等（需 DB）────────────────────────────────────────────
@pytest.fixture(scope="module")
def db_conn():
    if not os.environ.get("PGPASSWORD"):
        pytest.skip("未设置 PGPASSWORD，跳过 DB 入库测试")
    import psycopg2
    try:
        conn = psycopg2.connect(
            host="127.0.0.1", port=5433, dbname="nba",
            user="postgres", password=os.environ["PGPASSWORD"],
        )
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"无法连接集群 B: {e}")
    yield conn
    conn.close()


def test_upsert_end_to_end_idempotent(db_conn):
    """对临时表执行 upsert，验证 ON CONFLICT 幂等（不污染真实 player_shooting）。"""
    cur = db_conn.cursor()
    cur.execute("DROP TABLE IF EXISTS player_shooting_test")
    cur.execute(
        "CREATE TEMP TABLE player_shooting_test (LIKE player_shooting INCLUDING ALL)"
    )
    cur.execute(
        "CREATE UNIQUE INDEX uq_test_key ON player_shooting_test "
        "(player_id, season, season_type, team)"
    )
    db_conn.commit()

    crawler = PlayerShootingCrawler()
    rec = parse_per_season_shooting(_synth_html())[0]
    rows = [crawler.build_rows(db_conn, "brownja02", 2004, "BOS", rec)]

    n1 = crawler._upsert_rows(db_conn, "player_shooting_test", rows,
                               crawler.CONFLICT_COLS)
    db_conn.commit()
    cur.execute("SELECT COUNT(*) FROM player_shooting_test")
    assert cur.fetchone()[0] == 1, "应写入 1 行"

    # 幂等：再次 upsert 同样数据，行数不变
    n2 = crawler._upsert_rows(db_conn, "player_shooting_test", rows,
                               crawler.CONFLICT_COLS)
    db_conn.commit()
    cur.execute("SELECT COUNT(*) FROM player_shooting_test")
    assert cur.fetchone()[0] == 1, "重放后行数应仍为 1（幂等）"
    assert n1 == 1 and n2 == 1
    cur.execute("DROP TABLE IF EXISTS player_shooting_test")
    db_conn.commit()


def test_enumerate_players_returns_slugs(db_conn):
    """枚举宇宙应返回非空 slug 列表。"""
    crawler = PlayerShootingCrawler()
    slugs = crawler.enumerate_players(db_conn, priority_gap=False)
    assert isinstance(slugs, list) and len(slugs) > 0
    assert any(s for s in slugs)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
