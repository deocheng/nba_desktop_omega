# PRD — NBA 跨源桥接与双爬虫回补（简单版）

> 文档负责人：许清楚（Product Manager / software-product-manager）
> 版本：v0.1（简单版，不含竞品/市场分析）
> 团队：`software-nba-crawler-bridge`

---

## 1. 项目信息

| 项 | 内容 |
|---|---|
| Language | 中文（与用户需求一致） |
| Programming Language | **Python 3 + PostgreSQL**（端口 5433，库名 `nba`，用户 `postgres`）。本任务为数据管道 / 爬虫，非前端，故不适用 SOP 默认的 Vite+React+MUI+Tailwind 栈；既有脚本均为 `.py`，需复用而非重设计。 |
| Project Name | `nba_crawler_bridge` |
| 数据现状基线 | `dim_games` 70946 行；2023–26 共 **5313** 场；按 BR gid 已有 PBP 仅 **607/5313（≈11%）**；球员级 BR 统计 2023+ 已全量；孤儿（nba_api_id IS NULL）**528** 场；pbp_no_data=true 仅 **2** 场。 |

### 原始需求复述（用户逐条）
1. 确认 2023 至今 BR 数据是否全量；有缺则补、满则前推更早年份，**只爬缺失数据**。
2. 不同源 game id 大量不一致 → 用「主客队 + 比分 + 时间」找到共同指向，**补全 BR 的 game id**（桥接 BR gid ↔ nba_api_id ↔ ESPN event_id）。
3. 爬 ESPN 也要**爬更宽的数据集**（不止投篮坐标）。
4. 双爬虫**原始数据必须落盘**（BR HTML、ESPN JSON 都要存，不能只存解析后 DB 行）。
5. （隐含）保持**幂等**，绝不破坏已有真实坐标。

---

## 2. 产品目标（3 个清晰、正交的目标）

- **G1 — 跨源比赛身份统一**：以 `dim_games` 的 `(game_date, home_team_abbr, away_team_abbr, home_pts, away_pts)` 为天然锚点，建立稳定的 BR gid ↔ nba_api_id ↔ ESPN event_id 映射，从根本上解决跨源 game_id 不一致的桥接问题（含 528 场孤儿与错位场）。
- **G2 — BR 按 BR gid 的 PBP 缺口回补**：在严格幂等、绝不覆盖真实坐标的前提下，把 2023+ 按 BR gid 索引的 PBP 覆盖率从 ~11% 显著抬升（缺则补、满则前推）。
- **G3 — ESPN 宽数据集 + 双源原始归档**：扩展 ESPN 抓取范围至盒式/高级数据（不止投篮坐标），并将 BR HTML 与 ESPN JSON 原始响应落盘，保证可离线重解析、可审计。

> 原始归档（需求 4）作为贯穿 G2/G3 的**非功能护栏**落地，不单列为目标，但列为 P0。

---

## 3. 用户故事（爬虫运维者视角）

- **US-1**：As a 爬虫运维者，I want 跑一次自动对账，用 (日期+主客队+比分) 把 BR gid ↔ nba_api_id ↔ ESPN event_id 对齐，so that 缺失/错位的跨源钥匙能被批量补全，无需人工查表。
- **US-2**：As a 爬虫运维者，I want `br_fill_pbp` 能回补「PBP 挂在 nba_api_id 下、但 BR gid 下没有」的约 4655 场，so that 按 BR gid 索引的 PBP 覆盖率远超当前的 11%。
- **US-3**：As a 爬虫运维者，I want ESPN 爬虫除投篮坐标外还能抓取盒式/高级数据，so that 我们拥有一个更宽的 ESPN 数据集入库。
- **US-4**：As a 爬虫运维者，I want 两个爬虫都把原始 HTML/JSON 落盘归档，so that 需要重解析时不必重新打网络、且可审计原始响应。
- **US-5**：As a 爬虫运维者，I want 回补过程永远幂等、绝不覆盖已有真实坐标（x,y），so that 那 607 行带真实坐标的 PBP 不被破坏。

---

## 4. 需求池（P0 / P1 / P2）

### P0 — Must have（覆盖需求 1/2/4/5）

| ID | 需求 | 说明 / 验收口径 |
|---|---|---|
| **P0-1** | 跨源 game_id 桥接（按 日期/主客队/比分） | 基于 `dim_games` 锚点 `(game_date, home_team_abbr, away_team_abbr, home_pts, away_pts)` 建立 BR gid ↔ nba_api_id ↔ ESPN event_id 映射。优先处理 528 场 `nba_api_id IS NULL` 孤儿（2002:14 / 2004:3 / 2024:125 / 2025:1 / 2026:385）。产出桥接表 + 无法桥接清单。 |
| **P0-2** | BR 2023+ 缺失 PBP 按 BR gid 回补 | 对 2023–26 共 5313 场中「按 BR gid 无 PBP」的约 4706 场（其中 ~4655 场 PBP 已挂在 nba_api_id 下），复用 `br_fill_pbp.py` 的 `get_targets()` 排除逻辑回补；2 场 `pbp_no_data=true` 跳过；已全量则前推更早年份，**仅爬缺失**。 |
| **P0-3** | 双爬虫原始数据落盘 | `br_crawler` 抓取的 BR HTML、`espn_backfill_shot_coords`（及扩展脚本）抓取的 ESPN JSON **必须**归档到磁盘（路径/格式见 Open Questions）。不可只写解析后 DB 行。 |
| **P0-4** | 幂等守卫（贯穿护栏） | 回补**永远不加 `--force`**；已存在真实坐标（br_crawler / ESPN / nba_api 的 `(x,y)`）不得被覆盖；`get_targets()` 已存在 PBP（按 game_id 或 nba_api_id 任一）的比赛必须排除。 |

### P1 — Should have（覆盖需求 1/3）

| ID | 需求 | 说明 / 验收口径 |
|---|---|---|
| **P1-1** | ESPN 宽数据集 | 在现有 `espn_backfill_shot_coords.py`（Site API v2 summary → 投篮坐标）基础上，扩展抓取盒式 boxscore、球队/球员高级数据；先定**最小可用集**（见 OQ-c）。需把原始 JSON 一并落盘（呼应 P0-3）。 |
| **P1-2** | 覆盖判定与回填报告 | 产出「2023+ BR 全量」判定报告：球员级已全（✅）、PBP 按 BR gid 仅 ~11%（❌）。据此决策「补 2023+ 缺口」或「前推更早年份」，且**只爬缺失**。 |
| **P1-3** | 孤儿与错位专项 | 528 场 `nba_api_id IS NULL` 优先桥接；无法桥接的单独输出清单供人工兜底。 |

### P2 — Nice to have

| ID | 需求 | 说明 |
|---|---|---|
| **P2-1** | 更早年份前推自动化 | 当 2023+ 判定为全量后，自动触发 <2023 年份的前推爬取（仅缺失）。 |
| **P2-2** | 归档校验/索引 | 对落盘原始文件做校验和、去重、索引，便于回溯。 |
| **P2-3** | 跨源覆盖度看板 | 可视化各赛季 BR gid / nba_api_id / ESPN 三方覆盖度，便于监控缺口收敛。 |

---

## 5. 待确认问题（Open Questions）

- **(a) 原始归档路径与格式**：建议 `raw_archive/br/{season}/{gid}.html` 与 `raw_archive/espn/{date}/{event}.json`。是否采用？是否需要分区到「按年/按月」或带抓取时间戳？
- **(b) 约 4655 场「PBP 已在 nba_api_id 下、BR gid 下没有」**：是**重新用 BR gid 爬原始+解析一遍**（双份存储、BR 原生解析），还是**仅做桥接**（把 BR gid ↔ nba_api_id 对上、不重复爬）？这直接决定工作量量级（≈4655 场重爬 vs 纯 SQL/映射更新）。**强烈建议先明确此项再动工。**
- **(c) ESPN「宽数据集」最小可用集**：先抓 boxscore（球队/球员逐场）？还是一并纳入球队/球员高级（advanced）数据？请给出首批范围，避免过度抓取。
- **(d) 「BR 2023+ 全量」判定口径**：球员级统计已完整、PBP 按 BR gid 仅 11%——本任务以**哪个**为「全量」标准？是否以「PBP 按 BR gid 覆盖」为唯一缺口标尺？

---

## 6. 关键定义决策（文末确认）

> 本任务语境下，**「BR 2023+ 全量」= 球员级统计已全（✅），但按 BR gid 索引的 PBP 仅 ~11%（❌ 缺口）**。桥接（P0-1）与回补（P0-2）**针对的是后者**——即把「按 BR gid 视角缺失 PBP」的比赛补齐或对齐，而非重做已经完整的球员级统计。
