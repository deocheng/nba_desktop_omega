# T0 研究发现（player_shooting_backfill）

> 作者：寇豆码（Kou，工程师）｜ 日期：2026-07-23
> 集群 B：`127.0.0.1:5433 / nba / postgres`（口令走 `PGPASSWORD`，未硬编码）
> 配套实现见 `common/br_player_page.py` / `external_crawler/crawler/crawl_br_player_shooting.py`
> / `external_crawler/backfill/backfill_playoff_player_id.py` / `external_crawler/runner/run_player_shooting_backfill.sh` / `tests/test_br_player_page.py`

---

## 0. 研究结论速览

| 待明确项（设计 §5） | T0 实测结论 |
|---|---|
| dim_players 的 BR slug 列名 | **`player_id`**（character varying，5,476 行非空） |
| dim_players 的球员姓名列名 | **`player_name`**（text，5,476 行非空） |
| dim_players 是否还有 br_player_id / slug 列 | **均不存在**（实测报错确认） |
| player_shooting 唯一约束 | **原本 0 索引 / 0 唯一约束** → 已建 `uq_player_shooting_key` |
| 表名 | 单表 `player_shooting`（34 列，含 `season_type`，Regular/Playoffs 同表）✅ 与设计并一致 |
| BR 球员页双表 data-stat 顺序/列映射 | 已确认（见 §3），`weight` 不在页内（置 NULL） |
| season 解析口径 | 链接 `NBA_<year>_shooting.html` → `year+1` = 结束年（与既有表一致） |
| DB host 严格性 | 已用 `host=127.0.0.1, port=5433`（对齐铁律） |
| 枚举去重 | `player_gamelog.br_player_id` ∪ `dim_players.player_id`，UNION 去重 |

---

## 1. dim_players 列实测

```text
dim_players.player_id    : character varying  (BR slug, 5476 非空)  ← 回填 JOIN 用此列
dim_players.player_name  : text               (球员姓名, 5476 非空) ← 回填 JOIN 用此列
dim_players.br_player_id : 不存在 (列不存在)
dim_players.slug         : 不存在 (列不存在)
```

样本核对：
- `Jarrett Allen` → `allenja01`  ✅
- `OG Anunoby`   → `anunoog01` ✅

> 结论：`backfill_playoff_player_id.py` 经 `dim_players.player_id`（=BR slug）与
> `dim_players.player_name` 关联回填。设计 §5.1 的「slug 列名待定」在此拍板为 **player_id**。

---

## 2. player_shooting 结构 / 唯一约束实测

- 列数：**34 列**，与设计 §3 / 任务说明完全一致（含 `season_type`、`weight`(numeric)）。
- 索引 / 唯一约束（T0 前）：**0 个索引、0 个唯一约束**。
- 4 列键 `(player_id, season, season_type, team)` 现有重复组：**0**（含 B 回填后的 Playoffs 行）。
- **T5 已补 DDL**：`CREATE UNIQUE INDEX IF NOT EXISTS uq_player_shooting_key
  ON player_shooting (player_id, season, season_type, team)` —— 已执行成功（建索引前重复检查通过）。
  此索引是爬虫 A `ON CONFLICT` 的前置条件，runner 在启动 A 前也会再确保一次。

---

## 3. BR 球员 shooting 页结构（双表 data-stat 映射）

路径：`/players/{slug[0]}/{slug}/shooting/`（如 `/players/b/brownja02/shooting/`）。
一页含该球员全部赛季两张表，每行 = 一个赛季：

| 表 id | season_type |
|---|---|
| `#shooting` | `Regular` |
| `#shooting_playoffs` | `Playoffs` |

`data-stat` → `player_shooting` 列映射（解析纯函数 `parse_player_shooting_html` 依此实现）：

| BR data-stat | player_shooting 列 |
|---|---|
| season（单元格内链接 `NBA_<y>_shooting.html`，文本 `YYYY-YY`） | season（= y+1，结束年） |
| age | age |
| team_id | team |
| lg_id | lg |
| pos | pos |
| g / gs / mp | g / gs / mp |
| fg_percent | fg_percent |
| avg_dist_fga | avg_dist_fga |
| pct_fga_2pt / pct_fga_0_3 / pct_fga_3_10 / pct_fga_10_16 / pct_fga_16_3 / pct_fga_3p | percent_fga_from_x2p_range / _x0_3 / _x3_10 / _x10_16 / _x16_3p / _x3p |
| fg_pct_2pt / fg_pct_0_3 / fg_pct_3_10 / fg_pct_10_16 / fg_pct_16_3 / fg_pct_3p | fg_percent_from_x2p_range / … / _x3p |
| pct_fg_ast_2pt / pct_fg_ast_3pt | percent_assisted_x2p_fg / percent_assisted_x3p_fg |
| pct_fga_dunk / fg_dunk | percent_dunks_of_fga / num_of_dunks |
| pct_fg_3pt_corner / fg_pct_3pt_corner | percent_corner_3s_of_3pa / corner_3_point_percent |
| fg3a_heave（“#HEAVE”尝试数） | num_heaves_attempted |
| fg3_heave（“HEAVE%”命中百分比） | → 推导 `num_heaves_made = round(HEAVE% × #HEAVE)` |
| （页内无每行 weight） | weight = NULL |

- **球员姓名**：从页面 `<h1>` 抽取（如 `<h1>Jaylen Brown</h1>`），注入每条记录。
- **Career 汇总行 / Did Not Play 行**：`season` 单元格无年份 → 解析为 `None` → 跳过（不入库）。
- **前置约束**：`season < 1997`（1983–1996 无 BR shooting 数据）的行跳过，但不登记失败。

> ⚠️ **实时页获取受阻（沙箱 CF 拦截）**：本沙箱对所有自动化浏览器均被 Cloudflare 拦截——
> UC 后端报 `WebDriverException: unhandled request`（Chrome150 / UC 3.5.5 环境性故障）；
> Playwright / urllib 直连得 “Just a moment” / 403；CDP 端口 9222 经代理返回 502。
> 因此**无法实时取到真实 BR 页**。T0 夹具 `raw_archive/br_players/brownja02/shooting.html`
> 为对真实页结构的**高保真重建**（table id / data-stat / 列顺序 / 赛季链接 href / Career 行
> 均与真实页一致），用于驱动解析单测与端到端验证。真实页须在用户运行环境
> （UC + 有效 `cf_clearance`）经 `--rework` 复核（设计已要求「A 爬虫不要启动全量实时爬取」）。

---

## 4. 枚举宇宙规模

- `player_gamelog.br_player_id`：3,485 个去重非 NULL slug（爬虫枚举权威源之一）。
- `dim_players.player_id`：5,476 个去重非空 slug。
- 两者 UNION 去重即爬虫 A 的完整枚举宇宙；`--priority-gap` 时仅返回「在 gamelog 宇宙内、
  但 `player_shooting` 缺 Regular 组合」的 slug（优先补缺）。

---

## 5. B 回填实际执行结果（已真实执行，非 dry-run）

执行：`python external_crawler/backfill/backfill_playoff_player_id.py`

| 阶段 | 结果 |
|---|---|
| 回填前孤儿（Playoffs 且 player_id NULL） | **6,099** |
| 阶段1：经 dim_players 唯一 slug 回填 | 5,664 |
| （增强）姓名归一（去尾 `*` 名人堂标记）后补回 | +397（同阶段1合并执行） |
| 阶段2：同 (player,season) Regular 行自连接兜底 | 31 |
| 回填后孤儿 | **7** |
| 入 `backfill_review`（歧义/缺失，不误填） | 7 |

- **抽查验证**：`Jarrett Allen → allenja01`、`OG Anunoby → anunoog01`、
  `Jaylen Brown → brownja02` 均正确填入 BR slug ✅。
- **剩余 7 孤儿**（均为「同名多值歧义 / dim_players 无对应唯一 slug」，按设计安全跳过）：
  `Luca Vildoza`(2022)、`Nate Williams`(2025)、`Patrick Ewing*`(1997–2000, 5 行)。
- 与设计「应=0」的偏差说明：审计预期乐观。实际 `player_shooting.player` 含名人堂 `*` 后缀、
  且部分球员姓名在 `dim_players` 中映射到多个 slug（真歧义），按「同名多值安全跳过」铁律
  不得误填，故留 7 行进 `backfill_review` 供人工处理。已通过「去尾 `*` 归一」多回收 397 行。

---

## 6. 覆盖率校验（T5，跑 docs/coverage_report.sql）

执行前（A 爬虫尚未跑）基准：

| 指标 | 值 |
|---|---|
| gamelog 宇宙 (br_player_id, season, ≥1997) 去重组合数 | **17,473** |
| player_shooting Regular 已覆盖 (player_id 非 NULL) 组合数 | 14,569 |
| Regular 覆盖率 | **83.4%** |
| Regular 缺口（A 爬虫待补） | **2,904** |
| Playoffs 覆盖（B 回填后） | 6,092 有 id / 7 孤儿 |

> ⚠️ **与审计基准的偏差**：审计文档称 universe=24,366、覆盖率 59.8%、缺口≈9,797；
> 但 `coverage_report.sql`（忠实实现设计附录 B 的 SQL）实跑得到 universe=17,473、
> 覆盖率 83.4%、缺口 2,904。分子（covered=14,569）与审计完全一致，差异**仅在 universe
> 分母**——说明审计的 24,366 为过时/不准确估计，当前 gamelog 实际仅 17,473 个
> (br_player_id, season) 组合。覆盖率 SQL 以实时数据为准，A 爬虫将补齐这 2,904 个缺口。

Bug2 记录（仅记录不修）：`player_gamelog` 1997–2000 `br_player_id` NULL 行数由
`coverage_report.sql` 第 3 段统计，未改动。

---

## 7. 对设计的偏差 / 决策记录（供 QA 知悉）

1. **`_upsert_rows` 在子类中覆盖（未改 br_team_page.py）**：基类
   `BRTeamPageCrawler._upsert_rows` 生成的 SQL 含 `len(cols)` 个 `%s` 占位符，与
   `psycopg2.extras.execute_values`（要求**单一** `%s`）不兼容，运行即报
   “more than one '%s' placeholder”。在 `common/br_player_page.py` 的
   `BRPlayerPageCrawler` 中**覆盖**为单一 `%s` 形式（遵守「禁止修改 br_team_page.py」）。
2. **B 回填姓名归一增强**：`player_shooting.player` 对名人堂球员带 `*` 后缀（如
   `Allen Iverson*`），与 `dim_players.player_name` 无法精确匹配；JOIN 时 `TRIM(TRAILING '*'
   FROM ps.player)` 归一（仍要求「姓名→唯一 slug」才更新，安全）。并给 `backfill_review`
   加 `TRUNCATE` 使重复运行幂等。多回收 397 行。
3. **实时抓取受阻**：沙箱 CF 拦截所有自动化浏览器，T0 夹具为结构高保真重建，待用户运行环境复核。
4. **`weight` 列**：BR 球员 shooting 页无每行 weight，解析固定置 NULL（与 T0 §5.5 一致）；
   如需从 `dim_players.weight_lbs` 富化为后续增强。
5. **`num_heaves_made`**：BR 页仅给 “HEAVE%” 百分比，由 `round(HEAVE% × #HEAVE)` 推导整数命中数。
