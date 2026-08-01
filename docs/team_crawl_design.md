# BR 30 队球队页爬取逻辑 — 系统设计与任务分解

> 作者：架构师 Bob（高见远）　|　范围：**仅设计 + 任务分解，不写实现代码**
> 目标：把已验证的 **活塞(DET) 原型** 推广到 **全部 30 队**，并对照现有 DB 结构说明覆盖关系、缺口与范围边界。
> 配套图：`docs/class-diagram.mermaid`、`docs/sequence-diagram.mermaid`

---

## 0. 结论先行（给 team-lead 汇报用）

1. **两套包已具备 30 队能力，直接复用，不重写。**
   `transactions_crawl/`（commit 510e07c + 77f6d07）与 `hof_exec/`（commit a42e8b3）的 fetch / parse / load / validate / CLI 均已就绪，且 `transactions_crawl/parse.py` **已经内置了 30 队 `TEAM_FULL_NAME` 字典** —— "手工写死 Detroit Pistons" 的泛化问题在代码层面**事实上已解决**，只是该字典目前是 `parse.py` 内部的**局部副本**（单点重复风险，见 §3/§8）。
2. **真正待建的工作只有 4 块**：①单一来源的队名/slug 模块 `common/team_names.py`；②统一编排器 `crawl_team_pages.py`；③30 队离线回归；④运行手册/断点续爬。
3. **不改任何表结构。** 现有唯一约束直接复用：`transactions(tx_date,abbr,desc)`、`team_hof(tx_abbr,season,player)`、`team_executives(tx_abbr,rk)`。孪生去重 + `ON CONFLICT` upsert 已能覆盖旧拼接 bug。
4. **范围边界清晰**：仅 `transactions` + `HOF` + `executives`。教练/选秀/退役号码/球员/全明星等其它 BR 分区属不同管线，**OUT OF SCOPE**（见 §8）。

---

## 1. 实现方案 + 框架选型

### 1.1 复用确认
- 复用 `transactions_crawl`（交易页，多年倒序）与 `hof_exec`（HOF + 高管页，单页）两套已验证包。
- 两者均已支持 `--all-teams`、`--offline-dir` 双模（离线文件 / 在线 UC Chrome），并内置 `_is_cf_challenge` + `looks_like_404` 跳过逻辑。

### 1.2 是否需要统一编排器？ → **建议新建 `crawl_team_pages.py`**
| 方案 | 说明 | 评价 |
|---|---|---|
| A. 两条独立 `--all-teams` 命令 | `python -m transactions_crawl --all-teams --all-years` + `python -m hof_exec --all-teams --kind both` | 可行，但 CF 拦截下需手动跑两次、断点/日志分散、易遗漏某队 |
| B. **统一编排器 `crawl_team_pages.py`（推荐）** | 一个入口对 30 队依次跑 交易(多年倒序) + HOF + 高管，复用两包的 fetch/parse/load，统一断点续爬与进度统计 | **一次命令跑齐三类数据；CF 中断可续；单点进度/日志** |

**结论**：选 B。编排器**不重新实现**抓取/解析/落库，只组合调用两包的公开函数（`fetch_*` / `parse_*` / `upsert_*`），把"30 队 × 多年 × 3 类"的循环与续爬逻辑收口到一处。

### 1.3 框架与技术栈（沿用，不引入新框架）
- **解析**：BeautifulSoup4（`html.parser`，零外部依赖；`lxml` 可选提速）
- **落库**：psycopg2（`hof_exec.config.get_conn()`，口令走 `.env` 的 `DB_PASSWORD`，绝不硬编码）
- **在线抓取**：undetected-chromedriver（UC Chrome，过 Cloudflare；warm-up + retry）
- **架构模式**：分层 `fetch → parse(纯函数,源无关) → load(幂等 upsert)` + 顶层 `orchestrate`。解析器对离线/在线同一份 HTML 共用，符合"源无关"约定。

---

## 2. 文件列表（已有 vs 建议新增）

### 2.1 已有（已验证、DONE、本次不改动）
```
transactions_crawl/
  __init__.py  config.py  fetch.py  parse.py  load.py  validate.py  __main__.py
hof_exec/
  __init__.py  config.py  fetch.py  parse.py  load.py  validate.py  __main__.py
common/
  bridge_constants.py        # _CANON(30)、get_pg_conn()、PG_DSN(口令来自 env)
det2026_br/                  # DET 离线样本 + raw 缓存目录（在线抓取也落此）
docs/run_live_crawl.md       # 现有在线运行手册（T05 扩展）
```

### 2.2 建议新增 / 修改
```
common/
  team_names.py              # [新增] 单一来源：TEAM_FULL_NAME(30) + BR_TEAM_SLUGS(30) + get_*()
  __init__.py                # [改] 导出 team_names
tests/
  test_team_names.py         # [新增] 全名/slug 单测 + 对 dim_teams 校验
  test_team_pages_offline.py # [新增] 30 队离线回归（多队 gold 对比 + 拼接 bug 守卫）
scripts/
  verify_team_names_db.py    # [新增] 启动时校验 TEAM_FULL_NAME vs dim_teams.team_name
crawl_team_pages.py          # [新增] 统一编排器（30 队 × 交易(倒序) + HOF + 高管）
run_br_team_pages.sh         # [新增] 编排器便捷启动脚本（含 .env 加载）
crawl_state.json             # [新增,运行时生成] 断点续爬状态（完成 abbr 清单）
docs/
  team_crawl_design.md       # [新增,本文件] 设计 + 任务分解
  class-diagram.mermaid      # [新增] 类图
  sequence-diagram.mermaid   # [新增] 时序图
```

---

## 3. 数据结构与接口（表映射）

### 3.1 BR 数据类型 → 目标表 映射表
| BR 数据类型 | 源页面 (slug 来自 BR_TEAM_SLUGS) | 解析器 | 目标表 | 唯一约束 | 现有覆盖/备注 |
|---|---|---|---|---|---|
| 球队交易 Transactions | `/teams/{slug}/{year}_transactions.html` | `parse_transactions` | `transactions` | `(transaction_date, team_abbr, description)` | 18547 行；**孪生去重**修复旧拼接 bug（`TheDetroit Pistonssigned...`） |
| 名人堂 HoF | `/teams/{slug}/hof.html` | `parse_hof_div`（`div#div_leaderboard`，`leaderboard_number-<season>` 块） | `team_hof` | `(team_abbr, season, player_name)` | 118 行（DET 占 118） |
| 高管 Executives | `/teams/{slug}/executives.html` | `parse_executives_table`（含注释块 `<table>`、跳重复表头） | `team_executives` | `(team_abbr, rk)` | 22 行（DET 占 22） |

> 三张目标表的列结构**不变**，落库仅靠 `INSERT ... ON CONFLICT` / 孪生 `UPDATE`，**无 DDL 变更**。

### 3.2 共享参考（被三个爬虫共用）
| 参考源 | 提供 | 实测说明（重要修正） |
|---|---|---|
| `dim_teams` (36 行) | `{abbr → 队全名}` 的**校验基准** | 实际列：`id, team_abbr, current_code, team_name, is_active, created_at`。**全名在 `team_name` 列，不是 `full_name`**（`full_name` 只存在于 `dim_players`）。 |
| `team_mapping` (VIEW) | 同 `dim_teams` | `SELECT id, team_abbr AS team_code, current_code, team_name, is_active, created_at FROM dim_teams;` 无额外列。 |
| `hof_exec.config.BR_TEAM_SLUGS` | `{abbr → BR slug}` | **DB 无 slug 列**（↔ `current_code` 是另一概念）。slug 是**代码唯一来源**，不可查表获得。 |
| `common/team_names.py`（新增） | `TEAM_FULL_NAME(30)` + `BR_TEAM_SLUGS(30)` 单一来源 | **代码固化 30 队**，离线可测、无运行时 DB 依赖；并在测试/脚本中交叉校验 `TEAM_FULL_NAME` 与 `dim_teams.team_name`。 |

### 3.3 全名解析器接口设计（新增 `common/team_names.py`）
```python
# 单一来源：30 队全名 + 30 队 BR slug
TEAM_ABBRS:     list[str]          # 同 common.bridge_constants._CANON（30）
TEAM_FULL_NAME: dict[str, str]     # abbr -> "Detroit Pistons" 等（校验基准 = dim_teams.team_name）
BR_TEAM_SLUGS:  dict[str, str]     # abbr -> slug (BKN->BRK, CHA->CHO, 其余恒等)

def get_full_name(abbr: str) -> str:   # transactions 前缀重建用
def get_br_slug(abbr: str) -> str:     # URL 构造用
```
- **选择"代码固化"而非"运行时查 dim_teams"**（理由见 §8-Q2）：避免离线/测试依赖 DB、避免 CF 高压下再开连接；且 `slug` 本就不在 DB 中，只能代码固化。
- 固化值须与 `dim_teams.team_name`（30 个现役 abbr）逐一对齐，由 `tests/test_team_names.py` + `scripts/verify_team_names_db.py` 保证。

### 3.4 类图（细节）
见 `docs/class-diagram.mermaid`。要点：
- `TeamNames`（新增）向 `TransactionsCrawler` 提供全名（前缀重建）、向 `HofExecCrawler` 提供 slug（URL 构造）；并依赖 `DimTeams` 做全名校验。
- `TeamPageOrchestrator`（新增）**组合** `TransactionsCrawler` 与 `HofExecCrawler`，复用 `DbConn` 连接约定。

---

## 4. 程序调用流程（时序图）

见 `docs/sequence-diagram.mermaid`。要点：
1. **外层循环 30 队**（`TEAM_ABBRS`）。
2. **单队三爬**：
   - A. Transactions：多年**倒序** `range(year_end, year_start-1, -1)`（默认 2026→1947）；`fetch → (离线文件 | UC Chrome 在线) → parse(前缀重建+拼接修复+多动作切分) → 孪生去重 upsert（命中旧坏行则 UPDATE 修复，否则 INSERT ON CONFLICT）`。
   - B. HoF：单页 `hof.html → parse_hof_div → upsert_hof (ON CONFLICT tx_abbr,season,player)`。
   - C. Executives：单页 `executives.html → parse_executives_table（注释块表格+跳重复表头）→ upsert_executives (ON CONFLICT tx_abbr,rk)`。
3. **CF / 404 跳过**：`_is_cf_challenge` / `looks_like_404` 命中即 `SKIP`（记日志，**不中断整轮**），在线抓取会把 raw HTML 缓存到 `det2026_br/` 以便续跑。
4. **断点续爬**：编排器写 `crawl_state.json`（已完成 abbr 清单）；叠加"DB upsert 幂等 + raw HTML 缓存"双保险 —— 二次运行自动跳过已完成项。

---

## 5. 任务列表（有序、含依赖、≤5 个任务）

> 已 DONE（不复做）：`transactions_crawl/*`、`hof_exec/*`、`common/bridge_constants.py`、`hof_exec/config.py`（TEAM_ABBRS / BR_TEAM_SLUGS / get_conn / load_dotenv）。

| Task | 名称 | 源文件（新建/修改） | 依赖 | 优先级 |
|---|---|---|---|---|
| **T01** | 建 `common/team_names.py` 单一来源（全名+slug）并校验 `dim_teams` | `common/team_names.py`(新)、`tests/test_team_names.py`(新)、`scripts/verify_team_names_db.py`(新) | — | P0 |
| **T02** | 解析器/配置接入 `common` 来源（去硬编码） | `transactions_crawl/parse.py`(改:删本地 TEAM_FULL_NAME,改 import)、`hof_exec/config.py`(改:从 common 导入并重导出 BR_TEAM_SLUGS)、`common/__init__.py`(改:导出 team_names) | T01 | P1 |
| **T03** | 建统一编排器 `crawl_team_pages.py` | `crawl_team_pages.py`(新)、`run_br_team_pages.sh`(新)、`docs/run_live_crawl.md`(改:补编排器用法) | T01 | P0 |
| **T04** | 30 队离线回归 + 孪生去重校验 | `tests/test_team_pages_offline.py`(新)、`det2026_br/`(扩:≥1 支非 DET 样本+gold)、`transactions_crawl/validate.py`(改/扩:支持多队 gold) | T02, T03 | P1 |
| **T05** | Mac 在线全量倒序跑 + 运行手册定稿 | `docs/run_live_crawl.md`(定稿)、`run_br_team_pages.sh`(定稿)、`crawl_state.json`(新:续爬状态/看门狗文档) | T03 | P2 |

**依赖图**：`T01 → T02 → T04`；`T01 → T03 → {T04, T05}`。（5 个任务内闭环，无过长链式依赖。）

---

## 6. 依赖包列表
```
beautifulsoup4          # 解析 (bs4)；已装于 .venv，建议补入依赖声明
undetected-chromedriver # 在线过 CF；已装于 .venv，建议补入依赖声明
psycopg2-binary==2.9.10 # 落库 (requirements.txt 已有)
lxml                    # 可选：BS4 的更快解析器后端
pytest==8.3.4           # 回归测试 (requirements.txt 已有)
```
> 注：`bs4` 与 `undetected-chromedriver` 当前在 `.venv` 中可用但未写入 `requirements.txt`；T03/T04 应把二者补入依赖声明（不改现有代码逻辑）。

---

## 7. 共享知识（跨文件约定）
- **30 队常量唯一来源**：`common.bridge_constants._CANON`（abbr 集合）；`BR_TEAM_SLUGS` 与 `TEAM_FULL_NAME` 统一收敛到新增的 `common/team_names.py`。
- **ABBR ↔ slug ↔ 全名 单一映射**：slug/全名全在 `common/team_names.py`；DB 仅作**校验**（`dim_teams.team_name`），不作运行时取数。
- **拼接 bug 修复约定**：所有 `<li>` 一律 `get_text(" ", strip=True)`；前缀 `"The {TEAM_FULL_NAME[abbr]} "` 逐字复现 gold；单 `<li>` 多动作按动词（`Signed/Traded/Waived/...`）切分。
- **孪生去重 upsert 约定**：`transactions` 先 `SELECT ... REPLACE(desc,' ','')=...` 找孪生坏行 → `UPDATE` 修复；否则 `INSERT ... ON CONFLICT(tx_date,abbr,desc) DO UPDATE`。`team_hof`/`team_executives` 用 `ON CONFLICT` 刷新。
- **唯一约束清单**（落库幂等依据）：`transactions(tx_date,abbr,desc)`、`team_hof(tx_abbr,season,player)`、`team_executives(tx_abbr,rk)`。
- **离线/在线双模约定**：`offline_dir` 给定 → 读本地文件；否则 UC Chrome 在线，并把 raw HTML 缓存到 `det2026_br/`。CF/404 一律 SKIP 不中断。
- **口令约定**：`DB_PASSWORD` 仅来自 `.env` → `os.environ`；`get_conn()` 单点出口，绝不硬编码。
- **年份倒序约定**：`range(year_end, year_start-1, -1)`，默认 `year_end=2026, year_start=1947`。

---

## 8. 待明确事项（OPEN QUESTIONS — 需用户确认范围后再进入实现）

- **Q1 范围**：仅 `transactions + HOF + executives`？还是把 `coaches`（/teams/{slug}/coaches.html，与 executives 同属 front-office 分区）、`draft`、`retired_numbers`、`players`、`all_star`、`leaders` 等其它 BR 球队页分区也纳入？**建议 v1 仅三者**；其余为独立管线/工作流，单列（现有 `crawl_br_team_pages.py` 虽列了 11 个 DET 页，但那是原始 HTML 转储器，非结构化落库，与本逻辑解耦）。
- **Q2 全名来源（代码固化 vs 查 DB）**：**建议代码固化**（`common/team_names.py`），并在测试中对齐 `dim_teams.team_name`。理由：① `slug` 本就不在 DB（只能代码固化）；② 离线/测试无需 DB；③ CF 高压下少开连接。注意：DB 实际列名是 `team_name` 而非 `full_name`。
- **Q3 全量年份起点**：默认 `1947`（完整历史）还是推荐 `2000`（首轮实用）？CF 压力差异巨大。**建议首轮 `--year-start 2000`，`1947` 作为可选完整档**。
- **Q4 CF 命中策略**：在线连跑 30 队 × 多年必遇 CF。建议**跳过并继续**（已抓取的队靠 upsert+缓存续跑），而非整轮失败。是否需要在编排器内做"CF 退避+指数重试/换 UA"的增强？
- **Q5 续爬机制**：默认复用"raw HTML 缓存 + DB upsert 幂等"双保险即可；是否要显式 `crawl_state.json` 进度文件（T03/T05 已规划，可裁剪）？
- **Q6 Schema 变更**：本设计**零 DDL 变更**（仅复用现有唯一约束）。若用户希望给 `transactions` 增加 `transaction_type` 索引或给 HOF 补 `br_slug` 回填，请单独提。

---

## 9. 附录：与原始简报的偏差纠正（基于实测代码/库）
1. **"手工写死 Detroit Pistons" 已解决**：`transactions_crawl/parse.py` 现有 `TEAM_FULL_NAME` 已含全部 30 队；剩余问题是该字典为**局部副本**，需收敛到 `common/team_names.py`（T01/T02）。
2. **`dim_teams` 无 `full_name` 列**：全名在 `team_name`；`full_name` 仅 `dim_players` 有。`team_mapping` 是 `dim_teams` 的视图，无额外列。
3. **DB 无 BR slug 列**：`current_code` 是另一概念；slug 唯一来源是代码 `hof_exec.config.BR_TEAM_SLUGS`（→ 迁至 `common/team_names.py`）。
4. **`crawl_br_team_pages.py` 是原始 HTML 转储器**（写 raw + CSV + all.json），非结构化落库，与本次 `transactions_crawl`/`hof_exec` 逻辑解耦，v1 不纳入。
5. **`bs4` / `undetected-chromedriver` 未入 `requirements.txt`**：仅装于 `.venv`，需在依赖声明中补回（不影响设计）。
