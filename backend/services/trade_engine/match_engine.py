"""NBACore v8 — Trade Match Engine (T03/T04 core math).

纯函数薪资匹配核心（guaranteed 口径，决策③）：
    - 匹配档位分档（200% / +$7.5M / 125%，apron 以上 100%）
    - 逐队匹配结果计算（outbound / inbound / deficit / TPE 生成）
    - apron / tax 状态判定（税档引擎与匹配共用）

全部整数运算，禁止浮点。不依赖任何 DB / 规则子类，便于单测。
"""
from __future__ import annotations

from typing import List

from backend.services.trade_engine import constants, schemas

# 匹配档位阈值（2023 CBA，2025-26 生效，见 PRD §3.2）
_BAND1_MAX_OUT = 7_500_000
_BAND2_MAX_OUT = 29_000_000
_FLAT_ADD = 7_500_000
_PCT_ADD = 250_000


def apron_status_of(salary: int, rules: schemas.LeagueSalaryRules) -> schemas.ApronStatus:
    """根据总薪资判定 apron 状态。"""
    if salary > rules.second_apron:
        return "SECOND"
    if salary > rules.first_apron:
        return "FIRST"
    return "BELOW_FIRST"


def tax_status_of(salary: int, rules: schemas.LeagueSalaryRules) -> schemas.TaxStatus:
    """根据总薪资判定奢侈税状态。"""
    return "IN_TAX" if salary > rules.luxury_tax else "BELOW_TAX"


def band_max_inbound(
    outbound: int, post_cap_status: schemas.ApronStatus, rules: schemas.LeagueSalaryRules
) -> int:
    """给定送出额与交易后 apron 状态，返回可接收进薪上限（不含 TPE）。

    口径（PRD §3.2）：
        - 第一土豪线及以上（FIRST/SECOND）：100% × 送出
        - 第一土豪线以下：
            ≤ $7.5M      → 200% × 送出 + $250k
            ≤ $29M       → 送出 + $7.5M
            > $29M       → 125% × 送出 + $250k（整数：5/4）
    全整数运算。
    """
    if post_cap_status in ("FIRST", "SECOND"):
        return outbound
    if outbound <= _BAND1_MAX_OUT:
        return 2 * outbound + _PCT_ADD
    if outbound <= _BAND2_MAX_OUT:
        return outbound + _FLAT_ADD
    return (5 * outbound) // 4 + _PCT_ADD


def compute_match(
    leg: schemas.TeamTradeLeg, rules: schemas.LeagueSalaryRules
) -> schemas.MatchResult:
    """计算单队薪资匹配结果（guaranteed 口径，决策③）。

    返回 MatchResult，含 SALARY_MATCH 问题（如有）、deficit、TPE 生成。
    其余规则问题由 ``validate_leg`` 聚合。
    """
    outbound = leg.outbound_guaranteed()
    inbound = leg.inbound_guaranteed()
    post_salary = leg.post_trade_salary()
    post_status = apron_status_of(post_salary, rules)

    base_max = band_max_inbound(outbound, post_status, rules)
    max_inbound = base_max + (leg.tpe_used or 0)

    deficit = inbound - max_inbound
    issues: List[schemas.ValidationIssue] = []
    if deficit > 0:
        issues.append(
            schemas.ValidationIssue(
                rule_code="SALARY_MATCH",
                severity="error",
                message=(
                    f"{leg.team_abbr} 薪资不匹配：进薪 {inbound} > 上限 {max_inbound}"
                    f"（送出 {outbound}，TPE 已用 {leg.tpe_used}），缺口 {deficit}"
                ),
                amount_delta=deficit,
            )
        )

    tpe_generated: dict = {}
    if outbound > inbound:
        tpe_generated[leg.team_abbr] = outbound - inbound

    return schemas.MatchResult(
        team_abbr=leg.team_abbr,
        season=leg.season,
        legal=deficit <= 0,
        issues=issues,
        outbound_guaranteed=outbound,
        inbound_guaranteed=inbound,
        max_inbound_allowed=max_inbound,
        deficit=max(0, deficit),
        tpe_generated=tpe_generated,
    )
