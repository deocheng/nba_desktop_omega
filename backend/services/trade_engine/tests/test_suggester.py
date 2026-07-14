"""匹配建议 / 方案生成测试（任务② MatchSuggester，任务⑦ ProposalGenerator）。

MatchSuggester：纯逻辑构造不合法队腿 + 候选池，验证能给出通过的建议且复验生效。
ProposalGenerator：DB 相关，验证对真实目标球员生成 ≥1 个方案，并复验方案合法。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.services.trade_engine import rules as rules_mod, schemas, suggester
from backend.services.trade_engine.tests.conftest import (
    DB_OK,
    make_asset,
    skip_if_no_db,
)
from backend.services.trade_engine.tests.conftest import RULE_SET as RS, AS_OF

SV = suggester.MatchSuggester()


class TestMatchSuggester:
    def _illegal_leg(self, team="T"):
        # cap 以下，band +$7.5M：out 10M -> max 17.5M，in 20M -> 缺口 2.5M
        return schemas.TeamTradeLeg(
            team_abbr=team, season="2025-26", pre_trade_salary=100_000_000,
            outgoing=[make_asset(10_000_000, player_id="o")],
            incoming=[make_asset(20_000_000, player_id="i")],
        )

    def test_greedy_add_passes_and_verified(self, rules_2025):
        leg = self._illegal_leg()
        pool = [
            make_asset(1_000_000, player_id="a"),
            make_asset(2_000_000, player_id="b"),
            make_asset(3_000_000, player_id="c"),
        ]
        sugs = SV.suggest(leg, RS, pool, rules_2025, AS_OF)
        passed = [s for s in sugs if s.passes]
        assert passed, "应至少给出一条可通过的建议"
        # 复验：把建议应用到原腿，再次走完整规则校验应合法
        s = passed[0]
        new_out = list(leg.outgoing) + [p for p in pool if p.player_id in s.add_player_ids]
        re_leg = leg.model_copy(update={"outgoing": new_out})
        from backend.services.trade_engine.trade_graph import validate_leg
        mr = validate_leg(re_leg, RS, rules_2025, AS_OF)
        assert mr.legal is True

    def test_greedy_remove_passes_and_verified(self, rules_2025):
        # incoming 含一名高价 + 一名低价，移除高价即通过
        leg = schemas.TeamTradeLeg(
            team_abbr="T", season="2025-26", pre_trade_salary=100_000_000,
            outgoing=[make_asset(10_000_000, player_id="o")],
            incoming=[make_asset(20_000_000, player_id="big"),
                      make_asset(3_000_000, player_id="small")],
        )
        pool = [make_asset(1_000_000, player_id="a")]
        sugs = SV.suggest(leg, RS, pool, rules_2025, AS_OF)
        passed = [s for s in sugs if s.passes]
        assert passed, "移除高价球员应通过"
        s = passed[0]
        assert s.remove_player_ids  # 走了 remove 杠杆
        new_in = [p for p in leg.incoming if p.player_id not in s.remove_player_ids]
        re_leg = leg.model_copy(update={"incoming": new_in})
        from backend.services.trade_engine.trade_graph import validate_leg
        mr = validate_leg(re_leg, RS, rules_2025, AS_OF)
        assert mr.legal is True


@skip_if_no_db
class TestProposalGenerator:
    def test_generates_verified_proposals(self):
        from backend.services.trade_engine import service

        svc = service.TradeService()
        req = schemas.TradeGenerateRequest(
            season="2025-26", target_player_id="portemi01", initiator_team="GSW"
        )
        out = svc.generate(req)
        assert out["count"] >= 1, "应至少生成 1 个方案"
        assert out["count"] <= 10
        # 复验：每个方案重新走 /trade/validate 必须合法
        for p in out["proposals"]:
            vreq = schemas.TradeValidateRequest(
                season="2025-26", as_of=datetime(2026, 1, 15),
                legs=[schemas.LegRequest(**l) for l in p["legs"]],
            )
            vres = svc.validate(vreq)
            assert vres["legal"] is True, f"方案 {p['legs']} 复验应为合法"
