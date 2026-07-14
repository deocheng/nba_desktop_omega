# \# NBACore Studio v8 — Closed-Loop Development Contract（强化可控开发闭环版）

# 

# \# 你可以直接复制给 Trae / Codex / Claude 使用。

# 

# \---

# 

# \# 📦 NBACore Studio v8 — Closed-Loop Development Contract

# 

# \---

# 

# \# 0. 系统定义（最终形态）

# 

# \*\*NBACore Studio v8\*\* 是一个：

# 

# > \*\*Metric-Driven Batch Analytics Engine with Strict Closed-Loop Development Control\*\*

# 

# 系统必须保证：

# \- 所有功能必须可执行

# \- 所有模块必须可验证、可测试、可回滚

# \- 所有输出必须 deterministic（相同输入 = 相同输出）

# \- Metric Engine 是唯一计算源头

# \- 严格四层架构，禁止跨层逻辑泄漏

# 

# \---

# 

# \# 1. 🔁 Closed-Loop 开发模型（核心）

# 

# \*\*每个 Phase 必须严格遵循：\*\*

# 

# \*\*PLAN → BUILD → VERIFY → VALIDATE → FIX → LOCK\*\*

# 

# \*\*任何 Phase 未完成全部验证，不允许进入下一阶段。\*\*

# 

# \*\*新增：受控例外机制（Change Request）\*\*

# \- 如需在 LOCK 后修改，必须提交正式 Change Request

# \- 需经过完整回归测试 + 架构评审 + 重新 LOCK

# \- 所有变更必须记录在 `docs/change-log.md`

# 

# \---

# 

# \# 2. 🧱 四层架构（严格锁死）

# 

# \## Layer 1 — Data Layer（不可变）

# \- PostgreSQL NBA Database

# \- \*\*只允许 SELECT + batch query（使用 IN 或临时表）\*\*

# \- 必须带 season / date range filter

# \- 禁止任何 per-player 循环查询

# 

# \*\*验证\*\*：所有 SQL 必须可 trace（通过 query\_id 或 logging）

# 

# \## Layer 2 — Metric Engine（唯一计算层 ⭐）

# 路径：`/backend/services/metric\_engine/`

# 

# 职责：

# \- Metric Registry（所有指标必须注册）

# \- Batch Loader

# \- Matrix Builder

# \- Vectorized Executor（使用 numpy/pandas/polars）

# \- Cache Engine（Redis 或 disk cache）

# \- Rank Engine

# 

# \*\*验证\*\*：

# \- 所有 metric 必须来自 registry

# \- API / Frontend \*\*禁止任何计算逻辑\*\*

# \- 所有计算必须在 engine 内完成

# 

# \## Layer 3 — API Layer（纯编排）

# \- batch fetch data

# \- 调用 metric engine

# \- 返回结构化响应

# \- \*\*禁止 SQL、禁止计算、禁止业务逻辑\*\*

# 

# \## Layer 4 — Frontend Layer（纯渲染）

# \- 只负责调用 API + 渲染 UI + 图表

# \- \*\*禁止任何业务逻辑、计算、聚合、过滤\*\*

# \- 仅允许使用成熟图表库（Recharts / Chart.js / AG-Grid 等）

# 

# \---

# 

# \# 3. 🔁 Phase 执行结构（标准化模板）

# 

# 每个 Phase 必须包含以下部分（严格按顺序）：

# 

# 1\. \*\*PLAN\*\*（设计文档）

# 2\. \*\*BUILD\*\*（代码实现）

# 3\. \*\*VERIFY\*\*（单元测试 + 静态检查）

# 4\. \*\*VALIDATE\*\*（集成测试 + 端到端验证）

# 5\. \*\*FIX\*\*（修复所有问题）

# 6\. \*\*LOCK\*\*（代码冻结 + 文档更新 + git tag）

# 

# \---

# 

# \# 4. 📊 Phase 定义（升级版）

# 

# \## Phase 0 — Environment Bootstrap

# \*\*输出\*\*：Flask/FastAPI server、DB 连接池、配置管理、health check、logging  

# \*\*验证\*\*：`/health` 返回 200 + DB 连通 + server 正常启动

# 

# \## Phase 0.5 — Data Ingestion \& Schema（新增）

# \*\*输出\*\*：

# \- 数据库 Schema（player\_gamelog, player\_bio, team\_info 等）

# \- 数据导入脚本（支持 nba-sql 或官方 API）

# \- 季节/赛季分区策略

# \*\*验证\*\*：能成功导入至少一个完整赛季数据

# 

# \## Phase 1 — Data Layer Validation

# \*\*输出\*\*：batch SQL loader、schema mapping  

# \*\*验证\*\*：单次 batch 查询成功、无 per-player 查询

# 

# \## Phase 2 — Metric Engine Core

# \*\*输出\*\*：

# \- Metric Registry 系统

# \- 基础计算函数（weighted\_sum, ratio, expression parser）

# \- 向量计算管道

# \*\*验证\*\*：注册 → batch 计算 → 输出一致性测试通过

# 

# \## Phase 3 — API Layer

# \*\*输出\*\*：`/players`, `/vs/compare`, `/metrics/evaluate`, `/batch` 等  

# \*\*验证\*\*：无任何计算逻辑，所有指标走 Metric Engine

# 

# \## Phase 4 — Frontend VS System

# \*\*输出\*\*：VS 对比 UI、动态 metric 选择器、图表渲染  

# \*\*验证\*\*：纯 API 驱动，无任何前端计算

# 

# \## Phase 5 — Context System

# \*\*输出\*\*：player context engine、role evolution、usage trend  

# \*\*验证\*\*：全部基于 Metric Engine 输出

# 

# \## Phase 6 — Export \& Offline System

# \*\*输出\*\*：HTML/PDF/JSON 导出、离线缓存  

# \*\*验证\*\*：相同输入导出结果完全一致

# 

# \## Phase 7 — Testing \& Monitoring（新增）

# \*\*输出\*\*：完整测试套件、性能基准、监控仪表盘  

# \*\*验证\*\*：覆盖率 > 85%，所有核心路径通过

# 

# \---

# 

# \# 5. 🧪 Verification System（核心检查清单）

# 

# \*\*每个 Phase 结束前必须通过以下检查：\*\*

# 

# \### 5.1 Layer Leakage Check

# \- API 无计算

# \- Frontend 无逻辑

# \- Metric Engine 是唯一计算点

# 

# \### 5.2 SQL Trace \& Batch Check

# \- 所有查询 batch + 可 trace

# \- 禁止 per-player loop

# 

# \### 5.3 Determinism Check

# \- 相同输入 → 100% 相同输出（含浮点精度控制）

# 

# \### 5.4 Testing Coverage

# \- 单元测试覆盖 Metric Engine 核心函数

# \- 集成测试覆盖主要 API

# \- Snapshot 测试关键输出

# 

# \### 5.5 Runtime Guard（启动时检查）

# \- compute layer validation

# \- query batch enforcement

# \- cross-layer access prevention

# \- loop detection

# 

# \---

# 

# \# 6. ❌ 最终禁止清单（不可违反）

# 

# \- no `eval()` / `exec()`

# \- no dynamic SQL

# \- no per-player DB loop

# \- no frontend computation / aggregation

# \- no cross-layer logic leakage

# \- no mock for Metric Engine 核心逻辑

# \- no skipping verification steps

# \- no untracked Change

# 

# \---

# 

# \# 7. 📦 系统验收标准（v8 完成条件）

# 

# \- 所有 Phase 完成 PLAN→LOCK 闭环

# \- Metric Engine 是单一事实来源

# \- 零跨层逻辑泄漏

# \- 所有输出 deterministic

# \- SQL 完全可追溯

# \- Frontend 纯渲染

# \- 测试覆盖率达标

# \- 支持受控变更流程

# 

# \---

# 

# \# 8. 🧭 一句话系统定义

# 

# \*\*NBACore Studio v8\*\* 是严格遵循闭环控制、指标驱动的 NBA 批处理分析引擎，所有功能必须经过完整 PLAN→BUILD→VERIFY→VALIDATE→FIX→LOCK 流程并通过多维度验证后才能进入生产。

# 

# \---

# 

# \# 9. 🚀 使用说明（给 AI 开发者）

# 

# 你现在不是在“随便写代码”，而是在\*\*严格执行软件制造协议\*\*。

# 

# \- 每次回复前必须声明当前 Phase

# \- 必须按模板输出 PLAN / BUILD / VERIFY 等

# \- 完成一个 Phase 后必须请求我进行 VALIDATE

# \- 只有我确认 LOCK 后才能进入下一 Phase

# 

# \*\*准备好了吗？\*\*

# 

# 请回复：“\*\*Phase 0 启动\*\*”，我们立即开始执行。

# 

# \---

# 

# 🚀 \*\*v8 升级亮点总结\*\*：

# \- 更强的可执行性（标准化模板 + 新 Phase）

# \- 更好的扩展性（Change Request + Phase 7）

# \- 更高的实用性（数据导入、测试、监控完整覆盖）

# 

# 此合同已可直接投入使用。

