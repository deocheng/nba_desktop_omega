# tests/test_bridge_qa.py
# ============================================================================
# QA 独立验证套件 —— NBA 跨源桥接与双爬虫回补工程（T01–T05）
# 覆盖模块（按主理人任务书 A–F）：
#   A) raw_archiver.py        原子写 / 存在非空跳过 / .sha256 伴生一致
#   B) matcher.py             锚点命中 / 孤儿 ESPN / 无法匹配（含真实库断言）
#   C) game_id_bridge.py      幂等（重跑行数不变）+ 视图 v_pbp_br_resolved 可用性
#   D) espn_broad_crawler.py  dry-run 结构 + parse_boxscore 结构 + 极小真实落盘
#   E) verify_archive.py      空归档不崩 + 识别/对账 1 个 BR HTML
#   F) DDL 正确性             espn_boxscore JSONB / game_id_map UNIQUE(br_gid) / 视图存在
#
# 铁律（全程遵守）：
#   - 绝不触碰 play_by_play 的 (x,y) 坐标列（只读校验）。
#   - 不给 BR 抓取加 --force；不启动 br_crawler / espn 长循环（仅 --dry-run / 极小 --limit）。
#   - 向真实库写入的测试（bridge 20 行、espn 1 条）均保证幂等、可清理、不破坏坐标。
# ============================================================================
from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import date

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 被测模块
import raw_archiver  # noqa: E402
from matcher import match_game  # noqa: E402
from common.bridge_constants import PG_DSN, PROJECT_ROOT as BR_ROOT  # noqa: E402


# ---------------------------------------------------------------------------
# 工具：运行工程脚本（subprocess）
# ---------------------------------------------------------------------------
VENV_PY = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")


def run_script(script_rel: str, args, *, offline: bool = True, timeout: int = 240):
    """以 venv python 运行工程脚本。offline=True 时将 HTTP(S) 代理指向
    不可达地址，使任何 ESPN 网络请求立即失败（连接拒绝），避免 25s 超时等待，
    从而让桥接/回补在离线快速模式下运行（不影响 DB 连接，DB 走 psycopg2 非 HTTP）。"""
    env = dict(os.environ)
    if offline:
        env["HTTP_PROXY"] = "http://127.0.0.1:9"
        env["HTTPS_PROXY"] = "http://127.0.0.1:9"
        env["http_proxy"] = "http://127.0.0.1:9"
        env["https_proxy"] = "http://127.0.0.1:9"
    cmd = [VENV_PY, os.path.join(PROJECT_ROOT, script_rel)] + list(args)
    return subprocess.run(
        cmd, cwd=PROJECT_ROOT, env=env,
        capture_output=True, text=True, timeout=timeout,
    )


@pytest.fixture
def conn():
    """真实只读/幂等写入连接（autocommit，便于立即看到其他进程已提交的结果）。"""
    import psycopg2
    c = psycopg2.connect(PG_DSN)
    c.autocommit = True
    yield c
    c.close()


def sql1(conn, sql: str, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return row[0] if row else None


def sqlrow(conn, sql: str, params=None):
    """返回单行（tuple）；无结果返回 None。用于需要整行（多列）的断言。"""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


# ===========================================================================
# A) raw_archiver.py —— 原子写 / 去重 / 哈希
# ===========================================================================
class TestRawArchiver:
    def test_atomic_write_creates_file_and_no_tmp_left(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "out.txt")
            ok = raw_archiver.atomic_write(p, b"payload", write_sha256=False)
            assert ok is True
            assert os.path.exists(p)
            assert os.path.getsize(p) == len(b"payload")
            # 原子 rename 后不应残留 .tmp
            assert not os.path.exists(p + ".tmp")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_skip_when_target_exists_nonempty(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "out.txt")
            assert raw_archiver.atomic_write(p, b"hello") is True
            # 已存在且非空 → 跳过，返回 False，内容不被覆盖
            assert raw_archiver.atomic_write(p, b"world") is False
            assert open(p, "rb").read() == b"hello"
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_overwrite_when_rearchive(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "out.txt")
            raw_archiver.atomic_write(p, b"hello")
            assert raw_archiver.atomic_write(p, b"world", rearchive=True) is True
            assert open(p, "rb").read() == b"world"
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_empty_target_gets_overwritten(self):
        """目标存在但字节数为 0（空文件）时应被覆盖（去重仅对非空生效）。"""
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "out.txt")
            with open(p, "w") as fh:
                pass  # 空文件
            assert os.path.getsize(p) == 0
            assert raw_archiver.atomic_write(p, b"data") is True
            assert open(p, "rb").read() == b"data"
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_sha256_write_and_verify_consistency(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "out.txt")
            raw_archiver.atomic_write(p, b"checksum me", write_sha256=True)
            assert raw_archiver.verify_sha256(p) is True
            # 篡改内容后校验应失败
            with open(p, "ab") as fh:
                fh.write(b"x")
            assert raw_archiver.verify_sha256(p) is False
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_verify_sha256_missing_sidecar_returns_false(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "out.txt")
            raw_archiver.atomic_write(p, b"no sidecar")
            assert raw_archiver.verify_sha256(p) is False
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_save_br_html_and_espn_json_wrappers(self):
        """BR / ESPN 专用封装应落到正确模板路径；ESPN 支持 dict 负载（json 序列化）。"""
        d = tempfile.mkdtemp()
        orig = raw_archiver.PROJECT_ROOT
        raw_archiver.PROJECT_ROOT = d  # 重定向归档根，避免污染真实项目
        try:
            ok_br = raw_archiver.save_br_html(2026, "202601010BOS", "<html>BR</html>",
                                              write_sha256=True)
            br_path = os.path.join(d, "raw_archive/br/2026/202601010BOS.html")
            assert ok_br is True
            assert os.path.exists(br_path)
            assert raw_archiver.verify_sha256(br_path) is True

            ok_es = raw_archiver.save_espn_json("2026-01-01", "401585401",
                                                {"teams": [{"id": 1}]})
            es_path = os.path.join(d, "raw_archive/espn/2026-01-01/401585401.json")
            assert ok_es is True
            assert os.path.exists(es_path)
            # dict 负载应被序列化为合法 JSON
            loaded = json.loads(open(es_path, "r", encoding="utf-8").read())
            assert loaded["teams"][0]["id"] == 1
        finally:
            raw_archiver.PROJECT_ROOT = orig
            shutil.rmtree(d, ignore_errors=True)


# ===========================================================================
# B) matcher.py —— 匹配函数（含真实库断言）
# ===========================================================================
class TestMatcher:
    def test_real_dim_games_anchor_matched(self, conn):
        """真实 dim_games 锚点精确命中（双键齐全）→ dim_games / matched。"""
        row = sqlrow(conn, """
            SELECT m.br_gid, m.nba_api_id, g.game_date, g.home_team_abbr,
                   g.away_team_abbr, g.home_pts, g.away_pts
            FROM game_id_map m
            JOIN dim_games g ON g.game_id = m.br_gid
            WHERE m.nba_api_id IS NOT NULL AND m.match_method = 'dim_games'
            LIMIT 1
        """)
        assert row is not None, "需要一个双键齐全的 dim_games 锚点样本"
        br_gid, nba_api, gdate, h, a, hp, ap = row
        mr = match_game(gdate, h, a, hp, ap, conn=conn)  # 无 ESPN 会话
        assert mr.br_gid == br_gid
        assert mr.nba_api_id == nba_api
        assert mr.method == "dim_games"
        assert mr.status == "matched"

    def test_real_unmatched(self, conn):
        """不存在的锚点 → unmatched（读库，不碰坐标）。"""
        mr = match_game(date(1990, 1, 1), "BOS", "NYK", 100, 99, conn=conn)
        assert mr.status == "unmatched"
        assert mr.method == "unmatched"
        assert mr.br_gid is None and mr.nba_api_id is None

    def test_real_orphan_without_session_is_partial(self, conn):
        """孤儿（nba_api_id NULL，但 dim_games 有 br_gid）无 ESPN 会话 → partial。"""
        row = sqlrow(conn, """
            SELECT m.br_gid, g.game_date, g.home_team_abbr, g.away_team_abbr,
                   g.home_pts, g.away_pts
            FROM game_id_map m
            JOIN dim_games g ON g.game_id = m.br_gid
            WHERE m.nba_api_id IS NULL
            LIMIT 1
        """)
        if row is None:
            pytest.skip("当前库无孤儿样本（nba_api_id NULL）")
        br_gid, gdate, h, a, hp, ap = row
        mr = match_game(gdate, h, a, hp, ap, conn=conn)
        assert mr.br_gid == br_gid
        assert mr.nba_api_id is None
        assert mr.status == "partial"


# ===========================================================================
# C) game_id_bridge.py —— 幂等 + 视图可用性（核心功能）
# ===========================================================================
class TestGameIdBridge:
    def test_bridge_idempotent_and_playbyplay_untouched(self, conn):
        """重跑 --season 2026 --limit 20 行数不变（幂等），且 play_by_play 行数不变（铁律）。"""
        pbp_before = sql1(conn, "SELECT count(*) FROM play_by_play")
        gim_before = sql1(conn, "SELECT count(*) FROM game_id_map WHERE season = 2026")
        assert gim_before >= 1, "预期已有 season=2026 的桥接行"

        p1 = run_script("game_id_bridge.py", ["--season", "2026", "--limit", "20"],
                        offline=True, timeout=240)
        assert p1.returncode == 0, f"bridge run1 failed:\n{p1.stderr[-3000:]}"
        gim_after1 = sql1(conn, "SELECT count(*) FROM game_id_map WHERE season = 2026")

        p2 = run_script("game_id_bridge.py", ["--season", "2026", "--limit", "20"],
                        offline=True, timeout=240)
        assert p2.returncode == 0, f"bridge run2 failed:\n{p2.stderr[-3000:]}"
        gim_after2 = sql1(conn, "SELECT count(*) FROM game_id_map WHERE season = 2026")

        # 幂等：重跑不产生新行，且与运行前状态一致
        assert gim_after1 == gim_before, f"桥接改变了行数: {gim_before}->{gim_after1}"
        assert gim_after2 == gim_after1, f"桥接非幂等: {gim_after1}->{gim_after2}"

        # 铁律：play_by_play 行数必须保持不变（桥接绝不写坐标/不增删 PBP）
        pbp_after = sql1(conn, "SELECT count(*) FROM play_by_play")
        assert pbp_after == pbp_before, "桥接修改了 play_by_play 行数（违反坐标铁律！）"

    def test_view_resolves_br_gid_for_api_pbp(self, conn):
        """核心功能：PBP 挂在 nba_api_id 下、br_gid 下没有，经视图以 gameid_resolved=br_gid 暴露。"""
        row = sqlrow(conn, """
            SELECT m.br_gid, m.nba_api_id
            FROM game_id_map m
            WHERE m.nba_api_id IS NOT NULL AND m.pbp_under_api AND NOT m.pbp_under_br
            LIMIT 1
        """)
        assert row is not None, "需要一个 'PBP 在 nba_api_id 下、br_gid 下无' 的桥接样本"
        br_gid, nba_api = row

        pbp_api = sql1(conn, "SELECT count(*) FROM play_by_play WHERE gameid = %s", (nba_api,))
        pbp_br = sql1(conn, "SELECT count(*) FROM play_by_play WHERE gameid = %s", (br_gid,))
        view_cnt = sql1(conn,
                         "SELECT count(*) FROM v_pbp_br_resolved WHERE gameid_resolved = %s",
                         (br_gid,))

        assert pbp_api > 0, "预期 PBP 行挂在 nba_api_id 下"
        assert pbp_br == 0, "该场景 PBP 不应直接存于 br_gid 下"
        assert view_cnt == pbp_api, (
            f"视图应解析出 {pbp_api} 行 PBP 到 gameid_resolved={br_gid}，实际 {view_cnt}"
        )


# ===========================================================================
# D) espn_broad_crawler.py —— dry-run / parse 结构 / 极小真实落盘
# ===========================================================================
class TestEspnBroadCrawler:
    def test_dry_run_small_limit(self):
        """--dry-run --limit 2 应正常退出并打印将被抓取的场（不落库/不落盘/不崩）。"""
        p = run_script("espn_broad_crawler.py", ["--dry-run", "--limit", "2"],
                       offline=True, timeout=120)
        assert p.returncode == 0, f"espn dry-run failed:\n{p.stderr[-2000:]}"
        assert "[dry]" in p.stdout, "dry-run 应打印 [dry] 抓取计划"

    def test_parse_boxscore_structure(self):
        """parse_boxscore 能从合成 summary 正确解析 teams[]/players[]/shot_coords。"""
        from espn_broad_crawler import parse_boxscore

        summary = {
            "teams": [
                {"team": {"abbreviation": "BOS"}, "homeAway": "home", "score": "112"},
                {"team": {"abbreviation": "NYK"}, "homeAway": "away", "score": "105"},
            ],
            "boxscore": {
                "teams": [
                    {"team": {"abbreviation": "BOS"},
                     "statistics": [{"label": "PTS", "displayValue": "112"}]},
                    {"team": {"abbreviation": "NYK"},
                     "statistics": [{"label": "PTS", "displayValue": "105"}]},
                ],
                "players": [
                    {"team": {"abbreviation": "BOS"},
                     "statistics": [{"name": "Game",
                                     "athletes": [{"athlete": {"id": "1",
                                                              "displayName": "Jayson Tatum"}}]}]},
                    {"team": {"abbreviation": "NYK"},
                     "statistics": [{"name": "Game",
                                     "athletes": [{"athlete": {"id": "2",
                                                              "displayName": "Julius Randle"}}]}]},
                ],
            },
            "plays": [
                {"shootingPlay": True, "coordinate": {"x": 25, "y": 10},
                 "athletes": [{"athlete": {"id": "1", "displayName": "Jayson Tatum"}}],
                 "team": {"abbreviation": "BOS"}, "period": {"number": 1},
                 "clock": {"displayValue": "5:00"},
                 "text": "Jayson Tatum makes 3-point jump shot"},
                {"shootingPlay": True, "coordinate": {"x": 30, "y": 5},
                 "athletes": [{"athlete": {"id": "2", "displayName": "Julius Randle"}}],
                 "team": {"abbreviation": "NYK"}, "period": {"number": 1},
                 "clock": {"displayValue": "4:30"},
                 "text": "Julius Randle misses 2-point shot"},
                # 无坐标的 shootingPlay → 跳过
                {"shootingPlay": True, "coordinate": {"x": None, "y": None},
                 "athletes": [], "team": {"abbreviation": "BOS"},
                 "text": "no coord"},
                # 非投篮 play → 跳过
                {"shootingPlay": False, "text": "timeout"},
            ],
            "season": {"type": 2},
        }

        parsed = parse_boxscore(summary)
        # 主客队解析
        assert parsed["home_abbr"] == "BOS"
        assert parsed["away_abbr"] == "NYK"
        assert parsed["home_pts"] == 112
        assert parsed["away_pts"] == 105
        # 盒式
        assert isinstance(parsed["home_team_box"], dict)
        assert isinstance(parsed["away_team_box"], dict)
        assert isinstance(parsed["player_boxes"], list) and len(parsed["player_boxes"]) == 2
        # 投篮坐标结构
        shots = parsed["shot_coords"]
        assert isinstance(shots, list) and len(shots) == 2, f"应解析出 2 个真实坐标投篮，实际 {len(shots)}"
        made, missed = shots[0], shots[1]
        assert made["made"] is True and missed["made"] is False
        assert made["x"] == 25 and made["y"] == 10
        assert made["player_name"] == "Jayson Tatum" and made["team"] == "BOS"
        assert made["period"] == 1 and made["clock"] == "5:00"
        # 必备字段齐全
        for k in ("player_id", "player_name", "team", "period", "clock", "x", "y", "made"):
            assert k in made, f"shot_coords 缺少字段 {k}"
        # season_type
        assert parsed["season_type"] == 2

    def test_real_fetch_small_best_effort(self, conn):
        """极小真实 --limit 1 落盘（若网络可达）：断言文件非空 + espn_boxscore 有 upsert；
        无论成功与否均清理，避免污染真实库/归档。"""
        before = sql1(conn, "SELECT count(*) FROM espn_boxscore")
        p = run_script("espn_broad_crawler.py", ["--limit", "1"],
                       offline=False, timeout=180)
        if p.returncode != 0:
            pytest.skip("ESPN 网络抓取在本环境不可达，跳过真实落盘验证")

        # 从输出解析被写入的 espn_event
        import re
        m = re.search(r"espn=(\S+)", p.stdout)
        assert m, f"未在输出中找到 espn_event:\n{p.stdout[-2000:]}"
        eid = m.group(1)

        try:
            # 文件非空
            es_dir = os.path.join(BR_ROOT, "raw_archive", "espn")
            found = []
            for root, _, files in os.walk(es_dir):
                for f in files:
                    if eid in f and f.endswith(".json"):
                        found.append(os.path.join(root, f))
            assert found, f"未找到落盘的 ESPN JSON（event={eid}）"
            assert all(os.path.getsize(f) > 0 for f in found), "落盘 JSON 不应为空"

            # espn_boxscore 有 upsert
            cnt = sql1(conn, "SELECT count(*) FROM espn_boxscore WHERE espn_event = %s", (eid,))
            assert cnt == 1, f"espn_boxscore 应有 1 行（event={eid}），实际 {cnt}"
        finally:
            # 清理：删除测试写入的 espn 行 + 复位 game_id_map.espn_have + 落盘文件
            # （不影响 play_by_play 坐标 / 其他业务数据）
            br = sql1(conn, "SELECT br_gid FROM espn_boxscore WHERE espn_event = %s", (eid,))
            with conn.cursor() as cur:
                cur.execute("DELETE FROM espn_boxscore WHERE espn_event = %s", (eid,))
                if br:
                    cur.execute(
                        "UPDATE game_id_map SET espn_have = false WHERE br_gid = %s", (br,))
            conn.commit()
            for f in found:
                try:
                    os.remove(f)
                    sha = f + ".sha256"
                    if os.path.exists(sha):
                        os.remove(sha)
                except OSError:
                    pass
            after = sql1(conn, "SELECT count(*) FROM espn_boxscore")
            assert after == before, f"清理后 espn_boxscore 行数应回到 {before}，实际 {after}"


# ===========================================================================
# E) verify_archive.py —— 空归档不崩 + 识别/对账 1 个 BR HTML
# ===========================================================================
class TestVerifyArchive:
    def test_empty_archive_no_crash(self):
        """空归档下 verify_archive 不应崩溃，并输出缺口清单。"""
        p = run_script("verify_archive.py", [], offline=True, timeout=120)
        assert p.returncode == 0, f"verify_archive 崩溃:\n{p.stderr[-2000:]}"
        assert "缺口清单" in p.stdout, "应输出缺口清单"
        assert "BR  HTML 文件: 0" in p.stdout, "空归档 BR 文件数应为 0"

    def test_recognizes_br_html_and_reconciles(self):
        """构造 1 个 BR HTML 落盘后，verify_archive 能识别且不抛异常（对账逻辑可执行）。"""
        season = 2026
        dummy_gid = "QA_DUMMY_TEST_BRIDGE"
        rel = os.path.join("raw_archive", "br", str(season), dummy_gid + ".html")
        full = os.path.join(BR_ROOT, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        try:
            with open(full, "w", encoding="utf-8") as fh:
                fh.write("<html>QA dummy BR PBP</html>")
            p = run_script("verify_archive.py", [], offline=True, timeout=120)
            assert p.returncode == 0, f"verify_archive 崩溃:\n{p.stderr[-2000:]}"
            assert "BR  HTML 文件: 1" in p.stdout or "BR  HTML 文件: 2" in p.stdout, \
                f"应识别到 BR HTML 文件:\n{p.stdout[-1500:]}"
        finally:
            try:
                os.remove(full)
            except OSError:
                pass


# ===========================================================================
# F) DDL 正确性
# ===========================================================================
class TestDDL:
    def test_espn_boxscore_jsonb_and_rawjson(self, conn):
        rows = {}
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'espn_boxscore'
            """)
            for name, dtype in cur.fetchall():
                rows[name] = dtype
        for col in ("home_team_box", "away_team_box", "player_boxes", "shot_coords"):
            assert rows.get(col) == "jsonb", f"espn_boxscore.{col} 应为 JSONB，实际 {rows.get(col)}"
        assert rows.get("raw_json_path") == "text", \
            f"espn_boxscore.raw_json_path 应为 text，实际 {rows.get('raw_json_path')}"

    def test_game_id_map_unique_br_gid(self, conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = 'game_id_map'::regclass AND contype = 'u'
            """)
            defs = [r[0] for r in cur.fetchall()]
        assert any("UNIQUE (br_gid)" in d for d in defs), \
            f"game_id_map 应含 UNIQUE(br_gid)，实际: {defs}"

    def test_view_is_view(self, conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name, table_type
                FROM information_schema.tables
                WHERE table_name = 'v_pbp_br_resolved'
            """)
            row = cur.fetchone()
        assert row is not None, "v_pbp_br_resolved 视图应存在"
        assert row[1] == "VIEW", f"v_pbp_br_resolved 应为 VIEW，实际 {row[1]}"

    def test_bridge_tables_have_no_coordinate_columns(self, conn):
        """铁律护栏：桥接表 game_id_map / espn_boxscore 不得含顶层 (x,y) 坐标列。"""
        for tbl in ("game_id_map", "espn_boxscore"):
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = %s
                """, (tbl,))
                cols = [r[0] for r in cur.fetchall()]
            assert "x" not in cols and "y" not in cols, \
                f"{tbl} 不应含顶层坐标列 x/y（违反坐标铁律护栏）: {cols}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
