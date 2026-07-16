# 增量 PRD — NBA 球员头像（Headshot）抓取

> 文档负责人：许清楚（Product Manager / software-product-manager）
> 类型：**增量 PRD（仅描述变更部分）** · 简单版（不含竞品/市场分析）
> 基于：`PRD_v8.3.4.md`、`PRD_nba_crawler_bridge.md`、`crawl_br_gamelog.py`、`run_gamelog_all.sh`、`nba_schema_only.sql`（dim_players 定义）
> 项目代号：`headshots_incremental` · 语言：中文

---

## 1. 产品目标（本轮增量）

在「下一轮爬取」中新增 **Basketball-Reference 球员页 headshot 抓取**：复用库内已有 BR `player_id`，从 `https://www.basketball-reference.com/players/{first}/{player_id}.html` 提取球员头像并**下载到 12TB 本地盘**（`/Volumes/12T/NBA/球星/headshots/{player_id}.jpg`），同时在 `dim_players` 表新增 `headshot_path` 等字段记录本地文件路径（不存 DB BLOB、不只存 URL）。新增代码必须是**增量、独立、互不干扰**的：独立脚本、独立单实例锁名、独立运行步骤，且**绝对不能影响当前正在运行的 gamelog 爬虫（PID 15934）**。

---

## 2. 用户故事

- **US-1（爬取者）**：As a 爬虫运维者，I want 一个独立脚本把 `dim_players` 里全部球员的 BR 头像抓到本地盘并在库里记好路径，so that 下一轮爬取能一并补齐头像，且断点续传、已抓自动跳过，不重复打网络。
- **US-2（爬取者）**：As a 爬虫运维者，I want headshot 抓取与正在跑的 gamelog 爬虫共用同一套 CDP/CF 环境但**串行隔离**，so that 我不会误开第二个浏览器实例撞 BR 被封，也不会拖慢/打断 PID 15934。
- **US-3（前端展示者）**：As a 前端开发，I want 用 `dim_players.headshot_path` 渲染真实头像图替换当前首字母占位（`.player-avatar` 的 `initials`），so that 球员卡片/对位卡显示更直观（头像缺失时优雅回退到首字母）。
- **US-4（数据分析者）**：As a 数据分析师，I want `headshot_path`/`headshot_url` 直接落在 `dim_players`，so that 我能在任何分析/展示场景用 `player_id` 稳定 join 到头像文件，无需重新映射。
- **US-5（数据分析者）**：As a 数据分析师，I want 一轮抓取后产出覆盖度统计（成功/缺失/失败/跳过），so that 我能知道还差多少球员没头像、哪些是 BR 本身无图、哪些是抓取失败需重试。

---

## 3. 需求池（P0 / P1 / P2）

### P0 — Must have（核心交付：抓图 + 入库 + 不干扰）

| 编号 | 需求 | 描述 / 验收标准 |
|---|---|---|
| **HS-01** | 新增独立 headshot 爬虫脚本 | 新增 `external_crawler/crawler/crawl_br_headshots.py`：遍历 `dim_players` 全量 `player_id`（当前 5476 行），对每位球员构建 `players/{first}/{player_id}.html` 页面 URL，提取内嵌 headshot `<img>` 并下载。脚本须**独立、自包含**，不复用 gamelog 的 per-season 逻辑。验收：`.venv/bin/python crawl_br_headshots.py --help` 可用，且 `--limit`/`--dry-run`/`--resume` 行为一致。 |
| **HS-02** | 复用现有 CDP/CF 抓取通道 | 页面 HTML 用 `common.browser.get_driver()`（与 gamelog 一致，`BROWSER_BACKEND=cdp`、`CHROME_CDP_URL=http://127.0.0.1:9222`），复用有效 CF cookie，规避 Cloudflare 拦截。从渲染后的 `page_source` 用 BeautifulSoup 解析 `#info`/`#meta` 区 `.media-item img` 的 `src`，得到头像绝对 URL。验收：能在本机 CDP 环境下取到真实 `<img src>`。 |
| **HS-03** | 本地盘落盘（player_id 稳定键） | 下载字节写入 `/Volumes/12T/NBA/球星/headshots/{player_id}.jpg`，文件名 = `player_id`（与 `dim_players.player_id` PK 一致，避免按真实姓名建目录的歧义/重名问题）。验收：文件存在且为有效图片；`player_id` 与文件名一一对应。 |
| **HS-04** | `dim_players` 加头像字段 | 执行 schema 迁移（见第 4 节草案）：新增 `headshot_path`(text)、`headshot_url`(text)、`headshot_scraped_at`(timestamp)；必要时加 `headshot_status`(varchar)。DB 连接复用现有 `DB_CONFIG`（host=localhost, port=5433, dbname=nba, user=postgres, password=os.environ['DB_PASSWORD']）。验收：`dim_players` 查询含新列；已有 24 列数据零丢失。 |
| **HS-05** | 断点续传 / 幂等（已抓跳过） | 单球员若 `headshot_scraped_at IS NOT NULL` 且本地文件存在则跳过；支持 `--resume`（只抓未完成的）与 `--limit N`（测试）。验收：同球员二次运行不重复下载、不覆盖；`--limit 10` 只处理前 10 人。 |
| **HS-06** | 限速与 CF 兼容 | 球员之间限速 **3–6s**（`3 + random.uniform(0,3)`），与 `crawl_br_gamelog.py` 一致，降低被 BR 封禁风险。验收：日志显示每人间隔 3–6s。 |
| **HS-07** | 与下一轮爬取集成且不干扰 gamelog | 新增独立运行脚本 `run_headshots_all.sh`，**双保险单实例锁**：① 自身锁 `pgrep -f crawl_br_headshots.py` 防并行；② **额外锁 `pgrep -f crawl_br_gamelog.py`**——若 gamelog 仍在跑（含 PID 15934）则拒绝启动，避免争用同一 Chrome CDP 实例、绝不干扰在跑爬虫。环境与原脚本一致（source `.env`、`BROWSER_BACKEND=cdp`、`CHROME_CDP_URL`、`BR_COOKIE_FILE=/tmp/br_cf_cookies.json`）。验收：gamelog 运行时执行本脚本立即退出并写日志；两者不会同时持有 CDP 标签页。 |

### P1 — Should have（前端升级 + 容错）

| 编号 | 需求 | 描述 / 验收标准 |
|---|---|---|
| **HS-08** | 前端用头像替换首字母 | `frontend/js/app.js` 中 `renderVSPlayerCard` / `renderCtxVsPlayerCard` 的 `.player-avatar` 在有 `headshot_path` 时渲染 `<img src=本地路径>`（建议经后端静态服务/绝对路径暴露），无图时回退到当前 `initials`。验收：有头像球员显示图片，无头像显示首字母，两种状态均不破版。 |
| **HS-09** | 失败重试 / 部分失败不中断 | 单球员抓取失败（网络/CF/解析异常）不终止整体运行：记录状态、计数、继续下一人；运行结束打印汇总（成功/缺失/失败/跳过）。验收：中间某球员报错后脚本仍跑完全部并输出统计。 |

### P2 — Nice to have

| 编号 | 需求 | 描述 |
|---|---|---|
| **HS-10** | 尺寸/格式规范 | 统一归一化（如转 JPG、限制最大边、设定质量）；可选生成缩略图（64/128px）供前端卡片用。 |
| **HS-11** | 缺失球员优雅处理 | BR 球员页本身无 headshot（`<img>` 缺失）时，标记状态为 `missing`、路径保持 NULL，不与「抓取失败」混淆。 |
| **HS-12** | 覆盖度统计报告 | 产出 `dim_players` 头像覆盖率报告（按 missing/failed/ok 拆分），可写入爬虫概览页或日志，便于监控缺口收敛。 |

---

## 4. 存储与命名设计要点

### 4.1 本地目录与文件命名
- **根目录**：`/Volumes/12T/NBA/球星/headshots/`（新增独立子目录，与现有按真实姓名建的 `球星/{Real Name}/` 并存、互不干扰）
- **文件命名**：`{player_id}.jpg` —— 例如 `dybanaj01.jpg`、`richapo01.jpg`
- **稳定键**：`player_id`（= `dim_players.player_id` PK），不依赖真实姓名（避免重名、改名、特殊字符问题）
- **扩展名**：BR 头像通常为 `.jpg`；若实际 `Content-Type` 为 `image/png` 则按实际类型落盘（推荐默认 `.jpg`，见 OQ-5）

### 4.2 `dim_players` 新增列定义草案（SQL）
```sql
ALTER TABLE dim_players
  ADD COLUMN headshot_path        text,                            -- 本地绝对路径，如 /Volumes/12T/NBA/球星/headshots/dybanaj01.jpg
  ADD COLUMN headshot_url         text,                            -- BR 头像图片源 URL（用于重抓/排查）
  ADD COLUMN headshot_status      varchar(16),                     -- NULL=未抓 | 'ok'=成功 | 'missing'=BR无图 | 'failed'=抓取失败
  ADD COLUMN headshot_scraped_at  timestamp without time zone DEFAULT now();
```
- 列顺序追加在现有 24 列之后（不改动既有列），保持向后兼容。
- `headshot_status` 用于区分「BR 无图」与「抓取失败」，建议在 P0 一并加入（最终以 OQ-1 确认为准）。
- 不引入 BLOB 列；不单独只存 URL——以「本地文件路径」为唯一事实来源。

---

## 5. 待确认问题（Open Questions，需用户/架构师拍板）

1. **缺失 vs 失败的状态区分**：是否采用 `headshot_status` 枚举（`ok`/`missing`/`failed`）？还是仅用 `headshot_path` 是否为 NULL 来隐式表达（NULL=未成功，但无法区分「BR 无图」与「抓取失败」）？**建议加 `headshot_status`**，便于重试只针对 `failed`。
2. **头像尺寸/变体**：只存 BR 原始图，还是额外生成前端用的缩略图（如 64/128px）？影响存储与 HS-08 前端取图方式。
3. **浏览器实例策略**：headshot 复用 gamelog 的同一 Chrome CDP（`http://127.0.0.1:9222`，串行隔离），还是为 headshot 单独起一个 headless 实例以减少耦合？复用最简但强制串行（见 HS-07）。
4. **运行编排方式**：headshot 步骤是作为独立 `run_headshots_all.sh` 由调度/手动触发，还是作为 `run_gamelog_all.sh` 末尾一个**受双锁保护**的尾随步骤？**建议独立脚本 + 双锁**，明确与 gamelog 解耦。
5. **图片扩展名**：全部按 `.jpg` 落盘，还是按实际 `Content-Type` 决定（`.png` 等）？影响 `headshot_path` 拼接与 `headshot_url` 解析。
6. **`headshot_url` 存什么**：存 BR **头像图片 URL**（利于重抓/排查）还是球员页 URL？**建议存图片 URL**。

---

## 6. 非功能护栏（贯穿 P0）

- **零干扰**：任何情况下不得与 PID 15934（gamelog 爬虫）并行运行；共用 Chrome CDP 时强制串行。
- **幂等**：已成功抓取的球员不被重复下载、不被覆盖。
- **复用优先**：DB 配置、CF/CPD 通道、限速策略、单实例锁模式全部对齐 `crawl_br_gamelog.py` / `run_gamelog_all.sh`，不另起炉灶。
- **可重试**：`failed` 状态球员可经 `--resume` 在下一次运行补齐。
