"""真实库内集成测试（任务⑥ GSW/BRK 样例 + 任务⑧ 时间线）。

使用真实库内 GSW / BRK 数据，验证：
  - 任务⑥：GSW 收多于送且越过第二土豪线 $207,824,000 -> 触发 SALARY_MATCH + HARD_CAP，
            CapImpact 的 payroll / tax / apron 计算正确。
  - 任务⑧：球员 / 球队 6 季时间线返回结构正确（仅 2025-26 真实，其余季为 0/近似属已知简化）。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.services.trade_engine import schemas, service
from backend.services.trade_engine.tests.conftest import (
    SECOND_APRON,
    skip_if_no_db,
)


@skip_if_no_db
class TestGSWBRKTrade:
    """工程师曾验证：GSW 收多于送且越过第二土豪线 -> SALARY_MATCH + HARD_CAP。"""

    @staticmethod
    def _gsw_brk_request():
        return schemas.TradeValidateRequest(
            season="2025-26", as_of=datetime(2026, 1, 15),
            legs=[
                schemas.LegRequest(
                    team_abbr="GSW",
                    outgoing=["curryst01"],
                    incoming=["portemi01", "claxtni01", "mannte01"],
                ),
                schemas.LegRequest(
                    team_abbr="BRK",
                    outgoing=["portemi01", "claxtni01", "mannte01"],
                    incoming=["curryst01"],
                ),
            ],
        )

    def test_whole_trade_illegal(self):
        svc = service.TradeService()
        res = svc.validate(self._gsw_brk_request())
        assert res["legal"] is False

    def test_gsw_triggers_salary_match_and_hard_cap(self):
        svc = service.TradeService()
        res = svc.validate(self._gsw_brk_request())
        gsw = next(m for m in res["results"] if m["team_abbr"] == "GSW")
        codes = {i["rule_code"]: i for i in gsw["issues"]}
        assert "SALARY_MATCH" in codes and codes["SALARY_MATCH"]["severity"] == "error"
        assert "HARD_CAP" in codes and codes["HARD_CAP"]["severity"] == "error"
        # SALARY_MATCH 差额 = 进薪 - 上限（内部一致性，基于真实 guaranteed）
        assert codes["SALARY_MATCH"]["amount_delta"] == (
            gsw["inbound_guaranteed"] - gsw["max_inbound_allowed"]
        )
        # HARD_CAP 差额 = 交易后薪资 - 第二土豪线（内部一致性）
        cap = next(c for c in res["cap_impact"] if c["team_abbr"] == "GSW")
        assert codes["HARD_CAP"]["amount_delta"] == cap["payroll_after"] - SECOND_APRON

    def test_gsw_cap_impact_crosses_second_apron(self):
        svc = service.TradeService()
        res = svc.validate(self._gsw_brk_request())
        cap = next(c for c in res["cap_impact"] if c["team_abbr"] == "GSW")
        # 交易前未越第二土豪线，交易后越过（收多于送）
        assert cap["payroll_before"] < SECOND_APRON
        assert cap["payroll_after"] > SECOND_APRON
        assert cap["apron_status_after"] == "SECOND"
        assert cap["within_second_apron"] is True
        assert cap["tax_status_after"] == "IN_TAX"

    def test_brk_legal_counterparty(self):
        svc = service.TradeService()
        res = svc.validate(self._gsw_brk_request())
        brk = next(m for m in res["results"] if m["team_abbr"] == "BRK")
        assert brk["legal"] is True


@skip_if_no_db
class TestTimelines:
    def test_player_timeline_six_seasons(self):
        svc = service.TradeService()
        tl = svc.player_timeline("curryst01", "2025-26")
        assert tl is not None
        assert set(tl["salaries"].keys()) == {
            "2025-26", "2026-27", "2027-28", "2028-29", "2029-30", "2030-31"
        }
        # 2025-26 为真实薪资，非 0
        assert tl["salaries"]["2025-26"] > 0
        assert tl["guaranteed"]["2025-26"] > 0
        # 其余季为 0/近似属已知简化，不判 fail（仅验证键齐全）

    def test_team_timeline_gsw(self):
        svc = service.TradeService()
        tt = svc.team_timeline("GSW", "2025-26")
        assert tt is not None
        assert set(tt["total_salary"].keys()) == {
            "2025-26", "2026-27", "2027-28", "2028-29", "2029-30", "2030-31"
        }
        # GSW 2025-26 真实总薪资与税档态势
        assert tt["total_salary"]["2025-26"] == 204_744_987
        assert tt["apron_status"]["2025-26"] == "FIRST"
        assert tt["tax_status"]["2025-26"] == "IN_TAX"
