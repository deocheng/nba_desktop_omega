# NBA 2027 赛季 BR 四类数据补全 — 执行报告（2026-10-23 T+3h）

> 自动化任务批次：08d88999-b4e5-45ff-baf3-ee7d81dc76a3
> 执行时刻：2026-10-23 13:23 → 14:36 (GMT+8)

## 环境就绪
- PostgreSQL 5433（nba）：`pg_isready` 接受连接 ✅
- Chrome CDP（9223，受信 profile）：可达（HTTP 200）✅，全程保持打开
- 修复项（本批次对脚本的最小改动，已记录）：
  1. `external_crawler/nba_daily_crawler.py`：`Config.DB_PASSWORD` 改为优先读取 `PGPASSWORD`（原硬编码 `'postgres'` 与该迁移环境实际口令不符，导致认证失败）。
  2. 同文件 `BrowserManager.start()`：新增读取 `UC_CHROMEDRIVER_PATH` 环境变量，解决 Apple Silicon 上 UC 下载 x86_64 驱动导致 `Bad CPU type` 崩溃（根因见项目记忆 UC arm64 条）。
  3. 清理 CDP Chrome 中残留的游离 page（上次 gamelog 爬虫遗留的 willibr03/kolokch01 gamelog/2026 页），使 shot 爬虫 CDP 重连稳定。

## (a) 日更爬取结果（`nba_daily_crawler.py`，默认抓当天）
- 检测到 7 天缺失数据，自动回填 2026-10-16 → 10-22；**现已进入今天 2026-10-23**（team_game_splits 至 BOS 2/31）。
- 每日期次 = games(赛程/结果) + team_game_splits(31 队)。过程中 `imported=0` 居多（2027 早期赛季数据多已存在/暂空，属正常跳过）。
- 现象：10-22 起部分球队（DAL/DEN/DET/GSW/HOU/MEM/MIA 等）`team_game_splits` 报「未找到splits表格」——早期赛季 splits 表尚未生成，或瞬时 CF 残页；非致命，已跳过。
- 进程存活，自管 UC 浏览器，持续回填中。

## (b) player_shot_chart 2027 现库行数
- 总行数：**2446**；覆盖 (player,game) 对：**271 / 377（覆盖率 71.9%）**。
- 当前缺口：**106 个 (player,game) 对**（对应约 51 名零覆盖球员）。
- `crawl_2027_shot_charts.py`（BROWSER_BACKEND=cdp）已启动并连上受信 CDP，开始按球员字母序重爬 355 个 2027 slug（resume、幂等）。首球员 achiupr01 遇瞬时 CF 残页，重试后自愈，现正常 upsert（已至 b* 段）。覆盖率将随触达缺口球员而上升。

## (c) 四类 2027 覆盖率
| 类别 | 指标 | 2027 状态 |
|---|---|---|
| Box Score | player_gamelog 行数 | **377** ✅ 完整 |
| Plus/Minus | player_gamelog.plus_minus 非NULL | **377 / 377 = 100%** ✅ 完整 |
| Play-By-Play | play_by_play distinct gameid | **16** ✅ 完整 |
| Shot Charts | player_shot_chart (player,game)对 | **271 / 377 = 71.9%** ⏳ 回填中（缺口 106） |
| 派生 fct_pbp_shots | 行数 | **0** — 未重建（见 (d)） |

## (d) fct_pbp_shots 拟映射 + 行数（⚠️ 待用户确认，绝未写库）
- 仅做反向推导分析，**未执行任何 INSERT**。
- 2027 `play_by_play` 投篮事件（event_type ∈ 'Made Shot','Missed Shot'）：**2820 行 → 拟生成 fct_pbp_shots ≈ 2820 行**。
- 拟映射规则：
  - `season` ← play_by_play.season (2027)
  - `game_id` ← play_by_play.gameid（BR 格式，与原 fct 一致）
  - `period` ← play_by_play.period
  - `team` ← play_by_play.team
  - `player_slug` ← play_by_play.player（PBP 显示名，如 'T. Maxey'，**非 BR slug**）
  - `is_make` ← (event_type = 'Made Shot')
  - `shot_type` ← 由 subtype/description 推导 2PT/3PT
  - `shot_distance` ← play_by_play.dist
  - `qrem` ← 该节剩余秒数（由 clock_seconds 推导）
  - `is_eop` / `is_clutch` ← 由 clock_seconds / period / 分差 派生的布尔
  - `src_ctid` ← 暂映射 player1_id（**需与既有 fct 约定核对**）
  - `season_type` ← 由 dim_games 经 game_id→nba_api_id 映射 BR 格式判定
- 样例（play_by_play→fct）：gameid=22600002, PHI, 'T. Maxey', Made Shot, dist=28, clock_seconds=704。
- **下一步**：待用户确认上述映射（尤其 `src_ctid` 与 `player_slug` 语义）后，再编写并执行 INSERT 重建脚本。

## 风险与待办
1. **CF 瞬时挑战**：shot 爬虫首球员遇 CF 残页已自愈；若后续再遇，任务约定需用户在受信 CDP Chrome 上手动点一次 "Verify you are human" 后爬虫继续。
2. **shot 回填未完成**：爬虫在后台按字母序重爬 355 人（含已覆盖者），触达缺口球员后覆盖率上升；预计仍需一段时间，进程持续运行。
3. **fct_pbp_shots 写库待确认**：2820 行映射已就绪，等用户拍板后写。

## 产物/日志
- `logs/daily_crawler_20261023.log` — 日更爬虫
- `logs/shot_charts_2027.log` — shot 爬虫
- `logs/analyze_2027_recon.py` — 本批次对账/fct 分析脚本（只读）
