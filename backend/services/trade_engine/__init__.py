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
    cba_aux.py      补充模块：Bird Rights cap hold + Player max % + 多队 League
                    模拟（v8.3.2+ 引入，与 nba_rules.py / tax_engine.py 互补）
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
    cba_aux,  # v8.3.2+ 补充：可独立 CLI 跑；不影响现有计算路径
    cba_aux_db,  # v8.x DB 接入层：cba_aux 域对象从真实 DB 构造
    trade_semantics_db,  # v8 AI 语义解析：trade_semantics 写层（§6 唯一含 SQL）
)
from backend.services.trade_engine.service import TradeService
from backend.services.trade_engine.llm_provider import (  # noqa: E402,F401
    OllamaProvider,
    get_provider,
)

# 暴露 cba_aux 公共类（便于 `from backend.services.trade_engine import cba_aux` 使用）
from backend.services.trade_engine.cba_aux import (  # noqa: E402,F401
    LeagueSimulator,
    Player,
    SalaryCapRules,
    Team,
    TradeSimulator,
)
# cba_aux_db 公共 load 函数（DB 接入层），不影响现有导出
from backend.services.trade_engine.cba_aux_db import (  # noqa: E402,F401
    TradeSemantics,
    analyze_trade_semantics,
    load_league,
    load_player,
    load_salary_rules,
    load_team,
    load_trades,
    parse_trade_semantics,
)
# AI 语义解析写层公共函数（便于 `from backend.services.trade_engine import ...`）
from backend.services.trade_engine.trade_semantics_db import (  # noqa: E402,F401
    delete_trade_semantics,
    ensure_schema,
    exists_source_ref,
    get_trade_semantics,
    upsert_trade_semantics,
)

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
    # v8.3.2+ cba_aux 补充模块
    "cba_aux",
    "LeagueSimulator",
    "Player",
    "SalaryCapRules",
    "Team",
    "TradeSimulator",
    # v8.x cba_aux_db 接入层
    "cba_aux_db",
    "TradeSemantics",
    "load_salary_rules",
    "load_team",
    "load_player",
    "load_trades",
    "load_league",
    "parse_trade_semantics",
    "analyze_trade_semantics",
    # v8 AI 语义解析：provider + 写层
    "OllamaProvider",
    "get_provider",
    "trade_semantics_db",
    "ensure_schema",
    "exists_source_ref",
    "get_trade_semantics",
    "upsert_trade_semantics",
    "delete_trade_semantics",
]
