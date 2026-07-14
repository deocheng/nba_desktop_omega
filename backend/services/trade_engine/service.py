"""NBACore v8 — Trade Service Facade (T04 / T05 / T06 / T07 / T08 / T11).

门面（Facade）汇总所有引擎能力，供 API 层（Layer 3）薄编排调用：
    validate / suggest / generate / player_timeline / team_timeline / get_rules / upsert_rules

本类仅做「数据加载 + 编排 + 结果序列化」，不含规则数学（规则在 nba_rules /
match_engine）。所有结果均为 JSON 可序列化 dict（Pydantic model_dump）。
严格四层隔离：API 层只调用本门面，不触碰底层引擎细节。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from backend.services.trade_engine import (
    db,
    match_engine,
    rules,
    schemas,
    suggester,
    tax_engine,
    timeline,
    trade_graph,
)
from backend.services.trade_engine.rules import get_rule_set


class TradeService:
    """交易模拟器引擎门面。"""

    def __init__(self) -> None:
        self._tax = tax_engine.TaxEngine()
        self._suggester = suggester.MatchSuggester()
        self._generator = suggester.ProposalGenerator()
        self._timeline = timeline.TimelineService()

    # ── 内部辅助 ──
    def _load_rules(
        self, season: str, league: str = "NBA"
    ) -> schemas.LeagueSalaryRules:
        r = db.load_rules(season, league)
        if r is None:
            raise LookupError(f"no league_salary_rules for {league}/{season}")
        return r

    def _resolve_legs(
        self,
        req_legs: List[schemas.LegRequest],
        season: str,
        assets: Dict[str, schemas.PlayerAsset],
        payrolls: Dict[str, dict],
    ) -> List[schemas.TeamTradeLeg]:
        """将 API 入参 LegRequest（player_id 列表）解析为带 PlayerAsset 的 TeamTradeLeg。"""
        legs: List[schemas.TeamTradeLeg] = []
        for lr in req_legs:
            outgoing = [assets[pid] for pid in lr.outgoing if pid in assets]
            incoming = [assets[pid] for pid in lr.incoming if pid in assets]
            pre = (
                payrolls.get(lr.team_abbr, {})
                .get("totals", {})
                .get(season, 0)
            )
            legs.append(
                schemas.TeamTradeLeg(
                    team_abbr=lr.team_abbr,
                    season=season,
                    outgoing=outgoing,
                    incoming=incoming,
                    cash_sent=lr.cash_sent,
                    tpe_used=lr.tpe_used,
                    sign_and_trade=lr.sign_and_trade,
                    pre_trade_salary=pre,
                )
            )
        return legs

    # ── T04：合法性校验（TRADE-01） ──
    def validate(self, req: schemas.TradeValidateRequest) -> dict:
        r = self._load_rules(req.season, req.league)
        rs = get_rule_set(req.league)
        all_ids = [pid for lr in req.legs for pid in (lr.outgoing + lr.incoming)]
        assets = db.load_players_by_ids(all_ids, req.season)
        team_abbrs = [lr.team_abbr for lr in req.legs]
        payrolls = db.load_team_payrolls(team_abbrs, req.season)

        legs = self._resolve_legs(req.legs, req.season, assets, payrolls)
        proposal = schemas.TradeProposal(
            league=req.league, season=req.season, as_of=req.as_of, legs=legs
        )
        graph = trade_graph.TradeGraph.from_proposal(proposal)
        results = graph.validate_all(rs, r, req.as_of)
        cap_impact = self._tax.compute_all(graph, r)
        legal = graph.is_legal(results)

        return {
            "legal": legal,
            "is_balanced": proposal.is_balanced(),
            "results": [m.model_dump() for m in results],
            "cap_impact": [c.model_dump() for c in cap_impact],
            "message": "ok" if legal else "illegal",
        }

    # ── T05：薪资匹配建议（TRADE-02） ──
    def suggest(self, req: schemas.TradeSuggestRequest) -> dict:
        r = self._load_rules(req.season, req.league)
        rs = get_rule_set(req.league)
        all_ids = [pid for lr in req.legs for pid in (lr.outgoing + lr.incoming)]
        assets = db.load_players_by_ids(all_ids, req.season)
        team_abbrs = [lr.team_abbr for lr in req.legs]
        payrolls = db.load_team_payrolls(team_abbrs, req.season)
        rosters = db.load_team_players(team_abbrs, req.season)

        legs = self._resolve_legs(req.legs, req.season, assets, payrolls)
        suggestions: List[dict] = []
        for leg in legs:
            pool = rosters.get(leg.team_abbr, [])
            sugs = self._suggester.suggest(leg, rs, pool, r, req.as_of)
            suggestions.append(
                {
                    "team_abbr": leg.team_abbr,
                    "suggestions": [s.model_dump() for s in sugs],
                }
            )
        return {"suggestions": suggestions, "message": "ok"}

    # ── T07：方案生成（TRADE-07） ──
    def generate(self, req: schemas.TradeGenerateRequest) -> dict:
        r = self._load_rules(req.season, req.league)
        rs = get_rule_set(req.league)
        as_of = datetime.now()
        proposals = self._generator.generate(
            req.target_player_id, req.initiator_team, rs, r, req.season, as_of
        )
        out: List[dict] = []
        for p in proposals:
            out.append(
                {
                    "legs": [
                        {
                            "team_abbr": l.team_abbr,
                            "outgoing": [a.player_id for a in l.outgoing],
                            "incoming": [a.player_id for a in l.incoming],
                        }
                        for l in p.legs
                    ],
                    "legal": True,
                }
            )
        return {"proposals": out, "count": len(out), "message": "ok"}

    # ── T08：时间线（TRADE-08 / TRADE-09） ──
    def player_timeline(self, player_id: str, season: str) -> Optional[dict]:
        tl = self._timeline.player_timeline(player_id, season)
        return tl.model_dump() if tl else None

    def team_timeline(self, team_abbr: str, season: str) -> Optional[dict]:
        tl = self._timeline.team_timeline(team_abbr, season)
        return tl.model_dump() if tl else None

    # ── T11 / TRADE-05：规则常量读写 ──
    def get_rules(self, season: str, league: str = "NBA") -> Optional[dict]:
        r = db.load_rules(season, league)
        return r.model_dump() if r else None

    def upsert_rules(self, req: schemas.RulesUpsertRequest) -> dict:
        r = db.upsert_league_rules(
            schemas.LeagueSalaryRules(**req.model_dump())
        )
        return r.model_dump()

    def list_players(self, team_abbr: str, season: str) -> List[dict]:
        """列出某队球员（轻量视图，供前端构建器下拉，纯读）。"""
        rosters = db.load_team_players([team_abbr], season)
        players = rosters.get(team_abbr, [])
        return [
            {
                "player_id": p.player_id,
                "player_name": p.player_name,
                "salary": p.salary,
                "guaranteed": p.guaranteed,
                "opt_type": p.opt_type,
                "is_two_way": p.is_two_way,
                "is_partial": p.is_partial,
            }
            for p in players
        ]
