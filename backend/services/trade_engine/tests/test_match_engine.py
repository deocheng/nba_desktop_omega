"""薪资匹配档位测试（决策③：guaranteed 口径）。

覆盖 PRD §3.2 的全部档位：
  A. 第一土豪线以下：≤$7.5M → 200%+$250k；≤$29M → +$7.5M；>$29M → 125%+$250k
  B. 第一土豪线及以上（FIRST）：100% × 送出
  C. 第二土豪线及以上（SECOND）：100% × 送出
并核对 deficit 金额、apron / tax 状态判定（match_engine 纯函数）。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.services.trade_engine import match_engine, schemas
from backend.services.trade_engine.tests.conftest import (
    FIRST_APRON,
    LUXURY_TAX,
    SECOND_APRON,
    make_asset,
)

AS_OF = datetime(2026, 1, 15)


# ───────────────────────── 档位分档（band_max_inbound） ─────────────────────────
class TestBandMaxInbound:
    def test_band1_under_cap_200pct(self, rules_2025):
        # ≤ $7.5M -> 200% + $250k
        assert match_engine.band_max_inbound(5_000_000, "BELOW_FIRST", rules_2025) == 2 * 5_000_000 + 250_000
        # 边界：恰好 $7.5M 仍属 200% 档
        assert match_engine.band_max_inbound(7_500_000, "BELOW_FIRST", rules_2025) == 2 * 7_500_000 + 250_000

    def test_band2_under_cap_flat_add(self, rules_2025):
        # ≤ $29M -> 送出 + $7.5M
        assert match_engine.band_max_inbound(10_000_000, "BELOW_FIRST", rules_2025) == 10_000_000 + 7_500_000
        # 边界：恰好 $29M 仍属 +$7.5M 档
        assert match_engine.band_max_inbound(29_000_000, "BELOW_FIRST", rules_2025) == 29_000_000 + 7_500_000

    def test_band3_under_cap_125pct(self, rules_2025):
        # > $29M -> 125% + $250k（整数 5/4）
        assert match_engine.band_max_inbound(30_000_000, "BELOW_FIRST", rules_2025) == (5 * 30_000_000) // 4 + 250_000

    def test_band_over_first_apron_100pct(self, rules_2025):
        # FIRST / SECOND -> 100% × 送出
        assert match_engine.band_max_inbound(30_000_000, "FIRST", rules_2025) == 30_000_000
        assert match_engine.band_max_inbound(30_000_000, "SECOND", rules_2025) == 30_000_000


# ───────────────────────── apron / tax 状态判定 ─────────────────────────
class TestStatusHelpers:
    def test_apron_status_of(self, rules_2025):
        assert match_engine.apron_status_of(208_000_000, rules_2025) == "SECOND"
        assert match_engine.apron_status_of(FIRST_APRON + 1, rules_2025) == "FIRST"
        assert match_engine.apron_status_of(190_000_000, rules_2025) == "BELOW_FIRST"
        # 恰好压线不算跨线（> 严格大于）
        assert match_engine.apron_status_of(SECOND_APRON, rules_2025) == "FIRST"

    def test_tax_status_of(self, rules_2025):
        assert match_engine.tax_status_of(LUXURY_TAX + 1, rules_2025) == "IN_TAX"
        assert match_engine.tax_status_of(180_000_000, rules_2025) == "BELOW_TAX"
        # 恰好压线不算超税
        assert match_engine.tax_status_of(LUXURY_TAX, rules_2025) == "BELOW_TAX"


# ───────────────────────── compute_match：cap 以下档位 ─────────────────────────
class TestComputeMatchUnderCap:
    def _leg(self, out_g, in_g, pre=100_000_000):
        return schemas.TeamTradeLeg(
            team_abbr="T", season="2025-26", pre_trade_salary=pre,
            outgoing=[make_asset(out_g, player_id="o")],
            incoming=[make_asset(in_g, player_id="i")],
        )

    def test_band1_legal(self, rules_2025):
        # out 5M, max 10.25M, in 10M -> legal
        mr = match_engine.compute_match(self._leg(5_000_000, 10_000_000), rules_2025)
        assert mr.legal is True
        assert mr.max_inbound_allowed == 10_250_000
        assert mr.deficit == 0

    def test_band1_boundary_illegal(self, rules_2025):
        # out 7.5M, max 15.25M, in 15.25M+1 -> 缺口 1
        mr = match_engine.compute_match(self._leg(7_500_000, 15_250_001), rules_2025)
        assert mr.legal is False
        assert mr.deficit == 1
        assert mr.issues[0].rule_code == "SALARY_MATCH"

    def test_band2_boundary_illegal(self, rules_2025):
        # out 29M, max 36.5M, in 36.5M+1 -> 缺口 1
        mr = match_engine.compute_match(self._leg(29_000_000, 36_500_001), rules_2025)
        assert mr.legal is False
        assert mr.deficit == 1

    def test_band3_illegal_deficit(self, rules_2025):
        # out 30M, max 37.75M, in 40M -> 缺口 2.25M
        mr = match_engine.compute_match(self._leg(30_000_000, 40_000_000), rules_2025)
        assert mr.legal is False
        assert mr.deficit == 40_000_000 - ((5 * 30_000_000) // 4 + 250_000)
        assert mr.deficit == 2_250_000


# ───────────────────────── compute_match：apron 以上 100% 档 ─────────────────────────
class TestComputeMatchOverApron:
    def _leg(self, out_g, in_g, pre, out_sal=None, in_sal=None):
        out_sal = out_g if out_sal is None else out_sal
        in_sal = in_g if in_sal is None else in_sal
        return schemas.TeamTradeLeg(
            team_abbr="T", season="2025-26", pre_trade_salary=pre,
            outgoing=[make_asset(out_g, salary=out_sal, player_id="o")],
            incoming=[make_asset(in_g, salary=in_sal, player_id="i")],
        )

    def test_first_apron_100pct_legal(self, rules_2025):
        # pre 200M, out 10M(sal), in 8M(sal) -> post 198M (FIRST), 100%×10M=10M, in 8M -> legal
        mr = match_engine.compute_match(self._leg(10_000_000, 8_000_000, pre=200_000_000), rules_2025)
        assert mr.legal is True
        assert mr.max_inbound_allowed == 10_000_000

    def test_first_apron_100pct_illegal(self, rules_2025):
        # pre 200M, out 10M(sal), in 15M(sal) -> post 205M (FIRST), 100%×10M=10M, in 15M -> 缺口 5M
        mr = match_engine.compute_match(self._leg(10_000_000, 15_000_000, pre=200_000_000), rules_2025)
        assert mr.legal is False
        assert mr.deficit == 5_000_000

    def test_second_apron_100pct_illegal_and_hardcap(self, rules_2025):
        # pre 210M, out 30M(sal), in 35M(sal) -> post 215M (SECOND)
        leg = self._leg(30_000_000, 35_000_000, pre=210_000_000)
        mr = match_engine.compute_match(leg, rules_2025)
        # SALARY_MATCH 缺口 = 35M - 30M = 5M（SECOND 档 100%）
        assert mr.legal is False
        assert mr.deficit == 5_000_000
        # 硬帽由 check_hard_cap 单独判定（这里仅验证匹配缺口）
        from backend.services.trade_engine import nba_rules, rules as rulesmod
        rs = rulesmod.get_rule_set("NBA")
        issues = nba_rules.NBARuleSet().check_hard_cap(leg, rules_2025)
        assert any(i.rule_code == "HARD_CAP" for i in issues)
        hard = next(i for i in issues if i.rule_code == "HARD_CAP")
        assert hard.amount_delta == 215_000_000 - SECOND_APRON
