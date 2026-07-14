"""NBACore v8 — Trade Engine Schemas (Pydantic models).

此文件仅定义数据结构与轻量取值方法（无 DB / 无规则逻辑）：
    - 领域模型：PlayerAsset / TeamTradeLeg / TradeProposal / TradeGraph
    - 结果模型：ValidationIssue / MatchResult / CapImpact / Suggestion
    - 规则常量：LeagueSalaryRules
    - 时间线：   PlayerTimeline / TeamTimeline
    - 请求/响应： ValidateRequest / SuggestRequest / GenerateRequest / RulesUpsertRequest

全部金额字段为 BIGINT 美元整数（与 DB 一致）。引擎层做全整数运算，禁止浮点。
前端展示层再做 ``$XX.XM`` 格式化。

遵循 Google 风格 + 适度中英文注释。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# 规则代码（与 architecture.md §3.4 对齐）
RuleCode = Literal["SALARY_MATCH", "BYC", "TPE", "HARD_CAP", "APRON", "AGG", "FREEZE"]
Severity = Literal["error", "warn"]

# 税档 / apron 状态枚举
TaxStatus = Literal["BELOW_TAX", "IN_TAX"]
ApronStatus = Literal["BELOW_FIRST", "FIRST", "SECOND"]


# ─────────────────────────────────────────────────────────────────────────────
# 领域模型
# ─────────────────────────────────────────────────────────────────────────────
class PlayerAsset(BaseModel):
    """单个球员资产。匹配用 guaranteed 口径（决策③），two-way 按 $0（决策④）。"""

    player_id: str
    player_name: str
    team_abbr: str
    season: str
    salary: int = 0                       # 当前季薪资（美元整数，cap hit 基数）
    guaranteed: int = 0                   # 当前季保障额（匹配用，决策③）
    is_partial: bool = False              # 部分保障（前端 PART 徽标）
    is_two_way: bool = False              # 双向合同（决策④，按 $0 计）
    byc: bool = False                     # Base Year Compensation 标记（v1 钩子，默认 False）
    opt_type: Optional[Literal["team_option", "player_option"]] = None
    salary_by_season: Dict[str, int] = Field(default_factory=dict)        # '2025-26' -> salary
    guaranteed_by_season: Dict[str, int] = Field(default_factory=dict)    # '2025-26' -> guaranteed
    opt_by_season: Dict[str, Optional[str]] = Field(default_factory=dict) # '2025-26' -> opt 或 None

    def is_byc(self) -> bool:
        """该球员是否处于 BYC 状态（先签后换 / 涨幅 >20%）。"""
        return self.byc

    def matching_out_value(self) -> int:
        """送出端计入额：
        - two-way → $0（决策④）
        - BYC     → guaranteed 的 50%（PRD §3.3，决策③统一用 guaranteed）
        - 其他    → guaranteed
        全整数运算（向下取整）。
        """
        if self.is_two_way:
            return 0
        if self.byc:
            return self.guaranteed // 2
        return self.guaranteed

    def matching_in_value(self) -> int:
        """接收端计入额：
        - two-way → $0（决策④）
        - BYC     → guaranteed 的 100%（PRD §3.3）
        - 其他    → guaranteed
        """
        if self.is_two_way:
            return 0
        return self.guaranteed

    def cap_hit(self) -> int:
        """税档 / apron 计算用的 cap hit：
        - two-way → $0（决策④）
        - 其他    → 当前季 salary（cap 基于薪资总额，非保障额）
        """
        return 0 if self.is_two_way else self.salary


class TeamTradeLeg(BaseModel):
    """单队交易腿（多队交易图的节点）。出/入资产、现金、TPE 各自独立。

    校验编排见 ``trade_graph.validate_leg``（保持 schemas 纯净，避免循环依赖）。
    """

    team_abbr: str
    season: str
    outgoing: List[PlayerAsset] = Field(default_factory=list)
    incoming: List[PlayerAsset] = Field(default_factory=list)
    cash_sent: int = 0                    # 本队送出现金（美元整数；>0 在 second apron 禁止）
    tpe_used: int = 0                     # 本队使用的既有 TPE 额度（>0 在 second apron 禁止）
    sign_and_trade: bool = False          # 本腿是否含先签后换（S-TPE）获得球员
    pre_trade_salary: int = 0             # 交易前该队总薪资（税档基准，由 service 从 DB 填入）

    # ── 取值辅助（纯计算，无规则） ──
    def outbound_guaranteed(self) -> int:
        """送出端 guaranteed 计入总额（含 BYC 50% / two-way $0 口径）。"""
        return sum(p.matching_out_value() for p in self.outgoing)

    def inbound_guaranteed(self) -> int:
        """接收端 guaranteed 计入总额（含 BYC 100% / two-way $0 口径）。"""
        return sum(p.matching_in_value() for p in self.incoming)

    def outbound_cap(self) -> int:
        """送出端 cap hit 总额（税档用，two-way $0）。"""
        return sum(p.cap_hit() for p in self.outgoing)

    def inbound_cap(self) -> int:
        """接收端 cap hit 总额（税档用，two-way $0）。"""
        return sum(p.cap_hit() for p in self.incoming)

    def post_trade_salary(self) -> int:
        """交易后该队总薪资（用于 apron / 硬帽判定）。"""
        return self.pre_trade_salary - self.outbound_cap() + self.inbound_cap()

    def partner_teams(self) -> List[str]:
        """本腿对手队（出现在 incoming 来源 / 不在此实现，留作扩展）。"""
        return [p.team_abbr for p in self.incoming]


class TradeProposal(BaseModel):
    """交易提案（API 入参的总装）。legs 中每队一条 TeamTradeLeg。"""

    league: str = "NBA"
    season: str
    as_of: datetime
    legs: List[TeamTradeLeg] = Field(default_factory=list)

    def is_balanced(self) -> bool:
        """资产守恒粗检：每队送出 == 其他队收到（按 player_id 多方账本）。

        用于快速提示明显账本不平（非合规判定）。返回 True 表示账本平衡。
        """
        received: Dict[str, int] = {}
        sent: Dict[str, int] = {}
        for leg in self.legs:
            for p in leg.outgoing:
                sent[p.player_id] = sent.get(p.player_id, 0) + 1
            for p in leg.incoming:
                received[p.player_id] = received.get(p.player_id, 0) + 1
        if set(sent) != set(received):
            return False
        return all(sent[k] == received[k] for k in sent)


# ─────────────────────────────────────────────────────────────────────────────
# 规则常量
# ─────────────────────────────────────────────────────────────────────────────
class LeagueSalaryRules(BaseModel):
    """联盟级薪资规则常量（按 season 从 DB ``league_salary_rules`` 读取，不硬编码）。"""

    season: str
    league: str = "NBA"
    salary_cap: int = 0
    luxury_tax: int = 0
    first_apron: int = 0
    second_apron: int = 0
    minimum_team_salary: int = 0
    mle_non_tax: int = 0
    mle_tax: int = 0
    mle_room: int = 0
    freeze_calendar: Optional[dict] = None
    source_url: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# 结果模型
# ─────────────────────────────────────────────────────────────────────────────
class ValidationIssue(BaseModel):
    """单条校验问题。``amount_delta`` 为正表示缺口（需补足的美元）。"""

    rule_code: RuleCode
    severity: Severity
    message: str
    amount_delta: int = 0


class MatchResult(BaseModel):
    """单队（TeamTradeLeg）的匹配校验结果（逐队独立，决策①）。"""

    team_abbr: str
    season: str
    legal: bool
    issues: List[ValidationIssue] = Field(default_factory=list)
    outbound_guaranteed: int = 0
    inbound_guaranteed: int = 0
    max_inbound_allowed: int = 0
    deficit: int = 0
    tpe_generated: Dict[str, int] = Field(default_factory=dict)  # {team_abbr: amount}


class CapImpact(BaseModel):
    """交易前后税档 / 工资帽影响（TRADE-03）。"""

    team_abbr: str
    payroll_before: int = 0
    payroll_after: int = 0
    tax_status_before: TaxStatus = "BELOW_TAX"
    tax_status_after: TaxStatus = "BELOW_TAX"
    apron_status_before: ApronStatus = "BELOW_FIRST"
    apron_status_after: ApronStatus = "BELOW_FIRST"
    within_second_apron: bool = False


class Suggestion(BaseModel):
    """薪资匹配建议（TRADE-02）：最小改动使某队匹配通过。"""

    team_abbr: str
    add_player_ids: List[str] = Field(default_factory=list)
    remove_player_ids: List[str] = Field(default_factory=list)
    passes: bool = False
    residual_deficit: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# 时间线
# ─────────────────────────────────────────────────────────────────────────────
class PlayerTimeline(BaseModel):
    """球员 6 季薪资时间线（TRADE-08）。"""

    player_id: str
    player_name: str
    team_abbr: str
    season: str
    salaries: Dict[str, int] = Field(default_factory=dict)         # 6 季 salary
    guaranteed: Dict[str, int] = Field(default_factory=dict)       # 6 季 guaranteed
    opts: Dict[str, Optional[str]] = Field(default_factory=dict)   # 6 季 opt 状态
    is_two_way: bool = False
    is_partial: bool = False


class TeamTimeline(BaseModel):
    """球队 6 季薪资时间线（TRADE-09）。"""

    team_abbr: str
    team_name: str
    season: str
    total_salary: Dict[str, int] = Field(default_factory=dict)    # 6 季 total
    total_guaranteed: Dict[str, int] = Field(default_factory=dict)
    tax_status: Dict[str, TaxStatus] = Field(default_factory=dict)
    apron_status: Dict[str, ApronStatus] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# 请求 / 响应（API 层契约）
# ─────────────────────────────────────────────────────────────────────────────
class LegRequest(BaseModel):
    """API 入参：单条交易腿（用 player_id 引用资产，由 service 解析为 PlayerAsset）。"""

    team_abbr: str
    outgoing: List[str] = Field(default_factory=list)   # player_id 列表
    incoming: List[str] = Field(default_factory=list)   # player_id 列表
    cash_sent: int = 0
    tpe_used: int = 0
    sign_and_trade: bool = False


class TradeValidateRequest(BaseModel):
    league: str = "NBA"
    season: str
    as_of: datetime
    legs: List[LegRequest] = Field(default_factory=list)


class TradeSuggestRequest(BaseModel):
    league: str = "NBA"
    season: str
    as_of: datetime
    legs: List[LegRequest] = Field(default_factory=list)


class TradeGenerateRequest(BaseModel):
    league: str = "NBA"
    season: str
    target_player_id: str
    initiator_team: str = ""   # 为空则由引擎推断（目标球员所属队为对手）


class RulesUpsertRequest(BaseModel):
    season: str
    salary_cap: Optional[int] = None
    luxury_tax: Optional[int] = None
    first_apron: Optional[int] = None
    second_apron: Optional[int] = None
    minimum_team_salary: Optional[int] = None
    mle_non_tax: Optional[int] = None
    mle_tax: Optional[int] = None
    mle_room: Optional[int] = None
    freeze_calendar: Optional[dict] = None
    source_url: Optional[str] = None
