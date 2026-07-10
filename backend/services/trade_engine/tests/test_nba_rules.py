"""NBARuleSet 规则钩子测试（任务④ TPE / 硬帽 / apron；任务③ BYC）。

纯逻辑：直接构造 TeamTradeLeg（带 pre_trade_salary 控制 apron 位置）+ 规则常量。
"""
from __future__ import annotations

from datetime import datetime

from backend.services.trade_engine import nba_rules, rules as rules_mod, schemas
from backend.services.trade_engine.tests.conftest import (
    SECOND_APRON,
    make_asset,
)

AS_OF = datetime(2026, 1, 15)
RS = nba_rules.NBARuleSet()


def _leg(out_g, in_g, *, pre, out_sal=None, in_sal=None, n_out_extra=0,
         cash_sent=0, tpe_used=0, sign_and_trade=False, team="T"):
    out_sal = out_g if out_sal is None else out_sal
    in_sal = in_g if in_sal is None else in_sal
    outgoing = [make_asset(out_g, salary=out_sal, player_id="o")]
    # 额外送出球员（用于聚合测试），salary 计入 cap
    for k in range(n_out_extra):
        outgoing.append(make_asset(5_000_000, salary=5_000_000, player_id=f"ox{k}"))
    return schemas.TeamTradeLeg(
        team_abbr=team, season="2025-26", pre_trade_salary=pre,
        outgoing=outgoing,
        incoming=[make_asset(in_g, salary=in_sal, player_id="i")],
        cash_sent=cash_sent, tpe_used=tpe_used, sign_and_trade=sign_and_trade,
    )


class TestBYC:
    def test_byc_issue_gap(self, rules_2025):
        leg = schemas.TeamTradeLeg(
            team_abbr="T", season="2025-26",
            outgoing=[make_asset(20_000_000, byc=True, player_id="byc1")],
            incoming=[make_asset(10_000_000, player_id="i")],
        )
        issues = RS.check_byc(leg, rules_2025)
        assert len(issues) == 1
        assert issues[0].rule_code == "BYC"
        assert issues[0].severity == "warn"
        # 缺口 = guaranteed - 50% = 10M
        assert issues[0].amount_delta == 10_000_000

    def test_no_byc_no_issue(self, rules_2025):
        leg = schemas.TeamTradeLeg(
            team_abbr="T", season="2025-26",
            outgoing=[make_asset(20_000_000, player_id="o")],
            incoming=[make_asset(10_000_000, player_id="i")],
        )
        assert RS.check_byc(leg, rules_2025) == []


class TestHardCap:
    def test_hard_cap_over_second_apron(self, rules_2025):
        # pre 210M, out 30M(sal), in 35M(sal) -> post 215M > second_apron
        leg = _leg(30_000_000, 35_000_000, pre=210_000_000)
        issues = RS.check_hard_cap(leg, rules_2025)
        assert len(issues) == 1
        assert issues[0].rule_code == "HARD_CAP"
        assert issues[0].severity == "error"
        assert issues[0].amount_delta == 215_000_000 - SECOND_APRON

    def test_no_hard_cap_below_second(self, rules_2025):
        # pre 200M, out 10M(sal), in 8M(sal) -> post 198M < second_apron
        leg = _leg(10_000_000, 8_000_000, pre=200_000_000)
        assert RS.check_hard_cap(leg, rules_2025) == []


class TestTPE:
    def test_tpe_forbidden_at_second_apron(self, rules_2025):
        # 处于 SECOND 且使用既有 TPE -> 报错
        leg = _leg(30_000_000, 35_000_000, pre=210_000_000, tpe_used=5_000_000)
        issues = RS.check_tpe(leg, rules_2025)
        assert any(i.rule_code == "TPE" for i in issues)
        tpe = next(i for i in issues if i.rule_code == "TPE")
        assert tpe.severity == "error"
        assert tpe.amount_delta == 5_000_000

    def test_tpe_allowed_below_second(self, rules_2025):
        # 交易后未越第二土豪线 -> 不禁用 TPE
        leg = _leg(10_000_000, 8_000_000, pre=200_000_000, tpe_used=5_000_000)
        assert RS.check_tpe(leg, rules_2025) == []


class TestApron:
    def test_second_apron_aggregation_and_cash(self, rules_2025):
        # post 处于 SECOND（pre 213M, out 30M+5M sal, in 30M sal -> post 208M）
        leg = _leg(30_000_000, 30_000_000, pre=213_000_000, n_out_extra=1, cash_sent=1_000_000)
        issues = RS.check_apron(leg, rules_2025)
        codes = [i.rule_code for i in issues]
        assert codes.count("APRON") >= 2  # 聚合 1 + 现金 1
        assert any(i.amount_delta == 1_000_000 for i in issues)  # 现金额
        # 聚合错误应为 error
        assert any(i.severity == "error" and i.amount_delta == 2 for i in issues)  # n_out=2

    def test_first_apron_aggregation_only(self, rules_2025):
        # post 处于 FIRST（pre 201M, out 10M+5M sal, in 10M sal -> post 196M）
        leg = _leg(10_000_000, 10_000_000, pre=201_000_000, n_out_extra=1, cash_sent=0)
        issues = RS.check_apron(leg, rules_2025)
        assert len(issues) == 1
        assert issues[0].rule_code == "APRON"
        assert issues[0].severity == "error"

    def test_sign_and_trade_warn_at_second(self, rules_2025):
        leg = _leg(30_000_000, 35_000_000, pre=210_000_000, sign_and_trade=True)
        issues = RS.check_apron(leg, rules_2025)
        sat = [i for i in issues if i.rule_code == "APRON" and i.severity == "warn"]
        assert len(sat) == 1


class TestFreeze:
    def test_moratorium_warn(self, rules_2025):
        # 注入 freeze_calendar（与 sql/002 回填值一致）
        r = rules_2025.model_copy(update={
            "freeze_calendar": {
                "moratorium": ["2025-07-01", "2025-07-06"],
                "trade_deadline": "2026-02-05",
                "dec15_lock": True,
            }
        })
        leg = _leg(10_000_000, 8_000_000, pre=200_000_000)
        issues = RS.check_freeze(leg, datetime(2025, 7, 3), r)
        assert any(i.rule_code == "FREEZE" for i in issues)
