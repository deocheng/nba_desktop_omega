"""NBACore v8 — Trade Engine Rule Interface (T03).

可插拔 per-league 规则引擎契约：
    - ``SalaryRuleSet``(ABC)：声明全部规则钩子 + ``load_rules``。
    - ``RULE_REGISTRY``：按 ``league`` 分派的规则实现注册表。
    - ``get_rule_set(league)``：工厂，未知联赛回落到 NBA。

后续新增联赛（如 CBA / 欧篮）只需实现 SalaryRuleSet 并注册，核心编排
（service / trade_graph）不变（TRADE-06 可插拔）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Type

from backend.services.trade_engine import schemas


class SalaryRuleSet(ABC):
    """联盟规则集抽象基类。所有钩子以 guaranteed 口径 + 整数运算实现。"""

    league: str = "NBA"

    @abstractmethod
    def load_rules(self, season: str) -> schemas.LeagueSalaryRules:
        """加载某赛季联盟薪资规则（默认从 DB；子类可扩展）。"""

    @abstractmethod
    def check_match(
        self, leg: schemas.TeamTradeLeg, r: schemas.LeagueSalaryRules
    ) -> schemas.MatchResult:
        """薪资匹配校验，返回完整 MatchResult（含 SALARY_MATCH 问题）。"""

    @abstractmethod
    def check_byc(
        self, leg: schemas.TeamTradeLeg, r: schemas.LeagueSalaryRules
    ) -> List[schemas.ValidationIssue]:
        """BYC（基础年补偿）校验。"""

    @abstractmethod
    def check_tpe(
        self, leg: schemas.TeamTradeLeg, r: schemas.LeagueSalaryRules
    ) -> List[schemas.ValidationIssue]:
        """TPE（交易特例）/ S-TPE 校验。"""

    @abstractmethod
    def check_hard_cap(
        self, leg: schemas.TeamTradeLeg, r: schemas.LeagueSalaryRules
    ) -> List[schemas.ValidationIssue]:
        """硬工资帽（第二土豪线锁死）校验。"""

    @abstractmethod
    def check_apron(
        self, leg: schemas.TeamTradeLeg, r: schemas.LeagueSalaryRules
    ) -> List[schemas.ValidationIssue]:
        """Apron（第一/第二土豪线）限制校验。"""

    @abstractmethod
    def check_aggregation(
        self, leg: schemas.TeamTradeLeg, r: schemas.LeagueSalaryRules
    ) -> List[schemas.ValidationIssue]:
        """聚合限制（anti-padding）校验。"""

    @abstractmethod
    def check_freeze(
        self, leg: schemas.TeamTradeLeg, as_of: datetime, r: schemas.LeagueSalaryRules
    ) -> List[schemas.ValidationIssue]:
        """冻结期 / 截止日校验（v1 仅 WARN，不阻断）。"""


# 规则实现注册表（league -> SalaryRuleSet 子类）
RULE_REGISTRY: Dict[str, Type[SalaryRuleSet]] = {}

# 延迟注册避免循环导入：在模块导入时由 nba_rules 调用 register_rule_set。
def register_rule_set(league: str, cls: Type[SalaryRuleSet]) -> None:
    """注册一个联赛规则实现。"""
    RULE_REGISTRY[league] = cls


def get_rule_set(league: str = "NBA") -> SalaryRuleSet:
    """按 league 取规则实现；未知联赛回落 NBA。"""
    cls = RULE_REGISTRY.get(league) or RULE_REGISTRY.get("NBA")
    if cls is None:
        raise KeyError(f"no rule set registered for league={league!r}")
    return cls()
