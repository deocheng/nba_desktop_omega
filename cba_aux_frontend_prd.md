# cba_aux 前端可视化 · 简单 PRD

> 产品名：`cba_aux_frontend` ｜ 产出人：产品经理 许清楚（software-product-manager）
> 日期：2026-07-12 ｜ 语言：中文 ｜ 类型：简单 PRD（前端可视化）
> 关联模块：NBACore Studio v8 · `backend/services/trade_engine/cba_aux.py`（计算核心）+ `cba_aux_db.py`（DB 只读适配层）· 前端原生 JS

---

## 0. 调研结论（代码现状，只读）

### 0.1 后端引擎位置（与任务描述有偏差，需注意）
| 任务描述 | 实际情况 |
| --- | --- |
| `backend/engines/cba_aux/` | `backend/services/trade_engine/cba_aux.py`（计算核心） + `backend/services/trade_engine/cba_aux_db.py`（DB 只读适配层） |

- 已确认 `backend/services/trade_engine/__init__.py` **追加**导出了 `LeagueSimulator / Player / SalaryCapRules / Team / TradeSimulator` 以及 `cba_aux_db` 的 `load_*` 函数，**未删除任何既有导出**（符合"只追加"的描述）。
- 任务称"纯 stdlib、零 DB 依赖"：计算核心 `cba_aux.py` 确实零 SQL/零 DB；但另有 `cba_aux_db.py` 薄适配层从真实 DB 构造域对象。前端可视化应走 `cba_aux_db`（真实数据），计算仍下沉到 `cba_aux.py`。

### 0.2 对外导出 API（签名）
| 类 / 函数 | 关键方法 / 签名 | 返回 | 用途 |
| --- | --- | --- | --- |
| `SalaryCapRules` | `base_cap=168_000_000, luxury_tax_line, first_apron, second_apron, min_team_salary`（后 4 项缺省自动推导） | dataclass | 赛季薪资规则常量 |
| `Player` | `name, salary, yos=0, is_all_nba=False, contract_years_left=1, bird_rights_with_team` | dataclass | 球员 + Bird 归属 |
| `Player.get_max_salary_pct()` | 无参 | `0.25 / 0.30 / 0.35` | 顶薪占比（yos≥10 且 All-NBA→0.35；All-NBA→0.30；其余→0.25） |
| `Team` | `name`；`roster{name→Player}, cap_holds, is_repeat_luxury_payer` | class | 球队容器 |
| `Team.get_cap_hold(player)` | 入参 Player | `int(salary×1.50/1.25/1.20)` | Bird Rights cap hold（yos≥3→1.50x；≥2→1.25x；其余→1.20x） |
| `Team.total_salary()` | 无参 | `int` | roster 薪资之和 |
| `Team.add_player / renounce_bird_rights / to_dict / from_dict` | — | — | 增删与序列化 |
| `TradeSimulator` | `can_trade(team, rules, outgoing, incoming)` / `execute_trade(team_a, team_b, players_a_to_b, players_b_to_a, rules)` | `(bool,str)` / `bool` | 两支/多队交易校验与执行 |
| `LeagueSimulator` | `add_team(team)` / `season_summary()` / `save_league(path)` / `load_league(path)` | 无 / 无 / 无 / 实例 | 多队模拟 + JSON 持久化 |

### 0.3 DB 只读适配层 `cba_aux_db.py`（多队数据来源已解决）
| 函数 | 返回 | 数据源 |
| --- | --- | --- |
| `load_salary_rules(season='2025-26')` | `SalaryCapRules` | `league_salary_rules`（DB 权威，不用公式推） |
| `load_player(team_abbr, player_name, season)` | `Optional[Player]` | `player_contracts`（salary 取 season 对应列；`yos=max(0,age-19)`；`is_all_nba=False`） |
| `load_team(team_abbr, season)` | `Team`（附 `.payroll`） | `player_contracts` + `team_payroll` |
| `load_trades(team_abbr, season, include_semantics)` | `List[TradeRecord]` | `transactions`（仅 `Traded`） |
| `load_league(season='2025-26')` | `LeagueSimulator`（30 队） | `team_payroll` 全联盟 |

> 结论：**多队数据从哪来已解决** —— `load_league(season)` 直接从 `team_payroll` 构造 30 队 `LeagueSimulator`，前端无需手工造数。

### 0.4 API Router 现状
- `backend/api/routers/__init__.py` 现有 24 个 router（analytics_builder/batch/career/charts/clutch*/context/crawler/data_import/draft/export/games/intelligence/leaderboard/metrics/monitor/players/system/teams/trade/tactics/video_library/vs/workspace），**无 cba / cba_aux**。
- `backend/app.py` 通过 `app.include_router(X.router)` 挂载，router 自带 prefix（如 trade 用 `prefix="/trade"`）。
- 结论：需**新增 `routers/cba_aux.py`**（建议 `prefix="/cba"`），并在 `routers/__init__.py` 与 `app.py` 注册。

### 0.5 前端现状（原生 JS，非 React）
- `frontend/index.html`：侧栏 `nav-item`（带 `data-page` + `onclick="nav('X')"`）+ 主区 `<div id="page-X" class="page">`；底部 `<script src="js/components/*.js">` 引入各组件。
- `frontend/js/app.js`：全局 `nav(page)` 切换页面（toggle `.active`）；每页一个 `loadXPage()`，内部调用 `window.X.render('rootId')`；全局 `api(path)` 负责 fetch + 错误处理。
- 组件模式：IIFE 挂 `window.Trade` / `window.AnalyticsBuilder` 等，暴露 `render(containerId)`；**纯渲染，零业务计算**；图表用 ECharts（CDN）；`trade.js` 中 `fmtMoney()` 仅做 `int→$X.XM` 展示格式化（属展示层，非业务计算）。
- 结论：新增页面需 3 处最小改动（index.html 加 nav-item + page div + script 标签；app.js 加 nav 分支 + `loadCbaPage()`；新建 `components/cba.js`），**不引入 React/Vite**。

### 0.6 发现的关键风险（直接影响 PRD 范围）
- **R1 · `is_all_nba` 恒为 False**：`cba_aux_db.load_player` 强制 `is_all_nba=False`（DB 无该字段）→ 真实数据下 `get_max_salary_pct()` **恒返回 0.25**，30%/35% 档不会触发。Player Max 占比功能需决策（见 Q2）。
- **R2 · `yos` 启发式**：`yos=max(0, age-19)` 非真实资历 → Bird cap hold 与 Max% 都受其影响，UI 须标注数据可信度。
- **R3 · `season_summary()` 仅打印**：无结构化返回 → 多队汇总可视化需引擎层新增结构化方法（如 `snapshot()`）或 router 仅做编排 + 调用引擎结构化方法（计算必须留在引擎层，见 Q4）。
- **R4 · 多队数据已就绪**：`load_league(season)` 已构造 30 队，无需前端造数（利好 P1）。

---

## 1. 产品定义

### 1.1 产品目标
1. 把 cba_aux 已完成的 CBA 规则计算（Bird Rights cap hold / Player Max 占比 / 薪资规则常量）以可交互前端页面呈现，让老程无需跑 CLI 即可查看与核对。
2. 提供 League Simulator 的多队选择 + 模拟 + 围裙/奢侈税状态对比，沉淀为可视化情景分析工具。
3. 支持结果导出/分享，形成可复用的 CBA 情景。

### 1.2 用户故事（5 条）
- 作为球队薪资分析师（老程），我希望在页面选择某队并查看每位球员的 **Bird Rights cap hold 系数与金额**，以便快速判断帽上空间占用。
- 作为薪资分析师，我希望查看某球员的 **顶薪占比（25/30/35%）及其判定依据**（yos / All-NBA），以便评估续约上限。
- 作为分析师，我希望查看全联盟 30 队的 **薪资总额与围裙/奢侈税状态汇总**，以便横向对比。
- 作为分析师，我希望**选择若干队进行模拟**（如调整阵容/交易）并立即看到状态变化，以便做情景分析。
- 作为分析师，我希望把模拟结果**导出为 JSON 或生成可分享内容**，以便留存与协作。

---

## 2. 技术规范

### 2.1 需求池

**P0（必须）— Bird Rights / Cap Hold / Player Max 展示**
- **P0-1 Bird Rights Cap Hold 展示**：按球员展示系数（Full Bird 1.50x / Early Bird 1.25x / Non-Bird 1.20x）与计算金额（= `salary × 系数`）；团队级可汇总 `cap_holds`。
- **P0-2 Player Max 薪资占比展示**：展示 `get_max_salary_pct()`（25/30/35%）+ 判定依据（yos、is_all_nba）。需处理 `is_all_nba` 未接入问题（见 Q2）。
- **P0-3 薪资规则常量页**：展示 `cap / luxury_tax_line / first_apron / second_apron / min_team_salary`（来自 `load_salary_rules`）。

**P1（应当）— League Simulator 交互模拟**
- **P1-1 多队选择 + 模拟触发**：选队 → 调 `LeagueSimulator`/`TradeSimulator` → 返回逐队 `total_salary` 与状态（健康 / 第一围裙 / 第二围裙 / 奢侈税）。
- **P1-2 多队汇总可视化**：30 队（或所选队）薪资柱状图 + luxury/apron 阈值线（ECharts），按状态着色。
- **P1-3 交易执行模拟（纳入 P1 可选）**：两支/多队 `TradeSimulator.execute_trade` 前后状态对比。

**P2（可选）— 结果持久化与分享**
- **P2-1 结果导出**：JSON 下载（前端由 API 响应生成 blob，零后端写）。
- **P2-2 结果分享/存档**：服务端存档返回 share id（可选，需评估 §6 写路径）；或仅前端本地保存。
- **P2-3 情景保存/载入**：与 `save_league / load_league` 对齐（服务端文件系统）。

### 2.2 建议新增 API 端点（无现存 router，需新建 `/cba`）
> 约束：router 仅编排，**计算在 cba_aux、DB 读取经 cba_aux_db（零 SQL 子串）**，响应统一 `{code, data, message}` 信封（同 trade router）。

| 方法 & 路径 | 调用 | 说明 |
| --- | --- | --- |
| `GET /cba/rules?season=2025-26` | `load_salary_rules` | 薪资规则常量 |
| `GET /cba/team/{team_abbr}?season=` | `load_team` + `get_cap_hold` + `get_max_salary_pct` + `total_salary` | 该队逐人 `{salary, yos, bird_factor, cap_hold, max_pct, basis}` + 团队总额 + 状态 |
| `GET /cba/player/{team_abbr}/{player_name}?season=` | `load_player` + 上述方法 | 单人 max_pct + cap_hold + 判定依据 |
| `GET /cba/league/summary?season=` | `load_league` + 引擎 `snapshot()`（见 Q4） | 逐队 `{total_salary, status}` 结构化数据 |
| `POST /cba/league/simulate` | `LeagueSimulator`/`TradeSimulator` | 选队 + 操作，返回模拟后状态（P1） |
| `GET /cba/league/export?season=` | `LeagueSimulator.to_dict` | 当前 league JSON（P2） |

### 2.3 UI 设计稿

**页面布局**
- 侧栏新增 `nav-item`「CBA 规则 · cba_aux」，`data-page="cba"`。
- 主区 `page-cba`：顶部 `page-header`（赛季选择 + Tabs：① 规则常量 ② 球队/Bird&Max ③ 联盟模拟）。
- **Tab① 规则常量**：5 个 `stat-card` 展示 cap / luxury / first_apron / second_apron / min_team_salary。
- **Tab② 球队视图**：球队下拉 → 球员表（列：球员 / 薪资 / yos / Bird 系数 / Cap Hold 金额 / Max% / 判定依据）；底部团队总额 + 状态徽标；`is_all_nba`/`yos` 近似在表头/脚注显式标注（可信度）。
- **Tab③ 联盟模拟**：多队勾选 → 「模拟」按钮 → ECharts 柱状（各队 `total_salary`，叠加 luxury/apron 阈值线 `markLine`，按状态着色）+ 状态表；「导出 JSON」。

**核心组件（`frontend/js/components/cba.js`）**
- `window.Cba.render(containerId)`：渲染骨架 + 绑定事件（遵循 trade.js 的 IIFE 模式）。
- 子渲染：`renderRules / renderTeam / renderLeague`；表格复用现有 `.tbl` / `.card` 样式。
- 图表：`echarts.init` + `setOption`（阈值线用 `markLine`，状态着色用 THEME 常量）。
- 复用全局：`api()`、`escapeHtml()`、`toast()`、`fmtMoney()`（仅展示格式化）。

**数据流（严格 §6 四层）**
```
前端 cba.js (L4 纯渲染)
   │ api()  GET/POST /cba/*
   ▼
/cba router (L3 纯编排：校验入参 + 调引擎 + 塑形信封)
   │
   ├─► cba_aux_db (L2 只读适配：DB→域对象，零 SQL 子串)
   └─► cba_aux.py (L2 计算：cap_hold / max_pct / total_salary / 状态判定)
   │
   ▼
DB (L1，经 trade_engine.db 封装)
```
> 前端零业务计算：仅 `fmtMoney(int→$X.XM)` 等展示格式化；阈值与状态判定一律在引擎层。

### 2.4 关键架构约束（务必遵守）
- **§6 四层隔离**：Frontend(L4) 纯渲染；API router(L3) 纯编排（无 SQL / 无计算）；Engine(L2: `cba_aux.py` 计算 + `cba_aux_db.py` 只读)；Data(L1: `trade_engine.db`)。新增 `/cba` router 不得含 SQL 子串或薪资计算。
- **前端沿用现有原生 JS 组件模式**（IIFE + `window.Cba.render`），**不引入 React/Vite**（无强理由）；图表复用已有 ECharts（CDN）。
- 默认技术栈（Vite+React+MUI+Tailwind）**仅作参考**，本项目前端已是原生 JS，遵循现状。
- 金额统一 `int`（美元整数），前端格式化展示；`is_all_nba` / `yos` 近似必须在 UI 显式标注。

---

## 3. 待确认问题（Open Questions）

- **Q1 路径偏差**：任务写 `backend/engines/cba_aux/`，实际在 `backend/services/trade_engine/cba_aux.py`（+ `cba_aux_db.py`）。是否以实际位置为准？
- **Q2 `is_all_nba` 恒 False（关键）**：真实数据下 Max% 恒 0.25。方案建议：(a) 前端提供手动开关覆盖 `is_all_nba`；(b) 用 age/yos 启发式近似；(c) UI 标注"未接入，按 25% 显示"。推荐 **(a)+(c)**，需确认。
- **Q3 `yos` 启发式**：`age-19` 非真实资历，Bird/Max 数据需标注可信度？是否在 UI 显示"估算"徽标？
- **Q4 结构化快照**：`season_summary()` 仅打印。是否允许在引擎加一个无破坏的 `LeagueSimulator.snapshot()` 返回逐队 `{total_salary, status}` 结构化数据（供 `/cba/league/summary`）？还是偏好 router 内仅编排、判定逻辑另置？
- **Q5 router 命名/挂载**：新增 `routers/cba_aux.py`，prefix 用 `/cba` 还是 `/cba-aux`？需同步改 `routers/__init__.py` 与 `app.py`。
- **Q6 赛季对齐**：`cba_aux_db` 默认 `'2025-26'`，前端 `seasonSelect` 用 `2025`。默认赛季与可选范围以哪个为准（建议统一 `2025-26`）？
- **Q7 持久化/分享**：P2 的"分享"用前端下载 JSON（简单、零改动）还是服务端存档返回 id（需写路径，§6 需评估）？
- **Q8 引擎小改范围**：除 `snapshot()` 外，`get_cap_hold` / `get_max_salary_pct` 已有现成方法，P0 展示是否完全够用？是否同意在引擎层集中状态判定（避免 router 计算）？

---

*调研方法：仅使用只读工具（Glob / Read / Grep）核对 `cba_aux.py`、`cba_aux_db.py`、`__init__.py`、现有 router（trade.py）与前端（index.html / app.js / components/trade.js）。未编写任何实现代码。*
