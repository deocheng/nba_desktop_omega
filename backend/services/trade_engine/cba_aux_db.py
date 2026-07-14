"""NBACore v8 — cba_aux 的 DB 接入层（薄适配层）。

定位
----
本模块把数据库里的真实数据（薪资规则 / 球员合同 / 球队薪资表 / 交易记录）
映射为 ``cba_aux`` 的域对象（``SalaryCapRules`` / ``Player`` / ``Team`` /
``LeagueSimulator``），让 cba_aux 不再只能手工写示例。

合规约束（v8 §6）
------------------
- **零 SQL 子串 / 零数据库驱动**：本文件不含任何 SQL 语句，也不 import
  psycopg2；全部读取经 ``backend.services.trade_engine.db`` 封装函数，全部写入
  经 ``backend.services.trade_engine.trade_semantics_db`` 写层（唯一含 SQL 的模块）。
- **LLM 优先 + 正则兜底**：``parse_trade_semantics`` 先走 LLM provider，任何失败
  回退正则（旧版行为），永不抛错、``raw_text`` 必保留。
- **不 import 任何 router**（`backend.api.*`），不依赖网络（LLM 调用封装在 provider 内）。
- **不用 eval/exec**。

已知近似（标注）
----------------
- ``Player.yos`` 用启发式 ``max(0, age - 19)``（NBA 入行约 19 岁），非真实资历。
- ``Player.is_all_nba``：DB 无此字段，统一置 ``False``（已知近似）。
- 交易 ``counterparties`` 现由 LLM 优先产出、正则兜底；描述多用全名
  （如 "Orlando Magic"），正则用「全名 -> 缩写」映射 + 3 字母缩写兜底。

使用
----
    from backend.services.trade_engine.cba_aux_db import (
        load_salary_rules, load_player, load_team, load_trades, load_league,
    )
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from backend.services.trade_engine import cba_aux, constants, db
from backend.services.trade_engine.llm_provider import get_provider
from backend.services.trade_engine import trade_semantics_db
from backend.services.trade_engine.cba_aux import (
    LeagueSimulator,
    Player,
    SalaryCapRules,
    Team,
)

DEFAULT_SEASON = "2025-26"


# ====================== TradeSemantics（AI 语义扩展点） ======================
@dataclass
class TradeSemantics:
    """AI 语义解析层对自由文本交易描述应产出的结构化结果。

    字段:
        counterparties: 交易对手方球队缩写列表（LLM 优先，正则兜底）
        players_out:    送出球员名单（AI 填充）
        players_in:     换入球员名单（AI 填充）
        picks:          涉及选秀权列表（AI 填充）
        cash:           现金对价（float；可空）
        notes:          残余 / 未归类细节描述
        raw_text:       源 description 回显，便于溯源与再解析
    """

    counterparties: List[str] = field(default_factory=list)
    players_out: List[str] = field(default_factory=list)
    players_in: List[str] = field(default_factory=list)
    picks: List[str] = field(default_factory=list)
    cash: Optional[float] = None
    notes: str = ""
    raw_text: str = ""


# ====================== TradeRecord ======================
@dataclass
class TradeRecord:
    """一条交易记录的轻量载体（不做球员级解析）。

    字段:
        date:            交易日期（ISO 字符串）
        team_abbr:       发起/关联球队缩写
        description:     原始自由文本描述（原样保留）
        counterparties:  从 description 抽出的已知球队缩写列表（白名单命中）
        semantics:       可选；AI 语义解析结果（include_semantics=True 时附上）
    """

    date: str
    team_abbr: str
    description: str
    counterparties: List[str] = field(default_factory=list)
    semantics: Optional[TradeSemantics] = None


# ====================== 白名单 / 抽取 ======================
def _team_directory() -> Dict[str, str]:
    """构建 {小写全名: abbr} ∪ {abbr: abbr} 白名单映射（来自 team_payroll）。"""
    mapping: Dict[str, str] = {}
    for r in db.get_team_directory():
        abbr = str(r.get("team_abbr") or "")
        if abbr:
            mapping[abbr] = abbr
        name = r.get("team_name")
        if name:
            mapping[str(name).lower()] = abbr
    return mapping


def _extract_counterparties(description: str, whitelist: Dict[str, str]) -> List[str]:
    """从交易描述抽取已知球队缩写（白名单命中；正则兜底，非球员级 NLP）。"""
    found: set = set()
    if not description:
        return []
    low = description.lower()
    for name, abbr in whitelist.items():
        if len(name) <= 3:
            continue  # 缩写条目交给下方正则分支
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            found.add(abbr)
    for tok in re.findall(r"\b[A-Z]{3}\b", description or ""):
        if tok in whitelist:
            found.add(whitelist[tok])
    return sorted(found)


def parse_trade_semantics(text: str, team_abbr: str | None = None) -> TradeSemantics:
    """从自由文本交易描述解析结构化语义（LLM 优先 + 正则兜底）。

    策略（满足 R2 / D3，非破坏）：
        1) 先用 provider（默认 Ollama）做语义抽取，填充全部 7 字段。
        2) 若 provider 任何失败（网络/超时/JSON/字段异常），整体回退正则
           抽取 counterparties（旧版行为），其余字段留空，raw_text 保留。
        函数永不抛错。

    Args:
        text:       原始自由文本交易描述
        team_abbr:  可选关联球队缩写（作为 hint 传给 LLM）

    Returns:
        TradeSemantics: 含 raw_text 回显的结构化结果（LLM 或正则产出）
    """
    raw = text or ""
    try:
        provider = get_provider()
        d = provider.parse_trade(raw, team_abbr)
        # 校验/清洗：counterparties 若空则回退正则
        cps = d.get("counterparties") or _extract_counterparties(raw, _team_directory())
        return TradeSemantics(
            counterparties=sorted(set(cps)),
            players_out=d.get("players_out") or [],
            players_in=d.get("players_in") or [],
            picks=d.get("picks") or [],
            cash=d.get("cash"),
            notes=d.get("notes") or "",
            raw_text=raw,
        )
    except Exception:   # LLM 任何失败 -> 正则兜底，非破坏
        return TradeSemantics(
            counterparties=_extract_counterparties(raw, _team_directory()),
            raw_text=raw,
        )


# ====================== 5 个 load_* 函数 ======================
def load_salary_rules(season: str = DEFAULT_SEASON) -> SalaryCapRules:
    """从 league_salary_rules 构造 SalaryCapRules（DB 权威，不用公式推）。"""
    rules = db.load_rules(season)
    if rules is None:
        return SalaryCapRules(base_cap=0)
    scr = SalaryCapRules(base_cap=int(rules.salary_cap or 0))
    scr.luxury_tax_line = int(rules.luxury_tax or 0)
    scr.first_apron = int(rules.first_apron or 0)
    scr.second_apron = int(rules.second_apron or 0)
    scr.min_team_salary = int(rules.minimum_team_salary or 0)
    return scr


def _row_to_player(row: dict, season: str, is_all_nba: bool = False) -> Player:
    """player_contracts 原始行 -> cba_aux.Player。

    Args:
        is_all_nba: 由调用方透传（默认 False）。DB 无真实 All-NBA 字段，
            此处仅作覆盖入口，不伪造数据（U5 / R1 已知近似）。
    """
    col = constants.salary_column(season)
    salary = int(row.get(col) or 0)
    age = int(row.get("age") or 0)
    yos = max(0, age - 19)
    return Player(
        name=str(row.get("player_name") or ""),
        salary=salary,
        yos=yos,
        is_all_nba=bool(is_all_nba),
    )


def load_player(
    team_abbr: str,
    player_name: str,
    season: str = DEFAULT_SEASON,
    is_all_nba: bool = False,
) -> Optional[Player]:
    """从 player_contracts 取指定球员 -> Player（命中则非空）。

    Args:
        is_all_nba: 透传参数（默认 False，非破坏），命中后覆盖 Player.is_all_nba。
    """
    rows = db.get_team_player_rows([team_abbr], season)
    for r in rows:
        if str(r.get("player_name") or "") == player_name:
            return _row_to_player(r, season, is_all_nba=is_all_nba)
    return None


def load_team(
    team_abbr: str,
    season: str = DEFAULT_SEASON,
    is_all_nba: bool = False,
) -> Team:
    """建 Team(team_abbr)，逐个 add_player，并以 team_payroll.total 设 payroll。

    Args:
        is_all_nba: 透传参数（默认 False，非破坏），命中后覆盖每位 Player.is_all_nba。
    """
    team = Team(team_abbr)
    rows = db.get_team_player_rows([team_abbr], season)
    for r in rows:
        team.add_player(_row_to_player(r, season, is_all_nba=is_all_nba))

    payrolls = db.load_team_payrolls([team_abbr], season)
    if team_abbr in payrolls:
        total = int(payrolls[team_abbr]["totals"].get(season) or 0)
        team.payroll = total
    return team


def load_trades(
    team_abbr: Optional[str] = None,
    season: Optional[str] = None,
    include_semantics: bool = False,
) -> List[TradeRecord]:
    """读取交易记录 -> TradeRecord 列表（含 counterparties 抽取）。

    Args:
        team_abbr: 可选球队缩写过滤（走 db.get_trades 的 %s 参数）。
        season: 保留参数（transactions 表无 season 列，仅 API 对称，不用于过滤）。
        include_semantics: 为 True 时给每条记录附上 TradeSemantics（AI 语义扩展点）；
            默认 False，行为与旧版完全一致（非破坏）。

    注：counterparties 为白名单级抽取，非球员级 NLP。
    """
    whitelist = _team_directory()
    raw = db.get_trades(team_abbr)
    out: List[TradeRecord] = []
    for r in raw:
        desc = str(r.get("description") or "")
        cps = _extract_counterparties(desc, whitelist)
        rec = TradeRecord(
            date=str(r.get("transaction_date") or ""),
            team_abbr=str(r.get("team_abbr") or ""),
            description=desc,
            counterparties=cps,
        )
        if include_semantics:
            rec.semantics = parse_trade_semantics(desc, rec.team_abbr)
        out.append(rec)
    return out


def load_league(season: str = DEFAULT_SEASON) -> LeagueSimulator:
    """遍历 team_payroll 的 30 支球队 -> 逐个 load_team -> LeagueSimulator。"""
    sim = LeagueSimulator()
    for r in db.get_team_directory():
        abbr = str(r.get("team_abbr") or "")
        if not abbr:
            continue
        sim.add_team(load_team(abbr, season))
    return sim


# ====================== AI 批量预解析（§6 写层落表） ======================
def _sem_to_dict(sem: "TradeSemantics") -> dict:
    """TradeSemantics -> 写层 data dict（cash 转 float 或 None）。"""
    cash = sem.cash
    if cash is not None:
        try:
            cash = float(cash)
        except (TypeError, ValueError):
            cash = None
    return {
        "counterparties": list(sem.counterparties or []),
        "players_out": list(sem.players_out or []),
        "players_in": list(sem.players_in or []),
        "picks": list(sem.picks or []),
        "cash": cash,
        "notes": sem.notes or "",
    }


def analyze_trade_semantics(
    season: str | None = None,
    force: bool = False,
    throttle: float = 0.15,
) -> dict:
    """批量预解析 904 条 Traded 交易并落 trade_semantics 表（续跑 + 节流）。

    行为：
        - 读 ``db.get_trades(None)`` 全部 Traded 记录。
        - 续跑：``force=False`` 且 ``source_ref`` 已存在则跳过（幂等）。
        - 节流：每条之间 ``time.sleep(throttle)`` 防 Ollama 过载。
        - 每条经 ``parse_trade_semantics``（LLM 优先 + 正则兜底），结果
          经 ``trade_semantics_db.upsert_trade_semantics`` 落表。

    Args:
        season: 保留参数（transactions 表无 season 列；API 对称），当前忽略。
        force:  True 时忽略已存在记录，全量重跑。
        throttle: 每条之间的节流间隔（秒），0 表示不节流。

    Returns:
        dict: {total, parsed, skipped, failed}
    """
    provider = get_provider()
    rows = db.get_trades(None)   # 904 条 Traded
    total = len(rows)
    parsed = skipped = failed = 0
    for r in rows:
        ref = str(r.get("id"))
        if (not force) and trade_semantics_db.exists_source_ref(ref):
            skipped += 1
            continue
        try:
            sem = parse_trade_semantics(
                str(r.get("description") or ""),
                str(r.get("team_abbr") or ""),
            )
            trade_semantics_db.upsert_trade_semantics(
                ref, _sem_to_dict(sem), provider.__class__.__name__
            )
            parsed += 1
        except Exception:   # 单行失败不中断整体；计入 failed
            failed += 1
        if throttle:
            time.sleep(throttle)
    return {"total": total, "parsed": parsed, "skipped": skipped, "failed": failed}
