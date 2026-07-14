"""PlayerAsset 取值方法测试：BYC（任务③）、two-way（决策④）、cap_hit。

决策③：匹配用 guaranteed 口径。
决策④：is_two_way=true 的球员匹配/税档均按 $0 计。
BYC：送出端计 50%、接收端计 100%。
"""
from __future__ import annotations

from backend.services.trade_engine.tests.conftest import make_asset


class TestMatchingValues:
    def test_normal_full_guaranteed(self):
        a = make_asset(10_000_000)
        assert a.matching_out_value() == 10_000_000
        assert a.matching_in_value() == 10_000_000
        assert a.cap_hit() == 10_000_000

    def test_byc_out_50pct_in_100pct(self):
        # 任务③：BYC 送出端 50%、接收端 100%
        a = make_asset(20_000_000, byc=True)
        assert a.is_byc() is True
        assert a.matching_out_value() == 20_000_000 // 2  # 10M
        assert a.matching_in_value() == 20_000_000        # 20M

    def test_byc_odd_guaranteed_floor(self):
        # 奇数 guaranteed 向下取整
        a = make_asset(19_000_001, byc=True)
        assert a.matching_out_value() == 19_000_001 // 2  # 9_500_000

    def test_two_way_zero(self):
        # 决策④：two-way 匹配/税档均 $0
        a = make_asset(600_000, is_two_way=True)
        assert a.matching_out_value() == 0
        assert a.matching_in_value() == 0
        assert a.cap_hit() == 0

    def test_two_way_byc_combined_still_zero(self):
        # two-way 优先于 BYC，仍为 $0
        a = make_asset(20_000_000, is_two_way=True, byc=True)
        assert a.matching_out_value() == 0
        assert a.matching_in_value() == 0


class TestLegAggregations:
    def test_outbound_inbound_aggregations(self):
        from backend.services.trade_engine import schemas

        leg = schemas.TeamTradeLeg(
            team_abbr="T", season="2025-26",
            outgoing=[make_asset(10_000_000, player_id="o1"), make_asset(5_000_000, player_id="o2")],
            incoming=[make_asset(8_000_000, player_id="i1")],
        )
        assert leg.outbound_guaranteed() == 15_000_000
        assert leg.inbound_guaranteed() == 8_000_000
        assert leg.outbound_cap() == 15_000_000
        assert leg.inbound_cap() == 8_000_000

    def test_two_way_excluded_from_leg_totals(self):
        from backend.services.trade_engine import schemas

        leg = schemas.TeamTradeLeg(
            team_abbr="T", season="2025-26",
            outgoing=[make_asset(10_000_000, player_id="o1"), make_asset(600_000, is_two_way=True, player_id="tw")],
            incoming=[make_asset(600_000, is_two_way=True, player_id="twi")],
        )
        # two-way 不计入匹配/税档
        assert leg.outbound_guaranteed() == 10_000_000
        assert leg.inbound_guaranteed() == 0
        assert leg.outbound_cap() == 10_000_000
        assert leg.inbound_cap() == 0

    def test_post_trade_salary(self):
        from backend.services.trade_engine import schemas

        leg = schemas.TeamTradeLeg(
            team_abbr="T", season="2025-26", pre_trade_salary=200_000_000,
            outgoing=[make_asset(10_000_000, salary=10_000_000, player_id="o1")],
            incoming=[make_asset(8_000_000, salary=8_000_000, player_id="i1")],
        )
        assert leg.post_trade_salary() == 200_000_000 - 10_000_000 + 8_000_000
