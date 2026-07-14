"""NBACore v8 — cba_aux T03 联调 + JSON 导出 + 冒烟测试（QA 验收，严过关）.

覆盖验收 7 项（对应主理人验收清单）：
  1. 端点契约：6 端点返回结构符合设计 JSON Schema；{code,data,message} 信封一致；
     路径参数非法（不存在的 player）时优雅返回 4xx/错误信封而非 500。
  2. 引擎 snapshot()/_team_status() 边界（默认 SalaryCapRules 168M 基线）：
     210M→LUXURY_TAX、215M→FIRST_APRON、222M→SECOND_APRON、100M→HEALTHY；
     真实 30 队 load_league + snapshot 字段齐全。
  3. is_all_nba 透传：load_player(..., is_all_nba=True) 使 get_max_salary_pct() 回到
     30%/35% 档；False 默认 25%。
  4. §6 合规：routers/cba_aux.py 无 SQL 子串/无内联薪资算术；cba.js 无业务计算。
  5. JSON 导出端点：/cba/league/export 返回可解析 JSON（rules/teams 结构 + content-type）。
  6. 前端挂载冒烟（静态）：index.html 含 cba nav-item + page-cba 容器；app.js 含
     loadCbaPage + Cba.render；cba.js 定义 window.Cba.render。
  7. 回归：由运行层面执行 backend/services/trade_engine/tests/ 既有测试确认未破坏
     cba_aux / cba_aux_db（见报告“回归”小节）。

运行：env -u http_proxy ... .venv/Scripts/python.exe -m pytest \
        backend/services/trade_engine/tests/test_cba_aux_t03.py -v
"""
from __future__ import annotations

import inspect
import json
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from backend.services.trade_engine.cba_aux import (
    LeagueSimulator,
    Player,
    SalaryCapRules,
    Team,
)
from backend.services.trade_engine import cba_aux_db
from backend.services.trade_engine.tests.conftest import skip_if_no_db

ROOT = pathlib.Path(__file__).resolve().parents[4]  # 项目根 nba_desktop_omega
ROUTER_PATH = ROOT / "backend" / "api" / "routers" / "cba_aux.py"
CBA_JS_PATH = ROOT / "frontend" / "js" / "components" / "cba.js"
INDEX_HTML_PATH = ROOT / "frontend" / "index.html"
APP_JS_PATH = ROOT / "frontend" / "js" / "app.js"


# ──────────────────────────────────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────────────────────────────────
def _team_with_total(name: str, total: int) -> Team:
    """构造一支总薪资恰好为 total 的单人球队（仅用于引擎边界断言）。"""
    t = Team(name)
    t.add_player(Player("P1", total))
    return t


# ──────────────────────────────────────────────────────────────────────────
# 验收 2 · 引擎 snapshot() / _team_status() 边界（纯逻辑，默认 168M 基线）
# ──────────────────────────────────────────────────────────────────────────
def test_team_status_default_rules_baseline():
    """默认 SalaryCapRules(168M) 基线四档：
    100M→HEALTHY、210M→LUXURY_TAX、215M→FIRST_APRON、222M→SECOND_APRON。"""
    rules = SalaryCapRules(
        base_cap=168_000_000,
        luxury_tax_line=204_120_000,
        first_apron=210_120_000,
        second_apron=221_620_000,
        min_team_salary=151_200_000,
    )
    sim = LeagueSimulator()
    sim.rules = rules
    assert sim._team_status(100_000_000) == "HEALTHY"
    assert sim._team_status(210_000_000) == "LUXURY_TAX"
    assert sim._team_status(215_000_000) == "FIRST_APRON"
    assert sim._team_status(222_000_000) == "SECOND_APRON"


def test_team_status_strict_boundaries():
    """严格 '>' 边界语义：
    - 恰等于 luxury 线 -> HEALTHY（不算 >luxury）
    - 恰等于 first_apron -> LUXURY_TAX（>luxury 但非 >first）
    - 恰等于 second_apron -> FIRST_APRON（>first 但非 >second）
    - 越过各线 +1 -> 进入更高档。
    """
    rules = SalaryCapRules()
    sim = LeagueSimulator()
    sim.rules = rules
    lux, fa, sa = rules.luxury_tax_line, rules.first_apron, rules.second_apron
    assert sim._team_status(lux) == "HEALTHY"
    assert sim._team_status(lux + 1) == "LUXURY_TAX"
    assert sim._team_status(fa) == "LUXURY_TAX"
    assert sim._team_status(fa + 1) == "FIRST_APRON"
    assert sim._team_status(sa) == "FIRST_APRON"
    assert sim._team_status(sa + 1) == "SECOND_APRON"
    assert sim._team_status(0) == "HEALTHY"


def test_snapshot_structure_and_status():
    """snapshot() 返回 {teams:[{team,total_salary,status}]}，status 取值合法。"""
    rules = SalaryCapRules(
        base_cap=168_000_000,
        luxury_tax_line=204_120_000,
        first_apron=210_120_000,
        second_apron=221_620_000,
        min_team_salary=151_200_000,
    )
    sim = LeagueSimulator()
    sim.rules = rules
    sim.add_team(_team_with_total("HEALTHY_TEAM", 100_000_000))
    sim.add_team(_team_with_total("LUX_TEAM", 210_000_000))
    sim.add_team(_team_with_total("FA_TEAM", 215_000_000))
    sim.add_team(_team_with_total("SA_TEAM", 222_000_000))

    snap = sim.snapshot()
    assert set(snap.keys()) == {"teams"}
    assert len(snap["teams"]) == 4

    by = {t["team"]: t for t in snap["teams"]}
    for t in snap["teams"]:
        assert set(t.keys()) == {"team", "total_salary", "status"}
        assert isinstance(t["total_salary"], int)
        assert t["status"] in {
            "HEALTHY", "LUXURY_TAX", "FIRST_APRON", "SECOND_APRON"
        }
    assert by["HEALTHY_TEAM"]["status"] == "HEALTHY"
    assert by["LUX_TEAM"]["status"] == "LUXURY_TAX"
    assert by["FA_TEAM"]["status"] == "FIRST_APRON"
    assert by["SA_TEAM"]["status"] == "SECOND_APRON"


@skip_if_no_db
def test_snapshot_real_30_teams():
    """真实 30 队 load_league + snapshot：返回 30 队且字段齐全。"""
    sim = cba_aux_db.load_league("2025-26")
    snap = sim.snapshot()
    assert len(snap["teams"]) == 30
    for t in snap["teams"]:
        assert set(t.keys()) == {"team", "total_salary", "status"}
        assert isinstance(t["total_salary"], int)
        assert t["status"] in {
            "HEALTHY", "LUXURY_TAX", "FIRST_APRON", "SECOND_APRON"
        }


# ──────────────────────────────────────────────────────────────────────────
# 验收 3 · is_all_nba 透传
# ──────────────────────────────────────────────────────────────────────────
def test_max_pct_engine_all_nba_brackets():
    """引擎层：All-NBA 使 max_pct 回到 30%/35% 档；非 All-NBA 恒 25%。"""
    assert Player("A", 1, yos=5, is_all_nba=True).get_max_salary_pct() == 0.30   # yos<10
    assert Player("B", 1, yos=12, is_all_nba=True).get_max_salary_pct() == 0.35  # yos>=10
    assert Player("C", 1, yos=12, is_all_nba=False).get_max_salary_pct() == 0.25
    assert Player("D", 1, yos=0, is_all_nba=False).get_max_salary_pct() == 0.25


@skip_if_no_db
def test_is_all_nba_passthrough_true():
    """load_player(..., is_all_nba=True) 覆盖 Player.is_all_nba 且 max_pct 回到档位。"""
    p = cba_aux_db.load_player("GSW", "Stephen Curry", "2025-26", is_all_nba=True)
    assert p is not None
    assert p.is_all_nba is True
    # Curry yos=19(>=10) 且 All-NBA -> 0.35
    assert p.get_max_salary_pct() == 0.35


@skip_if_no_db
def test_is_all_nba_passthrough_false_default():
    """load_player 默认 is_all_nba=False -> 恒 0.25（非破坏）。"""
    p = cba_aux_db.load_player("GSW", "Stephen Curry", "2025-26")
    assert p is not None
    assert p.is_all_nba is False
    assert p.get_max_salary_pct() == 0.25


# ──────────────────────────────────────────────────────────────────────────
# 验收 1 + 5 · 端点契约 + 信封 + JSON 导出（FastAPI TestClient，真实 DB）
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    from backend.app import app
    with TestClient(app) as c:
        yield c


@skip_if_no_db
class TestCbaRouterContract:
    def test_rules_envelope(self, client):
        r = client.get("/cba/rules?season=2025-26")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0 and body["message"] == "ok"
        d = body["data"]
        for k in ("season", "base_cap", "luxury_tax_line",
                  "first_apron", "second_apron", "min_team_salary"):
            assert k in d

    def test_team_envelope(self, client):
        r = client.get("/cba/team/GSW?season=2025-26")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0 and body["message"] == "ok"
        d = body["data"]
        for k in ("team_abbr", "season", "team_total", "status",
                  "rules", "players", "approx"):
            assert k in d
        assert d["status"] in {
            "HEALTHY", "LUXURY_TAX", "FIRST_APRON", "SECOND_APRON"
        }
        assert isinstance(d["players"], list)

    def test_player_envelope(self, client):
        r = client.get("/cba/player/GSW/Stephen%20Curry?season=2025-26")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0 and body["message"] == "ok"
        d = body["data"]
        for k in ("team_abbr", "name", "salary", "yos", "is_all_nba",
                  "bird_factor", "cap_hold", "max_pct", "basis", "approx"):
            assert k in d

    def test_league_summary_envelope(self, client):
        r = client.get("/cba/league/summary?season=2025-26")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0 and body["message"] == "ok"
        d = body["data"]
        for k in ("season", "rules", "thresholds", "teams"):
            assert k in d
        assert len(d["teams"]) == 30
        for t in d["teams"]:
            assert set(t.keys()) == {"team", "total_salary", "status"}

    def test_league_simulate_envelope(self, client):
        r = client.post(
            "/cba/league/simulate",
            json={"season": "2025-26", "team_abbrs": ["GSW", "LAL"], "trade": None},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0 and body["message"] == "ok"
        d = body["data"]
        assert "teams" in d
        assert {t["team"] for t in d["teams"]} == {"GSW", "LAL"}

    def test_player_not_found_returns_404_not_500(self, client):
        """路径参数非法（不存在的 player）：优雅返回 404，而非 500。"""
        r = client.get("/cba/player/GSW/__NO_SUCH_PLAYER_XYZ__?season=2025-26")
        assert r.status_code == 404
        assert r.status_code != 500
        body = r.json()
        assert "detail" in body  # FastAPI HTTPException 结构

    def test_team_invalid_abbr_not_500(self, client):
        """不存在的球队缩写：不应 500（空队走正常信封）。"""
        r = client.get("/cba/team/ZZZ?season=2025-26")
        assert r.status_code != 500
        body = r.json()
        assert body["code"] == 0

    def test_export_envelope(self, client):
        """⑥ 导出端点：200 + 可解析 JSON（rules/teams 结构）+ content-type。"""
        r = client.get("/cba/league/export?season=2025-26")
        assert r.status_code == 200, f"导出端点返回 {r.status_code}: {r.text}"
        assert "application/json" in r.headers.get("content-type", "")
        body = r.json()
        assert body["code"] == 0 and body["message"] == "ok"
        d = body["data"]
        assert "rules" in d and "teams" in d
        assert isinstance(d["teams"], dict)
        # 可序列化往返（确认无不可 JSON 化的对象）
        json.loads(json.dumps(d))


# ──────────────────────────────────────────────────────────────────────────
# 验收 4 · §6 四层隔离合规（grep 验证 + 报告命中）
# ──────────────────────────────────────────────────────────────────────────
def test_section6_router_no_sql_or_inline_arith():
    """routers/cba_aux.py 不得含 SQL 子串，亦不得含内联薪资算术（如 salary*1.5）。"""
    text = ROUTER_PATH.read_text(encoding="utf-8")
    sql_kw = ["SELECT ", "INSERT ", "UPDATE ", "DELETE ",
              "WHERE ", "FROM ", "JOIN ", "CREATE TABLE"]
    hits = [kw for kw in sql_kw if kw in text]
    assert not hits, f"router 含 SQL 子串: {hits}"
    inline_arith = re.compile(r"(salary|total_salary)\s*[\*\/]\s*\d")
    m = inline_arith.search(text)
    assert m is None, f"router 含内联薪资算术: {m.group(0)!r}"


def test_section6_frontend_no_business_calc():
    """cba.js 仅展示格式化（fmtMoney）；不得出现薪资计算/状态判定。"""
    text = CBA_JS_PATH.read_text(encoding="utf-8")
    forbidden = [
        re.compile(r"total_salary\s*>\s*\d"),       # 前端自行判定状态
        re.compile(r"salary\s*[\*\/]\s*\d"),         # 内联薪资算术
        re.compile(r"(cap_hold|max_pct)\s*=\s*\d"),  # 前端计算 cap_hold/max_pct
    ]
    hits = [pat.search(text).group(0) for pat in forbidden if pat.search(text)]
    assert not hits, f"cba.js 疑似含业务计算: {hits}"
    # 必须出现 fmtMoney 展示格式化（§6 允许的展示层）
    assert "fmtMoney" in text


# ──────────────────────────────────────────────────────────────────────────
# 验收 6 · 前端挂载冒烟（静态校验）
# ──────────────────────────────────────────────────────────────────────────
def test_frontend_mount_static():
    """index.html 含 cba nav-item + page-cba 容器 + cba.js script；
    app.js 含 loadCbaPage + Cba.render；cba.js 定义 window.Cba.render。"""
    index = INDEX_HTML_PATH.read_text(encoding="utf-8")
    appjs = APP_JS_PATH.read_text(encoding="utf-8")
    cba = CBA_JS_PATH.read_text(encoding="utf-8")

    # index.html
    assert 'data-page="cba"' in index
    assert 'id="page-cba"' in index
    assert "js/components/cba.js" in index

    # app.js
    assert "loadCbaPage" in appjs
    assert "Cba.render" in appjs

    # cba.js
    assert "window.Cba" in cba
    assert "render" in cba
