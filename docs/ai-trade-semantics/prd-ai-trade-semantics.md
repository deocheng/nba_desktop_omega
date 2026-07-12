# NBACore Studio v8 — AI 交易语义解析 PRD（简单模式）

> 文档类型：简单 PRD（默认模式，不含竞品分析 / 市场象限图）
> 作者：许清楚 / Xu（产品经理）
> 关联模块：`backend/services/trade_engine/cba_aux_db.py`
> 对应扩展点：`TradeSemantics` dataclass / `parse_trade_semantics()` / `load_trades(include_semantics=True)`
> 版本：v1.0（初稿，待确认问题见 §5）

---

## 1. 项目信息

| 项 | 内容 |
|---|---|
| Language | 简体中文 |
| Programming Language | Python 3.11+（cba_aux 模块仅 stdlib：`urllib` + `json`，零新依赖；P2 前端可视化另用 React） |
| Project Name | `ai_trade_semantics` |
| 原始需求复述 | 在 `cba_aux_db.py` 的 `parse_trade_semantics` 扩展点接入本地 Ollama（默认 LLM provider），对 `transactions` 表中 904 条 `type='Traded'` 的自由文本做语义抽取，填充 `players_out` / `players_in` / `picks` / `cash` / `notes`（counterparties 也由 LLM 产出、正则兜底/校验）；并提供批量预解析能力，将结果落独立新表 `trade_semantics`，不污染源表。 |

---

## 2. 产品目标

**一句话**：以本地私有 Ollama 为默认 LLM provider，对 NBA 交易自由文本做语义结构化抽取，并将 904 条 Traded 描述批量预解析落独立表，全程数据不出网。

**说明**：`cba_aux_db.py` 已为「交易自由文本语义解析」预留 AI 扩展点，当前 `parse_trade_semantics` 仅用正则填 `counterparties`，其余字段留空（docstring 标注 `TODO(AI)`）。本需求将本地 LLM 真正接入，对 904 条 Traded 描述做语义抽取以覆盖全部 `TradeSemantics` 字段；采用 **LLM 优先 + 正则兜底** 的非破坏策略（失败/超时零中断），并用标准库 `urllib` 零新依赖调用本机 Ollama（`http://localhost:11434`，默认模型 `qwen3.5-16k`）。批量解析结果写入独立 `trade_semantics` 表，源 `transactions` 原表零变更，同时满足 §6 四层隔离（cba_aux 纯 stdlib / 零 DB import，所有 SQL 收口写层）。

**正交目标（3 条）**：

| 目标 | 说明 |
|---|---|
| G1 数据私有与合规 | 默认本地 LLM 优先，交易文本不出网；provider、地址、模型可配置，满足私有化部署。 |
| G2 语义质量提升 | 以 LLM 替代正则做语义抽取，覆盖全部 7 个 `TradeSemantics` 字段，提升结构化覆盖率与准确率。 |
| G3 非破坏与可扩展 | 接入不改源表与现有默认行为；provider 可插拔；LLM 不可达自动回退正则，功能零中断。 |

---

## 3. 用户故事

1. **作为分析员**，我希望交易描述被自动解析为结构化字段（对手方 / 送出球员 / 换入球员 / 选秀权 / 现金），以便按球员、选秀权、现金对价筛选与统计交易。
2. **作为开发者**，我希望 LLM 不可达或超时时自动回退正则，保证功能不中断且 `raw_text` 保留可追溯。
3. **作为数据工程师**，我希望 904 条 Traded 描述可批量预解析落独立表，并支持续跑与重跑幂等，以便离线构建语义索引而不污染源表。
4. **作为合规 / 运维**，我希望所有 SQL 收口在写层、Ollama 地址与模型可配（env），以便私有化部署与审计。
5. **作为产品负责人**，我希望未来可无改代码切换 provider（如 OpenAI），以便按需升级语义能力。

---

## 4. 需求池（P0 / P1 / P2）

| 编号 | 优先级 | 需求 | 说明 / 约束 | 验收关联 |
|---|---|---|---|---|
| R1 | **P0** | 可插拔 LLM Provider 接口 | 定义 `LLMProvider` 抽象（如 `parse(text, team_abbr) -> dict`），Ollama 为默认实现；预留 OpenAI 等扩展点。接口位于 cba_aux 内，零新依赖。 | AC1, AC5 |
| R2 | **P0** | `parse_trade_semantics` 改为 LLM 优先 + 正则兜底 | 非破坏性：LLM 成功填全部字段；失败/超时/JSON 异常时回退正则填 `counterparties`，其余字段空但 `raw_text` 保留。默认 `include_semantics` 行为不变。 | AC1, AC2 |
| R3 | **P0** | 零依赖调用 Ollama | 用 `urllib` + `json` 调 `http://localhost:11434/api/generate`（或 `/api/chat`），模型/地址可配置（env：`LLM_PROVIDER` / `OLLAMA_BASE_URL` / `OLLAMA_MODEL`）。不引入 `requests`。 | AC5 |
| R4 | **P0** | 批量 `analyze_trade_semantics()` 落独立新表 | 904 条 Traded 解析结果落 `trade_semantics` 表（字段：`counterparties` / `players_out` / `players_in` / `picks` / `cash` / `notes` 的 jsonb + `model` + `parsed_at` + 源行引用），源 `transactions` 不变。 | AC3 |
| R5 | **P0** | 所有 SQL 收口写层（§6 合规） | 新增 AI 层与独立表读写均经写层；路由层禁 SQL，保持 cba_aux 纯 stdlib / 零 DB import（四层隔离）。 | AC4 |
| R6 | P1 | 批量可续跑 | 按 trade id + model 去重，跳过已解析；中断后可重跑不重复解析，幂等。 | AC3 |
| R7 | P1 | 节流防 Ollama 过载 | 批量调用加并发 / 速率限制与简单重试退避（如固定间隔或指数退避）。 | — |
| R8 | P1 | 解析质量日志 + 抽样人工核对 | 记录解析成功率、回退次数、字段覆盖率；导出抽样结果供人工核对。 | — |
| R9 | P2 | 前端可视化交易语义 | 在 analytics-builder 展示单笔 / 批量交易语义结构。 | — |
| R10 | P2 | 多 provider 路由 | 按可用性 / 成本 / 质量路由不同 provider（如本地优先、云端兜底）。 | — |
| R11 | P2 | 置信度评分 | LLM 输出附带字段级置信度，辅助筛选与人工核对。 | — |

---

## 5. 待确认问题（需用户 / 架构师拍板）

1. **默认模型是否锁定 `qwen3.5-16k`？** 建议默认锁定但允许 env 覆盖；需确认是否接受其他 9.7B qwen 系模型作为备选。
2. **批量默认行为？** `analyze_trade_semantics()` 默认全量跑 904 条，还是按需 / 按条件触发？首次是否自动跑？
3. **独立表是否版本化 model？** 同一条交易用不同 model 多次解析时，是覆盖还是共存（多条记录）？`parsed_at` 如何用于「最新」判定？
4. **正则的角色：兜底填充器 vs 校验器？** LLM 产出 `counterparties` 与正则不一致时，是静默以 LLM 为准，还是标记 / 告警供核对？
5. **JSON 字段结构规范？** `picks`（如含 year / round / team）、`cash`（币种 / 单位）、`notes` 的 schema 是否需在 PRD 阶段与架构师对齐，还是交由实现定义？

---

## 6. 验收标准（可量化）

- **AC1（字段全覆盖）**：LLM 返回的 JSON 能被解析并映射到 `TradeSemantics` 全部 7 字段（含 `raw_text` 回显）；字段类型符合 dataclass（`cash` 为 float、列表字段为 list 等）。
- **AC2（回退不中断）**：Ollama 不可达（停服 / 错误 `OLLAMA_BASE_URL`）或超时 / JSON 异常时，自动回退正则，解析不抛异常，`raw_text` 等于源 `description`；回退率可观测记录。
- **AC3（批量幂等落表）**：904 条 `type='Traded'` 全部落 `trade_semantics`，源 `transactions` 行数与字段零变更；重跑幂等（已解析跳过或覆盖，表行数稳定），可续跑跳过已完成。
- **AC4（无回归）**：cba_aux 现有 **77** 个测试全部通过，无回归；新增 provider / 解析逻辑具备单测（mock Ollama，不依赖真实服务）。
- **AC5（零新依赖 + 可配置）**：仅用 stdlib（`urllib` / `json`），无新第三方依赖；`LLM_PROVIDER` / `OLLAMA_BASE_URL` / `OLLAMA_MODEL` 三个 env 生效并可切换默认 provider。

---

*说明：本 PRD 仅定义产品目标、用户故事、需求分级、待确认问题与验收标准；具体接口签名、表 DDL、调用时序与兜底算法交由架构师在技术方案中设计。*
