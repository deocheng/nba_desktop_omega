"""多队交易图测试（决策①：3+ 队，每队独立校验，整笔合法 ⇔ 所有队合法）。

纯逻辑：构造 3 队 TeamTradeLeg（各自 pre_trade_salary 控制 cap 位置）。
"""
from __future__ import annotations

from datetime import datetime

from backend.services.trade_engine import rules as rules_mod, schemas, trade_graph
from backend.services.trade_engine.tests.conftest import make_asset

AS_OF = datetime(2026, 1, 15)
RS = rules_mod.get_rule_set("NBA")


def _cap_below_leg(team, out_g, in_g, pre=100_000_000):
    """构造一个 cap 以下、默认合法的队腿（band +$7.5M）。"""
    return schemas.TeamTradeLeg(
        team_abbr=team, season="2025-26", pre_trade_salary=pre,
        outgoing=[make_asset(out_g, player_id=f"{team}_o")],
        incoming=[make_asset(in_g, player_id=f"{team}_i")],
    )


class TestValidateLeg:
    def test_aggregates_all_rules(self, rules_2025):
        # 构造一支越过第二土豪线且聚合的腿，聚合所有规则问题
        leg = schemas.TeamTradeLeg(
            team_abbr="T", season="2025-26", pre_trade_salary=210_000_000,
            outgoing=[make_asset(30_000_000, salary=30_000_000, player_id="o1"),
                      make_asset(5_000_000, salary=5_000_000, player_id="o2")],
            incoming=[make_asset(40_000_000, salary=40_000_000, player_id="i")],
            cash_sent=1_000_000,
        )
        mr = trade_graph.validate_leg(leg, RS, rules_2025, AS_OF)
        codes = {i.rule_code for i in mr.issues}
        # 应含 SALARY_MATCH / HARD_CAP / APRON（聚合+现金）
        assert "SALARY_MATCH" in codes
        assert "HARD_CAP" in codes
        assert "APRON" in codes
        assert mr.legal is False

    def test_legal_when_no_error(self, rules_2025):
        leg = _cap_below_leg("T", 10_000_000, 12_000_000)
        mr = trade_graph.validate_leg(leg, RS, rules_2025, AS_OF)
        assert mr.legal is True
        assert not any(i.severity == "error" for i in mr.issues)


class TestThreeTeamGraph:
    def _all_legal_graph(self):
        g = trade_graph.TradeGraph(league="NBA", season="2025-26")
        g.add_leg(_cap_below_leg("A", 10_000_000, 12_000_000, pre=100_000_000))
        g.add_leg(_cap_below_leg("B", 20_000_000, 25_000_000, pre=120_000_000))
        g.add_leg(_cap_below_leg("C", 10_000_000, 10_000_000, pre=100_000_000))
        return g

    def test_all_legal(self, rules_2025):
        g = self._all_legal_graph()
        results = g.validate_all(RS, rules_2025, AS_OF)
        assert len(results) == 3
        assert all(m.legal for m in results)
        # 决策①：所有队合法 -> 整笔合法
        assert g.is_legal(results) is True

    def test_one_illegal_makes_whole_illegal(self, rules_2025):
        g = self._all_legal_graph()
        # 让 C 队不合法：incoming 超过 band（+$7.5M 上限 17.5M，收到 20M）
        g.legs_by_team["C"] = _cap_below_leg("C", 10_000_000, 20_000_000, pre=100_000_000)
        results = g.validate_all(RS, rules_2025, AS_OF)
        by_team = {m.team_abbr: m for m in results}
        assert by_team["C"].legal is False
        assert by_team["A"].legal is True
        assert by_team["B"].legal is True
        # 决策①：任一队不合法 -> 整笔不合法
        assert g.is_legal(results) is False

    def test_from_proposal_preserves_order(self, rules_2025):
        prop = schemas.TradeProposal(
            league="NBA", season="2025-26", as_of=AS_OF,
            legs=[
                _cap_below_leg("A", 10_000_000, 12_000_000),
                _cap_below_leg("B", 20_000_000, 25_000_000),
                _cap_below_leg("C", 10_000_000, 10_000_000),
            ],
        )
        g = trade_graph.TradeGraph.from_proposal(prop)
        results = g.validate_all(RS, rules_2025, AS_OF)
        assert [m.team_abbr for m in results] == ["A", "B", "C"]
        assert g.is_legal(results) is True
