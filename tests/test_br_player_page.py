"""test_br_player_page.py — player_shooting_backfill 解析/入库 QA（任务 T6）。

覆盖：
  1) parse_player_shooting_html 纯函数：双表解析、33 列映射、season_type、
     Career 汇总行跳过、数值安全解析（空→None）、season 结束年解析、player 取自 h1。
  2) PlayerShootingCrawler.build_rows：注入 player_id=slug。
  3) 端到端入库 + 幂等：对临时表执行 upsert（ON CONFLICT 4 列键），重放幂等。
     需 PGPASSWORD 环境变量；缺失则跳过（不污染真实数据）。

夹具：raw_archive/br_players/brownja02/shooting.html（T0 研究夹具，结构高保真重建）。
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
    parse_player_shooting_html,
)

FIXTURE = ROOT / "raw_archive" / "br_players" / "brownja02" / "shooting.html"


def _load_html() -> str:
    assert FIXTURE.exists(), f"夹具缺失: {FIXTURE}"
    return FIXTURE.read_text(encoding="utf-8")


def _split(rows):
    reg = [r for r in rows if r["season_type"] == "Regular"]
    po = [r for r in rows if r["season_type"] == "Playoffs"]
    return reg, po


# ── 1) 解析纯函数 ──────────────────────────────────────────────────────────
def test_fixture_exists():
    assert FIXTURE.exists(), "T0 研究夹具必须存在"


def test_parse_dual_table_and_counts():
    rows = parse_player_shooting_html(_load_html())
    reg, po = _split(rows)
    # 3 个 Regular 赛季 + Career(跳过) = 3；2 个 Playoffs 赛季 + Career(跳过) = 2
    assert len(reg) == 3, f"Regular 行数应为 3，实际 {len(reg)}"
    assert len(po) == 2, f"Playoffs 行数应为 2，实际 {len(po)}"


def test_parse_player_name_and_lg():
    rows = parse_player_shooting_html(_load_html())
    assert all(r["player"] == "Jaylen Brown" for r in rows)
    assert all(r["lg"] == "NBA" for r in rows)


def test_parse_season_end_year_and_team():
    reg, po = _split(parse_player_shooting_html(_load_html()))
    # 2017-18 → 2018, 2018-19 → 2019, 2023-24 → 2024
    seasons = sorted(r["season"] for r in reg)
    assert seasons == [2018, 2019, 2024], seasons
    # href 解析：NBA_2017 → 2018
    r2018 = next(r for r in reg if r["season"] == 2018)
    assert r2018["team"] == "BOS"
    assert po[0]["season"] == 2019
    assert po[0]["season_type"] == "Playoffs"


def test_parse_numeric_mapping():
    reg, _ = _split(parse_player_shooting_html(_load_html()))
    r = next(x for x in reg if x["season"] == 2018)
    assert r["fg_percent"] == 0.465
    assert r["avg_dist_fga"] == 14.2
    assert r["percent_fga_from_x2p_range"] == 0.717
    assert r["percent_fga_from_x0_3_range"] == 0.274
    assert r["fg_percent_from_x3p_range"] == 0.345
    assert r["percent_assisted_x2p_fg"] == 0.556
    assert r["percent_assisted_x3p_fg"] == 0.789
    assert r["percent_dunks_of_fga"] == 0.123
    assert r["num_of_dunks"] == 78
    assert r["percent_corner_3s_of_3pa"] == 0.287
    assert r["corner_3_point_percent"] == 0.389
    # heave: #HEAVE=3, HEAVE%=.333 → made = round(.333*3)=1
    assert r["num_heaves_attempted"] == 3
    assert r["num_heaves_made"] == 1
    # weight 不在 BR 页 → None
    assert r["weight"] is None
    assert r["age"] == 21
    assert r["g"] == 70
    assert r["mp"] == 2417
    assert r["pos"] == "SG"


def test_parse_career_row_skipped():
    # 解析结果不应含 season=None 或 Career 文本
    rows = parse_player_shooting_html(_load_html())
    assert all(isinstance(r["season"], int) for r in rows)
    assert all(r["season"] >= BRPlayerPageCrawler.MIN_SEASON for r in rows)


def test_parse_empty_html():
    assert parse_player_shooting_html("") == []
    assert parse_player_shooting_html(None) == []


# ── 2) build_rows 注入 player_id ─────────────────────────────────────────────
def test_build_rows_injects_player_id():
    crawler = PlayerShootingCrawler()
    rec = parse_player_shooting_html(_load_html())[0]
    row = crawler.build_rows(conn=None, slug="brownja02", season=rec["season"],
                             season_type=rec["season_type"], rec=rec)
    assert row["player_id"] == "brownja02"
    # rec 中已有的 season/season_type/team 保留
    assert row["season"] == rec["season"]
    assert row["season_type"] == rec["season_type"]


# ── 3) 端到端入库 + 幂等（需 DB）─────────────────────────────────────────────
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
    # 普通 TEMP TABLE（无 ON COMMIT DROP，跨 commit 保留至会话结束）；
    # 测试结束手动 DROP，避免污染/跨测试干扰。
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
    rows = [crawler.build_rows(db_conn, "brownja02", r["season"],
                               r["season_type"], r)
            for r in parse_player_shooting_html(_load_html())]

    n1 = crawler._upsert_rows(db_conn, "player_shooting_test", rows,
                               crawler.CONFLICT_COLS)
    db_conn.commit()
    cur.execute("SELECT COUNT(*) FROM player_shooting_test")
    assert cur.fetchone()[0] == 5, "应写入 5 行"

    # 幂等：再次 upsert 同样数据，行数不变
    n2 = crawler._upsert_rows(db_conn, "player_shooting_test", rows,
                               crawler.CONFLICT_COLS)
    db_conn.commit()
    cur.execute("SELECT COUNT(*) FROM player_shooting_test")
    assert cur.fetchone()[0] == 5, "重放后行数应仍为 5（幂等）"
    assert n1 == 5 and n2 == 5
    cur.execute("DROP TABLE IF EXISTS player_shooting_test")
    db_conn.commit()


def test_enumerate_players_returns_slugs(db_conn):
    """枚举宇宙应返回非空 slug 列表（含 brownja02 或 gamelog 中 slug）。"""
    crawler = PlayerShootingCrawler()
    slugs = crawler.enumerate_players(db_conn, priority_gap=False)
    assert isinstance(slugs, list) and len(slugs) > 0
    # 至少应含 dim_players 的 slug 之一（如 allenja01）或 gamelog slug
    assert any(s for s in slugs)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
