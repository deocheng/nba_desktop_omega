"""NBACore v8 — Trade Engine (Layer 2 compute).

NBA 交易模拟器（v1）核心计算引擎。严格四层隔离：
    Frontend → API(编排) → Engine(本包) → Data(只读 batch_query)

本包全部为纯 Python 整数运算（金额统一 BIGINT 美元整数），不依赖任何
前端计算、不做网络请求。规则常量从 DB ``league_salary_rules`` 读取，不硬编码。

子模块：
    schemas.py      数据/结果 Pydantic 模型
    constants.py    赛季解析、two-way 识别、规则加载
    db.py           数据接入层（只读 batch_query + 专用写连接池）
    rules.py        可插拔规则引擎接口（ABC + 注册表）
    nba_rules.py    NBA 规则实现（SalaryRuleSet）
    match_engine.py 逐队薪资匹配核心（band 分档 / deficit）
    trade_graph.py  多队交易图 + 逐队校验编排
    tax_engine.py   税档/工资帽影响（CapImpact）
    suggester.py    匹配建议 + 方案生成
    timeline.py     球员/球队薪资时间线
    service.py      门面：validate/suggest/generate/timeline/rules
"""
from __future__ import annotations

from backend.services.trade_engine import (
    constants,
    db,
    match_engine,
    nba_rules,  # 触发 NBARuleSet 注册（TRADE-06 可插拔）
    rules,
    schemas,
    service,
    suggester,
    tax_engine,
    timeline,
    trade_graph,
)
from backend.services.trade_engine.service import TradeService

__all__ = [
    "TradeService",
    "constants",
    "db",
    "match_engine",
    "nba_rules",
    "rules",
    "schemas",
    "service",
    "suggester",
    "tax_engine",
    "timeline",
    "trade_graph",
]
