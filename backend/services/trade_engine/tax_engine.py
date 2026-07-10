"""NBACore v8 — Tax / Cap Impact Engine (T06, TRADE-03).

计算交易前后各队薪资总额、奢侈税、第一/第二 apron 状态变化（CapImpact）。
税档基于球队「薪资总额」（salary，非保障额）；匹配差额仍用 guaranteed（决策③），
两者分离、口径清晰。

全整数运算；规则常量从传入的 LeagueSalaryRules 读取。
"""
from __future__ import annotations

from typing import Dict, List

from backend.services.trade_engine import match_engine, schemas


class TaxEngine:
    """税档 / 工资帽影响计算（无 DB，纯内存）。"""

    @staticmethod
    def tax_status(salary: int, r: schemas.LeagueSalaryRules) -> schemas.TaxStatus:
        return match_engine.tax_status_of(salary, r)

    @staticmethod
    def apron_status(salary: int, r: schemas.LeagueSalaryRules) -> schemas.ApronStatus:
        return match_engine.apron_status_of(salary, r)

    def compute(
        self, leg: schemas.TeamTradeLeg, r: schemas.LeagueSalaryRules
    ) -> schemas.CapImpact:
        """计算单队交易前后税档 / 工资帽影响。"""
        before = leg.pre_trade_salary
        after = leg.post_trade_salary()
        return schemas.CapImpact(
            team_abbr=leg.team_abbr,
            payroll_before=before,
            payroll_after=after,
            tax_status_before=self.tax_status(before, r),
            tax_status_after=self.tax_status(after, r),
            apron_status_before=self.apron_status(before, r),
            apron_status_after=self.apron_status(after, r),
            within_second_apron=after > r.second_apron,
        )

    def compute_all(
        self, graph: "object", r: schemas.LeagueSalaryRules
    ) -> List[schemas.CapImpact]:
        """对交易图中每个参与队计算 CapImpact。"""
        # graph.legs_by_team values are TeamTradeLeg
        legs = getattr(graph, "legs_by_team", {})
        if isinstance(legs, dict):
            leg_list = list(legs.values())
        else:
            leg_list = list(legs)
        return [self.compute(leg, r) for leg in leg_list]
