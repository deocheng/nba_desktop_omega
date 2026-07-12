"""NBACore v8 — /cba router (Layer 3, pure orchestration).

cba_aux 可视化薄编排路由（T01）。本路由**不含任何 SQL 子串 / 薪资计算**
（v8 §6 Layer 3 强制）：仅做请求校验、调用 ``cba_aux``（计算引擎）与
``cba_aux_db``（只读适配层），塑形 ``{code, data, message}`` 信封。

接口清单（对应 cba_aux_design.md §3.2）：
    GET  /cba/rules                薪资规则常量
    GET  /cba/team/{abbr}          该队逐人 Bird&Max + 团队总额 + 状态
    GET  /cba/player/{abbr}/{name} 单人 cap_hold + max_pct + 判定依据
    GET  /cba/league/summary       逐队 {total_salary, status} 结构化快照
    POST /cba/league/simulate       多队选择 + 可选交易 -> 模拟后状态
    GET  /cba/league/export         当前 league JSON（零后端写，前端 blob 下载）

计算下沉说明：
    - 状态判定 / cap_hold / max_pct / total_salary 全部在 cba_aux 引擎层。
    - 本文件仅调用引擎方法（``team.get_cap_hold`` /
      ``player.get_max_salary_pct`` / ``team.total_salary`` /
      ``LeagueSimulator.snapshot`` / ``TradeSimulator.execute_trade``），
      不出现任何内联薪资算术。
    - ``bird_factor`` 仅为展示用分类常量（1.5/1.25/1.2，按 yos 档位），
      非薪资计算。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.services.trade_engine import cba_aux, cba_aux_db

router = APIRouter(prefix="/cba", tags=["cba"])

# 状态枚举 -> 中文标签（仅展示用；状态判定一律来自引擎）
_STATUS_CN = {
    "HEALTHY": "健康",
    "LUXURY_TAX": "奢侈税",
    "FIRST_APRON": "第一围裙",
    "SECOND_APRON": "第二围裙",
}


# ====================== 请求体模型（仅 POST /simulate 用） ======================
class _SimulateTrade(BaseModel):
    team_a: Optional[str] = None
    team_b: Optional[str] = None
    players_a_to_b: List[str] = []
    players_b_to_a: List[str] = []


class SimulateRequest(BaseModel):
    season: str = cba_aux_db.DEFAULT_SEASON
    team_abbrs: List[str] = []
    trade: Optional[_SimulateTrade] = None


# ====================== 信封 & 塑形辅助 ======================
def _envelope(data, message: str = "ok") -> Dict:
    return {"code": 0, "data": data, "message": message}


def _rules_dict(rules: "cba_aux.SalaryCapRules") -> Dict[str, int]:
    """SalaryCapRules -> 响应用规则 dict（金额 int，零计算）。"""
    return {
        "base_cap": rules.base_cap,
        "luxury_tax_line": rules.luxury_tax_line,
        "first_apron": rules.first_apron,
        "second_apron": rules.second_apron,
        "min_team_salary": rules.min_team_salary,
    }


def _thresholds_dict(rules: "cba_aux.SalaryCapRules") -> Dict[str, int]:
    """SalaryCapRules -> 阈值 dict（供前端 ECharts markLine 使用）。"""
    return {
        "base_cap": rules.base_cap,
        "luxury_tax_line": rules.luxury_tax_line,
        "first_apron": rules.first_apron,
        "second_apron": rules.second_apron,
    }


def _bird_factor(player: "cba_aux.Player") -> float:
    """展示用 Bird Rights 倍乘分类（1.5/1.25/1.2），按 yos 档位。

    仅分类常量映射，不涉及薪资算术；实际 cap_hold 金额由引擎 get_cap_hold 计算。
    """
    if player.yos >= 3:
        return 1.5
    if player.yos >= 2:
        return 1.25
    return 1.2


def _player_view(team: "cba_aux.Team", player: "cba_aux.Player") -> Dict:
    """构造单人展示视图（调用引擎方法，本函数不计算薪资）。"""
    return {
        "name": player.name,
        "salary": player.salary,
        "yos": player.yos,
        "bird_factor": _bird_factor(player),
        "cap_hold": team.get_cap_hold(player),
        "max_pct": player.get_max_salary_pct(),
        "basis": {"yos": player.yos, "is_all_nba": player.is_all_nba},
    }


# ====================== 端点 ======================
@router.get("/rules")
def get_rules(season: str = Query(cba_aux_db.DEFAULT_SEASON)):
    """① 薪资规则常量（来自 load_salary_rules，DB 权威）。"""
    try:
        rules = cba_aux_db.load_salary_rules(season)
        data = {"season": season, **_rules_dict(rules)}
        return _envelope(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"load salary rules failed: {exc}")


@router.get("/team/{team_abbr}")
def get_team(
    team_abbr: str,
    season: str = Query(cba_aux_db.DEFAULT_SEASON),
    is_all_nba: bool = Query(False),
):
    """② 该队逐人 Bird&Max + 团队总额 + 状态。

    状态判定复用引擎：构造单队 LeagueSimulator（rules=DB 规则）并调 snapshot()，
    保证与联盟汇总的判定逻辑同源，router 自身零薪资计算。
    """
    try:
        team = cba_aux_db.load_team(team_abbr, season, is_all_nba=is_all_nba)
        rules = cba_aux_db.load_salary_rules(season)

        # 用引擎 snapshot 判定该队状态（沿用 LeagueSimulator._team_status）
        sim = cba_aux.LeagueSimulator()
        sim.rules = rules
        sim.add_team(team)
        snap = sim.snapshot()
        status = snap["teams"][0]["status"] if snap["teams"] else "HEALTHY"

        players = [_player_view(team, p) for p in team.roster.values()]
        data = {
            "team_abbr": team_abbr,
            "season": season,
            "team_total": team.total_salary(),
            "status": status,
            "rules": _rules_dict(rules),
            "players": players,
            "approx": {"yos_heuristic": True, "is_all_nba_unverified": True},
        }
        return _envelope(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"load team failed: {exc}")


@router.get("/player/{team_abbr}/{player_name}")
def get_player(
    team_abbr: str,
    player_name: str,
    season: str = Query(cba_aux_db.DEFAULT_SEASON),
    is_all_nba: bool = Query(False),
):
    """③ 单人 cap_hold + max_pct + 判定依据。

    cap_hold 需 Team 上下文（引擎 get_cap_hold 仅用 player.yos/salary），
    故构造临时单球员 Team 调用引擎方法。
    """
    try:
        player = cba_aux_db.load_player(
            team_abbr, player_name, season, is_all_nba=is_all_nba
        )
        if player is None:
            raise HTTPException(
                status_code=404,
                detail=f"player {player_name} not found in team {team_abbr}",
            )
        tmp = cba_aux.Team(team_abbr)
        tmp.add_player(player)
        view = _player_view(tmp, player)
        data = {
            "team_abbr": team_abbr,
            "name": player.name,
            "salary": player.salary,
            "yos": player.yos,
            "is_all_nba": player.is_all_nba,
            "bird_factor": view["bird_factor"],
            "cap_hold": view["cap_hold"],
            "max_pct": view["max_pct"],
            "basis": view["basis"],
            "approx": {"yos_heuristic": True, "is_all_nba_unverified": True},
        }
        return _envelope(data)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"load player failed: {exc}")


@router.get("/league/summary")
def get_league_summary(season: str = Query(cba_aux_db.DEFAULT_SEASON)):
    """④ 逐队 {total_salary, status} 结构化快照（来自 load_league + snapshot）。"""
    try:
        sim = cba_aux_db.load_league(season)
        snap = sim.snapshot()
        data = {
            "season": season,
            "rules": _rules_dict(sim.rules),
            "thresholds": _thresholds_dict(sim.rules),
            "teams": snap["teams"],
        }
        return _envelope(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"league summary failed: {exc}")


@router.post("/league/simulate")
def post_simulate(req: SimulateRequest):
    """⑤ 多队选择 + 可选交易 -> 模拟后状态（P1）。

    可选 trade: {team_a, team_b, players_a_to_b, players_b_to_a}，
    命中则先调引擎 TradeSimulator.execute_trade 改动 sim，再 snapshot()。
    """
    try:
        sim = cba_aux_db.load_league(req.season)

        if req.trade:
            team_a = sim.teams.get(req.trade.team_a) if req.trade.team_a else None
            team_b = sim.teams.get(req.trade.team_b) if req.trade.team_b else None
            if team_a and team_b:
                cba_aux.TradeSimulator.execute_trade(
                    team_a,
                    team_b,
                    players_a_to_b=req.trade.players_a_to_b,
                    players_b_to_a=req.trade.players_b_to_a,
                    rules=sim.rules,
                )

        snap = sim.snapshot()
        teams = snap["teams"]
        if req.team_abbrs:
            selected = set(req.team_abbrs)
            teams = [t for t in teams if t["team"] in selected]

        data = {
            "season": req.season,
            "rules": _rules_dict(sim.rules),
            "thresholds": _thresholds_dict(sim.rules),
            "teams": teams,
        }
        return _envelope(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"league simulate failed: {exc}")


@router.get("/league/export")
def get_league_export(season: str = Query(cba_aux_db.DEFAULT_SEASON)):
    """⑥ 当前 league JSON（来自 LeagueSimulator.to_dict，零后端写）。

    前端据此生成 blob 下载（P2，v8 §6 零写层）。
    """
    try:
        sim = cba_aux_db.load_league(season)
        league_dict = sim.to_dict()
        data = {
            "rules": league_dict.get("rules", {}),
            "teams": league_dict.get("teams", {}),
        }
        return _envelope(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"league export failed: {exc}")
