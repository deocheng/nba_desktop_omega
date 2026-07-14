"""NBACore v8 — Trade Graph (T04).

多队交易图（决策①）：每队为独立 ``TeamTradeLeg``，各自独立出/入资产、
各自独立合规校验。整笔交易合法 ⇔ 所有队的 MatchResult.legal 均为 True。

本模块只做「多队结构 + 逐队独立校验编排」，不实现具体规则（规则在
NBARuleSet / match_engine）。``validate_leg`` 聚合一个队的所有规则问题。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from backend.services.trade_engine import rules, schemas


def validate_leg(
    leg: schemas.TeamTradeLeg,
    rs: rules.SalaryRuleSet,
    r: schemas.LeagueSalaryRules,
    as_of: datetime,
) -> schemas.MatchResult:
    """对单队交易腿执行全规则校验，聚合为 MatchResult（逐队独立，决策①）。

    合法判定：所有问题中无 severity='error' 者即通过。
    """
    match_result = rs.check_match(leg, r)
    issues: List[schemas.ValidationIssue] = list(match_result.issues)
    issues += rs.check_byc(leg, r)
    issues += rs.check_tpe(leg, r)
    issues += rs.check_hard_cap(leg, r)
    issues += rs.check_apron(leg, r)
    issues += rs.check_aggregation(leg, r)
    issues += rs.check_freeze(leg, as_of, r)

    legal = not any(i.severity == "error" for i in issues)
    return schemas.MatchResult(
        team_abbr=leg.team_abbr,
        season=leg.season,
        legal=legal,
        issues=issues,
        outbound_guaranteed=match_result.outbound_guaranteed,
        inbound_guaranteed=match_result.inbound_guaranteed,
        max_inbound_allowed=match_result.max_inbound_allowed,
        deficit=match_result.deficit,
        tpe_generated=match_result.tpe_generated,
    )


class TradeGraph:
    """多队交易图：legs_by_team 为每队一条 ``TeamTradeLeg``。"""

    def __init__(self, league: str = "NBA", season: str = "") -> None:
        self.league = league
        self.season = season
        self.legs_by_team: Dict[str, schemas.TeamTradeLeg] = {}

    def add_leg(self, leg: schemas.TeamTradeLeg) -> None:
        self.legs_by_team[leg.team_abbr] = leg

    def teams(self) -> List[schemas.TeamTradeLeg]:
        return list(self.legs_by_team.values())

    @classmethod
    def from_proposal(cls, proposal: schemas.TradeProposal) -> "TradeGraph":
        """由已解析的 TradeProposal 构建交易图。"""
        g = cls(league=proposal.league, season=proposal.season)
        for leg in proposal.legs:
            g.add_leg(leg)
        return g

    def validate_all(
        self,
        rs: rules.SalaryRuleSet,
        r: schemas.LeagueSalaryRules,
        as_of: datetime,
    ) -> List[schemas.MatchResult]:
        """对每队独立调用规则集，返回每队的 MatchResult（顺序同 legs）。"""
        results: List[schemas.MatchResult] = []
        for leg in self.teams():
            results.append(validate_leg(leg, rs, r, as_of))
        return results

    def is_legal(self, results: List[schemas.MatchResult]) -> bool:
        """整笔交易合法 ⇔ 所有队均合法（决策①）。"""
        return bool(results) and all(m.legal for m in results)
