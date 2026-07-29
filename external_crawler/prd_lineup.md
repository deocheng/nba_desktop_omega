# PRD — BR 球员 lineup 全量爬取（br_player_lineup）

> 内部数据基础设施项目，非面向终端用户的产品。目标：爬取 basketball-reference 球员级 lineup 页（per-player per-year），抓取该球员该季参与过的 5 人阵容组及出场时间/效率统计，落库至 `nba`（postgres @127.0.0.1:5433, public 模式）。本项目是项目记忆中「Lineups 全阵容完全缺失」的新数据域补全。
> 范围策略：**先小子集验证管线，再扩到全量**（已拍板）。

## 0. 项目信息

- **Language**：中文
- **Programming Language**：Python（复用现有 `external_crawler` + `common` 爬虫框架；非前端项目，不涉及 Vite/React）
- **Project Name**：`br_player_lineup_crawl`
- **原始需求复述**：爬取 BR 球员 lineup 全量数据。URL = `/players/{letter}/{slug}/lineups/{year}`（per-player per-year，year=赛季结束年，如 2014=2013-14 赛季）。先对少量球员/少量赛季跑通「抓取→解析→落库→校验」验证管线，再扩到全部球员 × 1997–2026。

---

## 1. 铁律（必须遵守）

> ⚠️ **`player_gamelog.br_player_id` 字段 corrupt**——含大量 phantom/错误 slug（如 Donovan Mitchell 的 gamelog 同时挂在 `mitchdi01`(错误) 和 `mitchdo01`(正确) 下）。用它当球员宇宙会导致爬虫全 404。
>
> **lineup 爬取的球员宇宙禁用 `player_gamelog.br_player_id`**，必须用可靠源：
> 1. `player_shooting` 表 `player_id` 列（text，BR slug，已验证为正确 slug 全集）；
> 2. 联盟页 `/leagues/NBA_{season}_per_game.html` 的球员名单。

---

## 2. 产品目标

**一句话目标**：把 BR 球员级 lineup 数据（每球员每赛季的 5 人阵容组 + 出场时间/效率）全量抓取并规范落库，填补平台 Lineups 数据域的球员维度缺口，使下游可做球员视角的阵容搭配与影响力分析。

**可量化成功标准**：
1. 小子集验证管线（P0）跑通：对 ≤5 个球员 × ≤3 个赛季完成「抓取→解析→落库→校验」，解析字段与 BR 页面一致、落库无孤儿键。
2. 全量（P1）覆盖 player_shooting 可靠 slug 宇宙 × 1997–2026 全赛季，落库 (slug, season) 覆盖率 ≥ 99%（缺失页有明确处理策略并记录于 `crawl_failures`）。
3. lineup 数据提供可被分析查询直接 JOIN 的实体键（player_id / season / season_type），与现有 `player_shooting` / `dim_players` 可关联，无孤立数据。

## 3. 数据消费场景（用户故事）

| # | 数据消费场景 |
|---|---|
| 1 | 作为数据分析师，我希望查询任意球员任意赛季参与过的全部 5 人阵容组及其在场时间/净胜分，以便评估该球员在不同阵容搭配下的表现与适配性。 |
| 2 | 作为数据分析师，我希望以球员为中心聚合其历年阵容搭档，以便发现「与某球员搭档效率最高/最低的 4 人组合」，做球员兼容性分析。 |
| 3 | 作为数据分析师，我希望把球员级 lineup 与现有 `team_lineups`（队级）交叉，以便校验队级阵容数据完整性、并做球员-球队双向的阵容一致性核对。 |
| 4 | 作为数据工程师，我希望 lineup 数据按 (player_id, season, season_type, lineup_key) 幂等落库、可断点续跑，以便全量长跑中断后能从断点恢复、不丢不重。 |

## 4. 需求池（按优先级 P0 → P2）

> 落库表名为**建议名**，最终由架构师设计；命名风格参考现有 `team_lineups` / `player_shooting`（snake_case + 实体描述）。字段集为基于 `team_lineups` 类比 + 任务描述的**提案**，须用样例 HTML 确认（见 §6 P0 依赖）。

| 优先级 | 编号 | 范围 | 内容 | 验收标准 |
|---|---|---|---|---|
| **P0** | L0 | 小子集验证管线 | 对 ≤5 个球员 × ≤3 个赛季（含 antetgi01/2014）跑通完整管线：CDP Chrome 抓取 → 原始 HTML 归档 → 解析 → 落库 → 校验。**前置依赖：样例 HTML 已就绪**（`raw_archive/br_players/antetgi01/lineups_2014.html`）。 | 解析器对样例页字段零误差；落库行数与 BR 页面阵容数一致；实体键可 JOIN `dim_players`/`player_shooting`；CF/限速/断点续跑机制在子集上验证可用。 |
| **P1** | L1 | 全量回填 | 扩展到 player_shooting 可靠 slug 宇宙 × 1997–2026 全赛季，按 (slug, year) 迭代。落库新表（建议 `player_lineups`）。 | (slug, season) 覆盖率 ≥ 99%；缺失页（404/无数据）记录于 `crawl_failures`；幂等可重放；支持 `--resume` 断点续跑。 |
| **P2** | L2 | Playoffs 覆盖 | 若 BR 球员 lineup 页同时提供 Regular + Playoffs 两表（类比 shooting 页 `#shooting` / `#shooting_playoffs`），则一并抓取并按 `season_type` 区分落库。 | Playoffs 行按 season_type='Playoffs' 入库；与 Regular 不混淆；无 Playoffs 数据的赛季干净跳过。 |

**关键范围标注**：
- P0 是 P1 的前置门禁：P0 验证解析器正确性 + 管线可用性后，P1 才能开跑全量。
- lineup 数据粒度 = 每球员 × 每赛季 × 每 5 人阵容组一行（lineup_key 为 5 个 br_player_id 排序后 `|` 连接，无序去重，对齐 `team_lineups.lineup_key` 约定）。
- **DB schema 由架构师设计**，PRD 只提需求：要哪些字段、粒度、与 `player_shooting`/`dim_players` 如何关联。

### 建议字段集（提案，待样例 HTML 确认）

基于 `team_lineups` 类比，球员级 lineup 行建议含：
- **维度键**：`player_id`（text，BR slug，主球员）、`season`（int，结束年）、`season_type`（'Regular'/'Playoffs'）、`lineup_key`（5 slug 排序 `|` 连接）
- **5 人组合**：`br_player_id1..5`（text，FK→dim_players.player_id）、`player_name1..5`（text）
- **出场**：`gp`（出场数）、`mp`/`minutes`（总分钟）
- **胜负**：`won`、`lost`
- **效率**：`pts`、`opp_pts`、`off_rtg`、`def_rtg`、`net_rtg`
- **溯源**：`source`（默认 'basketball-reference'）、`created_at`

> ⚠️ 球员级 lineup 页的**实际表结构与列名**可能与队级不同，必须以样例 HTML 为准。本字段集仅作架构师设计参考。

## 5. 关键约束

1. **slug 宇宙**：禁用 `player_gamelog.br_player_id`（见 §1 铁律）。用 `player_shooting.player_id`（2861 个可靠 slug，已覆盖 1997–2026）∪ 联盟页 `/leagues/NBA_{season}_per_game.html` 名单。
2. **URL 模型**：`/players/{letter}/{slug}/lineups/{year}`，**per-player per-year**（year=赛季结束年）。需按 (slug, year) 二维迭代——这与现有 `BRPlayerPageCrawler` 的「一页含全赛季、按 slug 一维迭代」模型不同，主循环需扩展为 (slug, year) 迭代。
3. **CF 反爬 + 限速**：basketball-reference.com 有 Cloudflare，沙箱过不了 CF；真实爬取须在**用户 Mac** 上用 CDP Chrome（9222，已过 CF）跑，`BROWSER_BACKEND=cdp`。限速 ≤15 请求/分。全量是数万页的长跑，需 resume / 断点续跑 / CF 中途过期处理。
4. **解析器硬前置**：沙箱过不了 CF，工程师写解析器需要**一个 lineup 页样例 HTML**。用户须存到 `raw_archive/br_players/antetgi01/lineups_2014.html`（Antetokounmpo 2013-14）。**P0 的硬依赖**，未就绪则 P0 无法启动。
5. **DB schema**：lineup 数据需新表（5 人组 + 出场时间/效率），由架构师设计。PRD 只提需求（字段、粒度、与 `player_shooting`/`dim_players` 关联方式）。球员键桥接复用现有 `dim_players.player_id`（BR slug）。

## 6. 现有资产（探查发现）

### 6.1 可复用框架

| 资产 | 路径 | 可复用点 | 需扩展/改造 |
|---|---|---|---|
| 球员页爬虫基类 | `common/br_player_page.py` (`BRPlayerPageCrawler`) | CF 握手门禁、≤15/min 限速、`_player_done` 断点续跑、`_quarantine_slug` 404 隔离、`_upsert_rows`(execute_values+ON CONFLICT)、`rework_from_archive` 免爬重放、`save_raw_html` 归档 | **URL 模型不同**：基类 `build_url(slug)` 单页全赛季；lineup 需 `build_url(slug, year)` per-year。**迭代模型不同**：基类 `run_players` 按 slug 一维迭代；lineup 需 (slug, year) 二维迭代。需重写 `build_url` / `_crawl_player` / `run_players` / `save_raw_html` / `_player_done`（按 (slug,year) 判定已落库）。 |
| 球队页爬虫基类 | `common/br_team_page.py` (`BRTeamPageCrawler`) | `extract_player_links`（5 人组合抽取）、`safe_int`/`safe_float`、`_row_data_stats`、`build_arg_parser`/`dispatch_cli`、CF 检测/upsert/失败登记 | 直接复用工具函数，无需改。 |
| 浏览器/CF 模块 | `common/browser.py` | `ensure_cf_cleared`（CF 握手门禁）、`createTarget` 重试 | 直接复用。 |
| auto 编排层 | `external_crawler/runner/run_player_shooting_auto.sh` | ensure_chrome(CDP 9222 自动起独立实例)、prompt_cf、缺口重算循环、verify_coverage 守门、Chrome 挂了自动重启 + cookie 过期 `--resume` 续跑、安全上限防死循环 | **作为模板**新建 `run_player_lineup_auto.sh`；缺口 SQL 改为 lineup 维度（按 (slug, season) 而非 slug）。 |
| 队级 lineup 解析器 | `external_crawler/crawler/crawl_br_team_lineups.py` (`parse_team_lineups_html`) | 解析 table `id=lineups`/`lineups_po`、5 人组合抽取、字段 gp/mp/won/lost/pts/opp_pts/off_rtg/def_rtg/net_rtg、`lineup_key` 排序去重 | **解析逻辑可借鉴**，但球员级 lineup 页表 id/列名可能不同，须以样例 HTML 为准重写。 |

### 6.2 DB 现状

| 表 | 状态 | 说明 |
|---|---|---|
| `team_lineups` | **已存在，0 行**（队级，未填充） | 队级 5 人阵容：5×br_player_id(FK→dim_players) + 5×player_id(bigint) + 5×player_name + gp/minutes/won/lost/pts/opp_pts/off_rtg/def_rtg/net_rtg。lineup_key=5 slug 排序 `\|` 连接。**球员级 lineup 需新建表**（建议 `player_lineups`），不与队级混用。 |
| `starting_lineups` | 已存在 | 场级首发 5 人，与本项目无关。 |
| `player_shooting` | 已存在，已填充 | `player_id`(text, BR slug) 为**可靠 slug 源**：2861 distinct slug，14,569 distinct (slug, season) Regular 组合，赛季 1997–2026。 |
| `dim_players` | 已存在 | `player_id`(text, BR slug) 5,476 个，是 `team_lineups.br_player_id*` 的 FK 目标。可作为球员键桥接源（候选 universe，但 PRD 指定优先 player_shooting + 联盟页）。 |
| `crawl_failures` | 已存在 | id/game_id/task_type/created_at/resolved——失败登记复用。 |
| **球员级 lineup 表** | **不存在** | 需架构师新建（建议 `player_lineups`）。 |

### 6.3 规模预估

- player_shooting 可靠 (slug, season) Regular 组合 = **14,569**（全量 floor 估算）。
- 联盟页名单 union 后预计 ~15k–25k 个 (slug, year) 页面。
- 限速 ≤15 请求/分 = 900 请求/小时：15k 页 ≈ 17 小时纯请求时间；含 CF 暂停/限速间隙，**全量预计 1–3 天长跑**。
- → resume / 断点续跑 / CF 中途过期处理为 P1 必备（非可选）。

## 7. 待确认问题（给用户的开放问题）

1. **字段集确认**：球员级 lineup 页实际含哪些列？建议字段集（§4）是否够用？是否含 BR 的扩展效率列（如 pace / efg% / tov% 等四因子）？→ **须等样例 HTML 就绪后确认**。
2. **样例 HTML 是否已就绪**：`raw_archive/br_players/antetgi01/lineups_2014.html` 是否已保存？这是 P0 的硬前置，未就绪则解析器无法编写、P0 无法启动。
3. **是否含 Playoffs**：BR 球员 lineup 页是否同时提供 Regular + Playoffs 两表（类比 shooting 页）？决定 P2 是否成立、`season_type` 是否需要。
4. **slug 宇宙最终用哪个源**：player_shooting 的 2861 slug 是否作为主宇宙？联盟页名单是补充还是替代？是否需要把 dim_players.player_id(5,476) 也纳入并集？（注意铁律：gamelog 不可用。）
5. **全量规模与可接受时长**：~15k–25k 页、预计 1–3 天长跑是否可接受？是否需要并行/多 Chrome 实例加速（注意 ≤15 req/min 总配额约束）？
6. **早期赛季页面可用性**：BR 球员 lineup 页对早期赛季（如 1997–2000s）是否都存在？缺失页处理策略（跳过 / 记 `crawl_failures` / 标记 NULL）？
7. **最小分钟阈值**：是否只存 BR 实际列出的组合？是否需要按最小上场分钟过滤（队级默认 0=全存）？
8. **表命名**：确认新表名 `player_lineups`？是否与队级 `team_lineups` 命名风格一致、加区分？
