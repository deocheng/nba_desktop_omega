"""税档 / 工资帽影响测试（TaxEngine.compute → CapImpact，任务⑥）。

纯逻辑：用构造的 pre_trade_salary + cap hit 验证交易前后 payroll / tax / apron 计算。
"""
from __future__ import annotations

from backend.services.trade_engine import schemas, tax_engine
from backend.services.trade_engine.tests.conftest import (
    FIRST_APRON,
    LUXURY_TAX,
    SECOND_APRON,
    make_asset,
)


class TestCapImpact:
    def _leg(self, pre, out_sal, in_sal):
        return schemas.TeamTradeLeg(
            team_abbr="T", season="2025-26", pre_trade_salary=pre,
            outgoing=[make_asset(out_sal, salary=out_sal, player_id="o")],
            incoming=[make_asset(in_sal, salary=in_sal, player_id="i")],
        )

    def test_under_to_over_second_apron(self, rules_2025):
        # pre 180M（低于奢侈税 187.895M）, 送出 10M 收到 40M -> post 210M（SECOND, IN_TAX）
        leg = self._leg(180_000_000, 10_000_000, 40_000_000)
        ci = tax_engine.TaxEngine().compute(leg, rules_2025)
        assert ci.payroll_before == 180_000_000
        assert ci.payroll_after == 210_000_000
        assert ci.tax_status_before == "BELOW_TAX"
        assert ci.tax_status_after == "IN_TAX"
        assert ci.apron_status_before == "BELOW_FIRST"
        assert ci.apron_status_after == "SECOND"
        assert ci.within_second_apron is True

    def test_over_to_below(self, rules_2025):
        # pre 200M, 送出 20M 收到 5M -> post 185M（BELOW_TAX, BELOW_FIRST）
        leg = self._leg(200_000_000, 20_000_000, 5_000_000)
        ci = tax_engine.TaxEngine().compute(leg, rules_2025)
        assert ci.payroll_after == 185_000_000
        assert ci.tax_status_after == "BELOW_TAX"
        assert ci.apron_status_after == "BELOW_FIRST"
        assert ci.within_second_apron is False

    def test_first_to_second_apron_threshold(self, rules_2025):
        # post 刚好压第二土豪线不算跨线
        leg = self._leg(SECOND_APRON - 5_000_000, 0, 5_000_000)
        ci = tax_engine.TaxEngine().compute(leg, rules_2025)
        assert ci.payroll_after == SECOND_APRON
        assert ci.apron_status_after == "FIRST"  # 恰好压线 -> FIRST
        assert ci.within_second_apron is False

    def test_compute_all(self, rules_2025):
        g_legs = [
            self._leg(200_000_000, 10_000_000, 20_000_000),
            self._leg(150_000_000, 5_000_000, 2_000_000),
        ]

        class _G:
            legs_by_team = {f"T{i}": l for i, l in enumerate(g_legs)}

        impacts = tax_engine.TaxEngine().compute_all(_G(), rules_2025)
        assert len(impacts) == 2
        assert impacts[0].payroll_after == 210_000_000
        assert impacts[1].payroll_after == 147_000_000
