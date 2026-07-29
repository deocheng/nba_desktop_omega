"""test_parse_player_lineups.py — BR 球员 lineup 解析/入库/隔离 QA。

覆盖：
  1) parse_player_lineups_html 纯函数：空 HTML 处理、双表探测、5 人组合抽取、
     diff_* 净差列解析（含 +/-）、mp(M:SS)→总秒、season_type 标注。
  2) PlayerLineupCrawler.build_rows：lineup_key 排序、player_id 注入、5×字段展开、
     ranker/team_id/minutes/diff_* 透传、csk 校验。
  3) build_url：URL 格式正确。
  4) _player_done：(slug, year) 断点续跑判定（mock DB）。
  5) _quarantine_slug：(slug, year) 复合 PK 404 隔离（mock DB）。
  6) enumerate_lineup_targets：排除已落库 + 已隔离（mock DB）。
  7) 端到端 upsert 幂等（需 DB；缺失则 skip）。

夹具：tests/fixtures/lineups_2014_sample.html（真实结构，antetgi01/2014 样本，
  lineups-5-man 表 + 22 个 diff_* 列；2026-07-24 定稿）。
不含占位符——解析细节直接用真实 HTML 断言。

DB 相关用例使用 MockConn（不连真实库），全部在 sandbox 离线跑；
不含任何 BR 网络请求。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common.br_player_lineup import BRPlayerLineupCrawlerBase  # noqa: E402
from external_crawler.crawler.crawl_br_player_lineup import (  # noqa: E402
    DIFF_STATS,
    PlayerLineupCrawler,
    parse_minutes,
    parse_player_lineups_html,
)

FIXTURE = ROOT / "tests" / "fixtures" / "lineups_2014_sample.html"
# 多阵容人数样本：lineups-5/4/3/2-man 四表齐全（各 10 行，Regular）。
FIXTURE_MULTI = ROOT / "tests" / "fixtures" / "lineups_2001_multi_sample.html"


def _load_html() -> str:
    assert FIXTURE.exists(), f"夹具缺失: {FIXTURE}"
    return FIXTURE.read_text(encoding="utf-8")


# ── 测试用 MockConn / MockCursor（离线，记录所有 SQL 以便断言）──────────────
class _MockCursor:
    def __init__(self, router, log):
        self._router = router
        self._log = log
        self._rows: list = []

    def execute(self, sql: str, params=None):
        self._log.append((sql, params))
        self._rows = self._router(sql, params or [])

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


def _make_router(inserts: list, done_slugs: set = None):
    """SQL 路由：_player_done / _quarantine_slug / enumerate / INSERT 分流。"""
    done = done_slugs or set()

    def router(sql: str, params):
        s = sql.strip().upper()
        if s.startswith("INSERT"):
            m = re.search(r"INSERT INTO (\w+)", sql)
            table = m.group(1) if m else "?"
            inserts.append((table, params))
            return []
        # _player_done: SELECT 1 FROM player_lineups WHERE player_id=... AND season=...
        if "FROM player_lineups" in sql and "WHERE player_id" in sql \
                and "LIMIT 1" in sql.upper():
            if params and len(params) >= 2 and (params[0], params[1]) in done:
                return [(1,)]
            return []
        # enumerate_lineup_targets: SELECT DISTINCT ps.player_id ... FROM player_shooting
        if "FROM player_shooting" in sql and "player_lineups_404" in sql:
            return [("goodslug01", 2014), ("goodslug02", 2015)]
        return []

    return router


# ═════════════════════════════════════════════════════════════════════════
# 1) build_url 格式校验（纯函数，不抓 BR）
# ═════════════════════════════════════════════════════════════════════════
def test_build_url_format():
    """build_url 应返回正确的 /players/{letter}/{slug}/lineups/{year} 格式。"""
    c = PlayerLineupCrawler()
    url = c.build_url("antetgi01", 2014)
    assert url == (
        "https://www.basketball-reference.com/players/a/antetgi01/lineups/2014"
    ), url


def test_build_url_different_slug_and_year():
    c = PlayerLineupCrawler()
    url = c.build_url("jamesle01", 2026)
    assert url == (
        "https://www.basketball-reference.com/players/j/jamesle01/lineups/2026"
    ), url


def test_build_url_class_constants():
    """类常量应与设计一致。"""
    assert BRPlayerLineupCrawlerBase.DOMAIN == "player_lineup"
    assert BRPlayerLineupCrawlerBase.TASK_TYPE == "br_player_lineup"
    assert BRPlayerLineupCrawlerBase.TABLE == "player_lineups"
    assert BRPlayerLineupCrawlerBase.QUARANTINE_TABLE == "player_lineups_404"
    assert BRPlayerLineupCrawlerBase.CONFLICT_COLS == (
        "player_id", "season", "season_type", "lineup_size", "lineup_key")
    assert BRPlayerLineupCrawlerBase.MIN_SEASON == 1997
    assert BRPlayerLineupCrawlerBase.MAX_SEASON == 2026


# ═════════════════════════════════════════════════════════════════════════
# 2) parse_player_lineups_html 纯函数 — 空值处理
# ═════════════════════════════════════════════════════════════════════════
def test_parse_empty_html():
    assert parse_player_lineups_html("") == []
    assert parse_player_lineups_html(None) == []


def test_parse_no_lineups_table():
    """无 #lineups-5-man 表的 HTML 应返回空列表。"""
    html = "<html><body><h1>Not Found</h1></body></html>"
    assert parse_player_lineups_html(html) == []


def test_parse_minutes_helper():
    """parse_minutes 应把 M:SS 解析为总秒数，异常值返回 None。"""
    assert parse_minutes("132:57") == 7977
    assert parse_minutes("0:00") == 0
    assert parse_minutes("5") == 5
    assert parse_minutes(None) is None
    assert parse_minutes("") is None
    assert parse_minutes("garbage") is None


# ═════════════════════════════════════════════════════════════════════════
# 3) parse_player_lineups_html — 真实 fixture 结构校验
# ═════════════════════════════════════════════════════════════════════════
def test_parse_real_fixture_structure():
    """真实 fixture（lineups-5-man）应解析出 ≥1 行，每行 5 人、Regular、size=5。"""
    html = _load_html()
    rows = parse_player_lineups_html(html)
    assert len(rows) > 0, "真实 HTML 应解析出至少 1 行"
    for r in rows:
        assert len(r["players"]) == 5, "每行 players 长度须为 5"
        assert r["lineup_size"] == 5, "5-man 表解析出的行 size 须为 5"
        assert r["season_type"] == "Regular", \
            "本样本无 Playoffs 表，season_type 应为 Regular"


def test_parse_real_fixture_all_four_sizes():
    """真实 fixture（5/4/3/2-man 四表齐全）应解析出全部 4 种阵容人数，
    每种 10 行、行内人数 == lineup_size、Regular。"""
    html = FIXTURE_MULTI.read_text(encoding="utf-8")
    rows = parse_player_lineups_html(html)
    # 按阵容人数分组计数
    by_size: dict = {}
    for r in rows:
        by_size.setdefault(r["lineup_size"], 0)
        by_size[r["lineup_size"]] += 1
        assert len(r["players"]) == r["lineup_size"], \
            f"人数 {len(r['players'])} != size {r['lineup_size']}"
        assert r["season_type"] == "Regular"
    # 期望：5/4/3/2-man 各 10 行（共 40）
    assert set(by_size.keys()) == {2, 3, 4, 5}, \
        f"应覆盖 2/3/4/5-man，实际 {sorted(by_size)}"
    for sz in (2, 3, 4, 5):
        assert by_size[sz] == 10, f"size={sz} 应 10 行，实际 {by_size[sz]}"


def test_parse_real_fixture_diff_fields():
    """真实 fixture 首行的 diff_* / ranker / team_id / minutes 应正确解析。"""
    html = _load_html()
    rows = parse_player_lineups_html(html)
    r = rows[0]
    # 首行：Rk=1, Tm=MIL, MP=132:57 → 7977 秒
    assert r["ranker"] == 1
    assert r["team_id"] == "MIL"
    assert r["minutes"] == 7977, "MP=132:57 应解析为 7977 秒"
    # diff_*（带 +/- 符号，safe_float 处理）
    assert r["diff_fg"] == 5.2
    assert r["diff_fga"] == 1.8
    assert r["diff_fg_pct"] == 0.05, "+.050 → 0.05"
    assert r["diff_pts"] == 2.4
    assert r["diff_ft"] == -10.2, "负值应保留符号"
    assert r["diff_blk"] == -3.0
    # 22 个 diff_* 列应全部出现在记录中
    for ds in DIFF_STATS:
        assert ds in r, f"记录缺少 diff 列 {ds}"


def test_parse_real_fixture_skips_summary_row():
    """汇总行（Player Average，无 <a> 链接）应被跳过；
    每行球员数须 == 其 lineup_size（大小混合也成立）。"""
    html = _load_html()
    rows = parse_player_lineups_html(html)
    assert len(rows) > 0
    for r in rows:
        # 汇总行无 link → 跳过；故解析出的每行人数必 == lineup_size
        assert len(r["players"]) == r["lineup_size"], \
            f"人数 {len(r['players'])} != size {r['lineup_size']}"


# ═════════════════════════════════════════════════════════════════════════
# 4) build_rows — lineup_key 排序 + player_id 注入 + 5×字段展开
# ═════════════════════════════════════════════════════════════════════════
def test_build_rows_lineup_key_sorted():
    """lineup_key 应为 5 个 br_player_id 排序后 '|' 连接。"""
    crawler = PlayerLineupCrawler()
    rec = {
        "season_type": "Regular",
        "players": [
            ("zebra01", "Zebra Player"),
            ("alpha01", "Alpha Player"),
            ("mike001", "Mike Player"),
            ("bravo01", "Bravo Player"),
            ("char01", "Charlie Player"),
        ],
        "ranker": 1, "team_id": "MIL", "minutes": 100,
    }
    row = crawler.build_rows(conn=None, slug="testslg", season=2014,
                             season_type="Regular", rec=rec)
    # 排序后: alpha01|bravo01|char01|mike001|zebra01
    assert row["lineup_key"] == "alpha01|bravo01|char01|mike001|zebra01", \
        row["lineup_key"]


def test_build_rows_lineup_key_no_slug_fallback_to_names():
    """无 slug 时 lineup_key 退回按 player_name 排序。"""
    crawler = PlayerLineupCrawler()
    rec = {
        "season_type": "Regular",
        "players": [
            (None, "Zebra Player"),
            (None, "Alpha Player"),
            (None, "Mike Player"),
            (None, "Bravo Player"),
            (None, "Charlie Player"),
        ],
    }
    row = crawler.build_rows(conn=None, slug="testslg", season=2014,
                             season_type="Regular", rec=rec)
    assert row["lineup_key"] == "Alpha Player|Bravo Player|Charlie Player|Mike Player|Zebra Player", \
        row["lineup_key"]


def test_build_rows_injects_player_id_and_season():
    """build_rows 应注入 player_id=slug / season / season_type。"""
    crawler = PlayerLineupCrawler()
    rec = {
        "season_type": "Regular",
        "players": [(f"slug{i}", f"Player{i}") for i in range(1, 6)],
    }
    row = crawler.build_rows(conn=None, slug="antetgi01", season=2014,
                             season_type="Regular", rec=rec)
    assert row["player_id"] == "antetgi01"
    assert row["season"] == 2014
    assert row["season_type"] == "Regular"


def test_build_rows_expands_5_br_player_ids_and_names():
    """build_rows 应展开 5× br_player_id / player_name。"""
    crawler = PlayerLineupCrawler()
    players = [(f"slug{i}", f"Player{i}") for i in range(1, 6)]
    rec = {"season_type": "Regular", "players": players}
    row = crawler.build_rows(conn=None, slug="test", season=2014,
                             season_type="Regular", rec=rec)
    for i, (slug, name) in enumerate(players, start=1):
        assert row[f"br_player_id{i}"] == slug
        assert row[f"player_name{i}"] == name


def test_build_rows_passes_numeric_and_diff_fields():
    """build_rows 应透传 ranker / team_id / minutes / 22 个 diff_*。"""
    crawler = PlayerLineupCrawler()
    rec = {
        "season_type": "Regular",
        "players": [(f"s{i}", f"P{i}") for i in range(5)],
        "ranker": 3, "team_id": "MIL", "minutes": 7977,
        "diff_fg": 5.2, "diff_fga": 1.8, "diff_fg_pct": 0.05,
        "diff_fg3": 2.2, "diff_fg3a": 2.8, "diff_fg3_pct": 0.058,
        "diff_efg_pct": 0.061, "diff_ft": -10.2, "diff_fta": -9.3,
        "diff_ft_pct": -0.149, "diff_pts": 2.4, "diff_orb": 0.2,
        "diff_orb_pct": 0.2, "diff_drb": -0.3, "diff_drb_pct": 0.2,
        "diff_trb": 0.2, "diff_trb_pct": 0.4, "diff_ast": 2.9,
        "diff_stl": -0.1, "diff_blk": -3.0, "diff_tov": 0.7,
        "diff_pf": 0.6,
    }
    row = crawler.build_rows(conn=None, slug="t", season=2014,
                             season_type="Regular", rec=rec)
    assert row["ranker"] == 3
    assert row["team_id"] == "MIL"
    assert row["minutes"] == 7977
    assert row["diff_fg"] == 5.2
    assert row["diff_fg_pct"] == 0.05
    assert row["diff_ft"] == -10.2
    assert row["diff_blk"] == -3.0
    for ds in DIFF_STATS:
        assert ds in row, f"build_rows 缺 diff 列 {ds}"


# ═════════════════════════════════════════════════════════════════════════
# 5) _player_done — (slug, year) 断点续跑判定（mock DB）
# ═════════════════════════════════════════════════════════════════════════
def test_player_done_returns_true_for_done_pair():
    """已落库的 (slug, year) 应返回 True。"""
    inserts: list = []
    router = _make_router(inserts, done_slugs={("antetgi01", 2014)})
    conn = _MockConn(router)
    crawler = PlayerLineupCrawler()
    assert crawler._player_done(conn, "antetgi01", 2014) is True


def test_player_done_returns_false_for_undone_pair():
    """未落库的 (slug, year) 应返回 False。"""
    inserts: list = []
    router = _make_router(inserts, done_slugs=set())
    conn = _MockConn(router)
    crawler = PlayerLineupCrawler()
    assert crawler._player_done(conn, "antetgi01", 2014) is False


# ═════════════════════════════════════════════════════════════════════════
# 6) _quarantine_slug — (slug, year) 复合 PK 404 隔离（mock DB）
# ═════════════════════════════════════════════════════════════════════════
def test_quarantine_slug_inserts_composite_pk():
    """_quarantine_slug 应写 player_lineups_404 (slug, year, note) 复合 PK。"""
    inserts: list = []
    router = _make_router(inserts)
    conn = _MockConn(router)
    crawler = PlayerLineupCrawler()
    crawler._quarantine_slug(conn, "badslug01", 2005, note="http_404")
    q = [p for (t, p) in inserts if t == "player_lineups_404"]
    assert q, "必须把 404 (slug, year) 隔离进 player_lineups_404"
    # 参数应为 (slug, year, note) 三元组
    assert ("badslug01", 2005, "http_404") in q, \
        f"隔离参数应为 (slug, year, note)，实际 {q}"


def test_quarantine_slug_uses_on_conflict_composite():
    """隔离 SQL 应使用 ON CONFLICT (slug, year) 复合键。"""
    inserts: list = []
    router = _make_router(inserts)
    conn = _MockConn(router)
    crawler = PlayerLineupCrawler()
    crawler._quarantine_slug(conn, "s1", 2010)
    sql = next((s for (s, _) in conn.log
                if "INSERT INTO player_lineups_404" in s), "")
    assert sql, "必须发出 player_lineups_404 INSERT"
    assert "ON CONFLICT (slug, year)" in sql, \
        "隔离 SQL 必须用复合 PK (slug, year) ON CONFLICT"


# ═════════════════════════════════════════════════════════════════════════
# 7) enumerate_lineup_targets — 排除已落库 + 已隔离（mock DB）
# ═════════════════════════════════════════════════════════════════════════
def test_enumerate_lineup_targets_returns_pairs():
    """enumerate_lineup_targets 应返回 (slug, year) 对列表。"""
    inserts: list = []
    router = _make_router(inserts)
    conn = _MockConn(router)
    crawler = PlayerLineupCrawler()
    targets = crawler.enumerate_lineup_targets(conn)
    assert isinstance(targets, list)
    assert len(targets) == 2
    assert all(isinstance(t, tuple) and len(t) == 2 for t in targets)
    assert ("goodslug01", 2014) in targets
    assert ("goodslug02", 2015) in targets


def test_enumerate_lineup_targets_uses_player_shooting_universe():
    """枚举 SQL 应从 player_shooting 取宇宙，排除 player_lineups_404。"""
    inserts: list = []
    router = _make_router(inserts)
    conn = _MockConn(router)
    crawler = PlayerLineupCrawler()
    crawler.enumerate_lineup_targets(conn)
    sql = next((s for (s, _) in conn.log
                if "FROM player_shooting" in s and "player_lineups_404" in s), "")
    assert sql, "必须发出 player_shooting 宇宙查询"
    # 禁用 player_gamelog
    assert "player_gamelog" not in sql, \
        "enumerate_lineup_targets 禁用 player_gamelog（corrupt）"
    assert "player_lineups_404" in sql, "必须 LEFT JOIN 404 隔离表排除已隔离"
    assert "NOT EXISTS" in sql, "必须排除已落库 player_lineups"


# ═════════════════════════════════════════════════════════════════════════
# 8) save_raw_html — 归档路径
# ═════════════════════════════════════════════════════════════════════════
def test_save_raw_html_path(tmp_path):
    """save_raw_html 应写到 raw_archive/br_players/{slug}/lineups_{year}.html。"""
    crawler = PlayerLineupCrawler()
    # 临时覆盖 RAW_ARCHIVE 到 tmp_path
    crawler.RAW_ARCHIVE = str(tmp_path / "raw_archive" / "br_players")
    path = crawler.save_raw_html("antetgi01", 2014, "<html>test</html>")
    assert path.exists()
    assert path.name == "lineups_2014.html"
    assert "antetgi01" in str(path)
    assert path.read_text(encoding="utf-8") == "<html>test</html>"


# ═════════════════════════════════════════════════════════════════════════
# 9) 端到端 upsert 幂等（需 DB；缺失则 skip）
# ═════════════════════════════════════════════════════════════════════════
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
    """对临时表执行 upsert，验证 ON CONFLICT 幂等（不污染真实 player_lineups）。"""
    cur = db_conn.cursor()
    # 确保主表存在（DDL 幂等）
    ddl = (ROOT / "docs" / "ddl_player_lineups.sql").read_text(encoding="utf-8")
    cur.execute(ddl)
    db_conn.commit()

    # 临时表（LIKE player_lineups INCLUDING ALL）
    cur.execute("DROP TABLE IF EXISTS player_lineups_test")
    cur.execute(
        "CREATE TEMP TABLE player_lineups_test (LIKE player_lineups INCLUDING ALL)"
    )
    db_conn.commit()

    crawler = PlayerLineupCrawler()
    # 构造 2 行测试数据（diff_* 模型）
    def _rec(slugs, **kw):
        return {
            "season_type": "Regular",
            "lineup_size": kw.get("lineup_size", len(slugs)),
            "players": [(s, f"Player {s}") for s in slugs],
            "ranker": kw.get("ranker", 1),
            "team_id": kw.get("team_id", "MIL"),
            "minutes": kw.get("minutes", 100),
            "diff_fg": kw.get("diff_fg", 5.2),
            "diff_fga": kw.get("diff_fga", 1.8),
            "diff_fg_pct": kw.get("diff_fg_pct", 0.05),
            "diff_fg3": kw.get("diff_fg3", 2.2),
            "diff_fg3a": kw.get("diff_fg3a", 2.8),
            "diff_fg3_pct": kw.get("diff_fg3_pct", 0.058),
            "diff_efg_pct": kw.get("diff_efg_pct", 0.061),
            "diff_ft": kw.get("diff_ft", -10.2),
            "diff_fta": kw.get("diff_fta", -9.3),
            "diff_ft_pct": kw.get("diff_ft_pct", -0.149),
            "diff_pts": kw.get("diff_pts", 2.4),
            "diff_orb": kw.get("diff_orb", 0.2),
            "diff_orb_pct": kw.get("diff_orb_pct", 0.2),
            "diff_drb": kw.get("diff_drb", -0.3),
            "diff_drb_pct": kw.get("diff_drb_pct", 0.2),
            "diff_trb": kw.get("diff_trb", 0.2),
            "diff_trb_pct": kw.get("diff_trb_pct", 0.4),
            "diff_ast": kw.get("diff_ast", 2.9),
            "diff_stl": kw.get("diff_stl", -0.1),
            "diff_blk": kw.get("diff_blk", -3.0),
            "diff_tov": kw.get("diff_tov", 0.7),
            "diff_pf": kw.get("diff_pf", 0.6),
        }

    recs = [
        _rec(["slug1", "slug2", "slug3", "slug4", "slug5"],
              ranker=1, minutes=100),
        _rec(["slug1", "slug6", "slug3", "slug4", "slug5"],
              ranker=2, minutes=50),
    ]
    rows = [crawler.build_rows(db_conn, "testslug", 2014, "Regular", r)
            for r in recs]

    n1 = crawler._upsert_rows(db_conn, "player_lineups_test", rows,
                              crawler.CONFLICT_COLS)
    db_conn.commit()
    cur.execute("SELECT COUNT(*) FROM player_lineups_test")
    assert cur.fetchone()[0] == 2, "应写入 2 行"

    # 幂等：再次 upsert 同样数据，行数不变
    n2 = crawler._upsert_rows(db_conn, "player_lineups_test", rows,
                              crawler.CONFLICT_COLS)
    db_conn.commit()
    cur.execute("SELECT COUNT(*) FROM player_lineups_test")
    assert cur.fetchone()[0] == 2, "重放后行数应仍为 2（幂等）"
    assert n1 == 2 and n2 == 2
    cur.execute("DROP TABLE IF EXISTS player_lineups_test")
    db_conn.commit()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
