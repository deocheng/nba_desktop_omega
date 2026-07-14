"""NBACore v8 — NBA Rule Set (T03).

``NBARuleSet`` 实现 2023 CBA（2025-26 生效）全部已建模规则：
    - 薪资匹配档位（200% / +$7.5M / 125%，apron 以上 100%）→ match_engine
    - BYC：送出 50% / 接收 100%（缺口提示）
    - TPE / S-TPE：第二土豪线以上禁用以既有 TPE
    - 硬工资帽：第二土豪线锁死（超限即违规）
    - Apron：第一/第二土豪线聚合限制、禁现金、禁先签后换
    - 聚合：7/1–12/15 仅含 1 名底薪（anti-padding）
    - 冻结期：moratorium / trade_deadline（v1 仅 WARN）

金额全整数（BIGINT）；规则常量从 DB 读取（不硬编码）。
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from backend.services.trade_engine import constants, db, match_engine, rules, schemas


class NBARuleSet(rules.SalaryRuleSet):
    """NBA 规则实现（默认插件，league='NBA'）。"""

    league = "NBA"

    # ── 规则常量加载（TRADE-05，不硬编码） ──
    def load_rules(self, season: str) -> schemas.LeagueSalaryRules:
        loaded = db.load_rules(season, league=self.league)
        if loaded is None:
            raise LookupError(f"no league_salary_rules for NBA/{season}")
        return loaded

    # ── 薪资匹配（委托 match_engine，guaranteed 口径） ──
    def check_match(
        self, leg: schemas.TeamTradeLeg, r: schemas.LeagueSalaryRules
    ) -> schemas.MatchResult:
        return match_engine.compute_match(leg, r)

    # ── BYC：送出端 50% 计，提示缺口 ──
    def check_byc(
        self, leg: schemas.TeamTradeLeg, r: schemas.LeagueSalaryRules
    ) -> List[schemas.ValidationIssue]:
        issues: List[schemas.ValidationIssue] = []
        for p in leg.outgoing:
            if p.is_byc():
                gap = p.guaranteed - p.matching_out_value()  # = guaranteed // 2
                issues.append(
                    schemas.ValidationIssue(
                        rule_code="BYC",
                        severity="warn",
                        message=(
                            f"{p.player_name} 处于 BYC：送出端仅计 50%"
                            f"（{p.matching_out_value()}），缺口 {gap}"
                        ),
                        amount_delta=gap,
                    )
                )
        return issues

    # ── TPE：第二土豪线以上禁用既有 TPE ──
    def check_tpe(
        self, leg: schemas.TeamTradeLeg, r: schemas.LeagueSalaryRules
    ) -> List[schemas.ValidationIssue]:
        issues: List[schemas.ValidationIssue] = []
        post_status = match_engine.apron_status_of(leg.post_trade_salary(), r)
        if leg.tpe_used > 0 and post_status == "SECOND":
            issues.append(
                schemas.ValidationIssue(
                    rule_code="TPE",
                    severity="error",
                    message=(
                        f"{leg.team_abbr} 处于第二土豪线以上，不可使用既有 TPE"
                        f"（{leg.tpe_used}）"
                    ),
                    amount_delta=leg.tpe_used,
                )
            )
        return issues

    # ── 硬工资帽：第二土豪线锁死（超限即违规） ──
    def check_hard_cap(
        self, leg: schemas.TeamTradeLeg, r: schemas.LeagueSalaryRules
    ) -> List[schemas.ValidationIssue]:
        issues: List[schemas.ValidationIssue] = []
        post = leg.post_trade_salary()
        if post > r.second_apron:
            over = post - r.second_apron
            issues.append(
                schemas.ValidationIssue(
                    rule_code="HARD_CAP",
                    severity="error",
                    message=(
                        f"{leg.team_abbr} 被硬工资帽限制在第二土豪线，"
                        f"交易后薪资超限 {over}"
                    ),
                    amount_delta=over,
                )
            )
        return issues

    # ── Apron 限制：聚合 / 现金 / 先签后换 ──
    def check_apron(
        self, leg: schemas.TeamTradeLeg, r: schemas.LeagueSalaryRules
    ) -> List[schemas.ValidationIssue]:
        issues: List[schemas.ValidationIssue] = []
        post_status = match_engine.apron_status_of(leg.post_trade_salary(), r)
        n_out = len(leg.outgoing)

        if post_status == "SECOND":
            if n_out > 1:
                issues.append(
                    schemas.ValidationIssue(
                        rule_code="APRON",
                        severity="error",
                        message=(
                            f"{leg.team_abbr} 处于第二土豪线以上，禁止聚合多名球员"
                            f"（当前送出 {n_out} 名，最多 1 名）"
                        ),
                        amount_delta=n_out,
                    )
                )
            if leg.cash_sent > 0:
                issues.append(
                    schemas.ValidationIssue(
                        rule_code="APRON",
                        severity="error",
                        message=(
                            f"{leg.team_abbr} 处于第二土豪线以上，禁止送出现金"
                            f"（{leg.cash_sent}）"
                        ),
                        amount_delta=leg.cash_sent,
                    )
                )
            if leg.sign_and_trade:
                issues.append(
                    schemas.ValidationIssue(
                        rule_code="APRON",
                        severity="warn",
                        message=(
                            f"{leg.team_abbr} 处于第二土豪线以上，禁止通过先签后换获得球员"
                        ),
                        amount_delta=0,
                    )
                )
        elif post_status == "FIRST":
            if n_out > 1:
                issues.append(
                    schemas.ValidationIssue(
                        rule_code="APRON",
                        severity="error",
                        message=(
                            f"{leg.team_abbr} 处于第一土豪线以上，禁止聚合多名球员"
                            f"（当前送出 {n_out} 名，最多 1 名）"
                        ),
                        amount_delta=n_out,
                    )
                )
        return issues

    # ── 聚合限制（anti-padding）：冻结窗口内送出>接收仅含 1 名底薪 ──
    def check_aggregation(
        self, leg: schemas.TeamTradeLeg, r: schemas.LeagueSalaryRules
    ) -> List[schemas.ValidationIssue]:
        issues: List[schemas.ValidationIssue] = []
        calendar = r.freeze_calendar or {}
        dec15_lock = bool(calendar.get("dec15_lock", False))
        n_out = len(leg.outgoing)
        n_in = len(leg.incoming)
        if dec15_lock and n_out > n_in:
            min_players = [
                p for p in leg.outgoing
                if p.guaranteed <= constants.MIN_CONTRACT_THRESHOLD
            ]
            if len(min_players) > 1:
                issues.append(
                    schemas.ValidationIssue(
                        rule_code="AGG",
                        severity="warn",
                        message=(
                            f"{leg.team_abbr} 冻结窗口内送出({n_out})>接收({n_in})，"
                            f"聚合仅可含 1 名底薪球员（当前 {len(min_players)} 名）"
                        ),
                        amount_delta=len(min_players),
                    )
                )
        return issues

    # ── 冻结期 / 截止日（v1 仅 WARN，不阻断） ──
    def check_freeze(
        self, leg: schemas.TeamTradeLeg, as_of: datetime, r: schemas.LeagueSalaryRules
    ) -> List[schemas.ValidationIssue]:
        issues: List[schemas.ValidationIssue] = []
        calendar = r.freeze_calendar or {}

        mor = calendar.get("moratorium")
        if isinstance(mor, (list, tuple)) and len(mor) == 2:
            try:
                start = datetime.fromisoformat(str(mor[0]))
                end = datetime.fromisoformat(str(mor[1]))
                if start <= as_of <= end:
                    issues.append(
                        schemas.ValidationIssue(
                            rule_code="FREEZE",
                            severity="warn",
                            message=(
                                f"{leg.team_abbr} 处于 moratorium 冻结期"
                                f"（{mor[0]}~{mor[1]}），交易可能被限制"
                            ),
                            amount_delta=0,
                        )
                    )
            except (ValueError, TypeError):
                pass

        td = calendar.get("trade_deadline")
        if td:
            try:
                deadline = datetime.fromisoformat(str(td))
                if as_of > deadline:
                    issues.append(
                        schemas.ValidationIssue(
                            rule_code="FREEZE",
                            severity="warn",
                            message=(
                                f"{leg.team_abbr} 已过交易截止日（{td}），交易无效"
                            ),
                            amount_delta=0,
                        )
                    )
            except (ValueError, TypeError):
                pass
        return issues


# 注册到全局注册表（TRADE-06 可插拔）
rules.register_rule_set("NBA", NBARuleSet)
