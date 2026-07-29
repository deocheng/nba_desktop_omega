# PRD — BR 球队页数据补全（br_gapfill）

> 内部数据基础设施项目，非用户级产品。目标：补全 BR 球队页左侧菜单中当前缺失的 5 类数据，全量回补历史赛季并落库至 `nba`（postgres @127.0.0.1:5433, public 模式）。

## 1. 产品目标

**一句话目标**：把 BR 球队页左侧菜单中当前缺失的 5 类数据（Lineups / On-Off / Referees / Depth Charts 当前季 / Team Shooting）全量补全并规范落库，消除平台的数据覆盖缺口。

**可量化成功标准**：
1. 5 类数据全部落库，其中 ⑤①②③ 覆盖 BR 有数据的最早赛季 → 最新赛季（目标 1947→2026）全历史；④ 补齐 2025-26 当前季。
2. 落库数据经抽查，5 类数据的赛季覆盖率均 ≥ 99%（缺失页有明确处理策略并记录于 `crawl_failures`）。
3. 5 类数据均提供与现有表一致的、可被分析查询直接 JOIN 的实体键（team / season / player_id / game_id），无孤立数据。

## 2. 用户故事

| # | 用户故事 |
|---|---|
| ⑤ | 作为数据分析师，我希望查询任意球队任意赛季的队级投篮分布（自身与对手），以便做投篮效率与防守覆盖的横向对比。 |
| ① | 作为数据分析师，我希望获取任意球队任意赛季的全部 5 人阵容组合及其在场时间与净胜分，以便评估阵容搭配效果。 |
| ② | 作为数据分析师，我希望知道每个球员上场/下场时球队的攻防效率与正负差，以便量化球员真实影响力。 |
| ④ | 作为数据分析师，我希望深度图包含最新 2025-26 季的位置排序，以便分析当前球队轮转与伤病影响。 |
| ③ | 作为数据分析师，我希望知道每场比赛的执法裁判名单，以便研究裁判尺度对比赛结果的影响。 |

## 3. 需求池（按优先级 51243 → P0~P4）

> 优先级序列含义：P0=最先实现。落库表名为**建议名**，最终由架构师确认；命名风格参考现有 `starting_lineups` / `team_depth_chart` / `player_shooting`（snake_case + 复数/实体描述）。

| 优先级 | 域 | 编号 | BR 源页 URL 模式 | 数据实体 | 落库表名建议 | 字段要点 | 回填范围 | 验收标准 |
|---|---|---|---|---|---|---|---|---|
| **P0** | Team Shooting | ⑤ | `/teams/{ABBR}/{YEAR}/shooting/`（More 页内） | 球队自身 + 对对手的投篮分布（区域/距离/命中率） | `team_shooting` | team, season, vs_type（own/opponent）, zone_or_distance（如 Restricted Area / Corner 3 / Mid-Range / 距离桶）, fg, fga, fg_pct, x2p/x3p 拆分, fg_freq（出手占比） | **全历史**（BR 最早赛季→2026） | 每个 team×season×vs_type×zone 行齐全；fg/fga 与 BR 页面数值一致（误差 ≤0）；覆盖季与 `team_summaries` 对齐。 |
| **P1** | Lineups | ① | `/teams/{ABBR}/{YEAR}/lineups/` | 所有 5 人阵容组合 + 在场分钟 + 净胜分/正负 | `team_lineups` | team, season, player_id×5（5 个位置占位）, gp（出场数）, mp（总分钟）, won, lost, off_rtg, def_rtg, net_rtg（或 pts/opp_pts 推导） | **全历史** | 组合粒度正确（5 人无序去重）；mp/net_rtg 与 BR 一致；含 BR 默认最小分钟阈值下的全部组合。 |
| **P2** | On/Off | ② | `/teams/{ABBR}/{YEAR}/on-off/` | 每个球员上场/下场时球队/对手攻防效率与正负 | `team_on_off` | team_abbr, season, season_type, player_id, br_player_id, player_name, **on_mp/on_off_rtg/on_pace/on_efg_pct/on_tov_pct/on_orb_pct/on_drb_pct/on_trb_pct/on_stl_pct/on_blk_pct/on_ast_pct**（Off 组 `opp_` 前缀、Diff 组 `diff_` 前缀，共 33 数值列） | **全历史** | 每 team×season 覆盖全部出场球员；On/Off/Diff 三组效率可从 BR 核对一致（净值由 Diff 组体现，无独立 net 列）。 |
| **P3** | Depth Charts | ④ | `/teams/{ABBR}/{YEAR}/depth-charts/` | 各位置深度排序（**增量补 2025-26**） | `team_depth_chart`（**已存在表，仅增量 upsert 2025-26**） | team, season, position（PG/SG/SF/PF/C）, depth_rank, player_id | **仅 2025-26 一季（增量更新，非全量新建）** | 2025-26 各队 5 位置深度排序均已 upsert；不与既有历史行冲突（按 team+season+position+depth_rank 唯一键）。 |
| **P4** | Referees | ③ | `/teams/{ABBR}/{YEAR}/referees/` | 每场比赛的裁判名单 | `game_referees` | game_id, team, season, ref_name×3（或 ref_id×3） | **全历史** | 每 game 裁判数 = BR 列出数（通常 3）；game_id 可与 `games` 表 JOIN；缺失页有记录。 |

**关键范围标注**：
- ④ Depth Charts = **增量更新**（补 2025-26 一季），复用现有 `team_depth_chart` 表，不新建表。
- ⑤ Team Shooting = **新建队级表**，与现有 `player_shooting`（球员级）并存，互不冲突。

## 4. 数据产物形态（替代 UI 设计）

本项目无前端界面，下游消费者为分析查询 / BI。产物形态如下：

| 域 | 落库目标 | 是否进 postgres | 中间缓存 |
|---|---|---|---|
| ⑤ Team Shooting | 新表 `team_shooting`（public） | ✅ 是 | 本地缓存目录 `br_shooting_cache/`，按 (team, season) 存原始解析结果，参考既有 `gamelog_cache/` 的 **merge 语义**（追加新数据、不覆盖） |
| ① Lineups | 新表 `team_lineups` | ✅ 是 | `br_lineups_cache/`，按 (team, season) 缓存原始 HTML/解析 JSON |
| ② On/Off | 新表 `team_on_off` | ✅ 是 | `br_onoff_cache/`，按 (team, season) 缓存 |
| ④ Depth Charts | 复用 `team_depth_chart`，仅 upsert 2025-26 | ✅ 是 | 可复用既有 depth 抓取缓存，无需新建目录 |
| ③ Referees | 新表 `game_referees` | ✅ 是 | `br_referees_cache/`，按 (team, season) 缓存，落库时按 game_id 去重 |

- **统一约定**：全部 5 类最终数据均落 postgres `nba` 库 public 模式；爬虫与落库**分离**，先写本地 cache 再 MERGE 入库，保证可断点续跑、可重放。
- 实体键对齐现有表：`team`↔`team_mapping`，`season` 沿用**结束年**整数（如 **2026** = 2025-26 季，与 `dim_games.season`/`team_depth_chart.season` 一致，**非起始年**），`player_id`↔现有球员桥表，`game_id`↔`games`。

## 5. 待确认问题（决策价值）

1. **⑤ Team Shooting 表结构**：是建两张表（`team_shooting` 自身 / `team_shooting_opponent` 对手）还是合并为单表带 `vs_type` 列？影响查询与维护成本。
2. **① Lineups 组合爆炸**：是否只存 BR 实际列出的组合？是否采用 BR 默认的**最小上场分钟阈值**（如 MP≥10）过滤？全量组合（含极低分钟）是否必要？
3. **早期赛季页面可用性**：Referees / On-Off / Lineups 页面 BR 是否对早期赛季（如 1950s）都存在？对缺失页的处理策略（跳过 / 记 `crawl_failures` / 标记 NULL）？
4. **爬虫组织方式**：为 5 类各建独立脚本（`crawl_br_lineups.py` 等），还是扩展现有某个爬虫（如 `crawl_br_gamelog.py`）统一调度？
5. **全量回填限速/并发**：是否沿用既有 BR 爬虫 **≤15 请求/分钟** 的限制？多域并行回填时如何分配配额避免触发反爬？
6. **表命名规范**：确认沿用 snake_case + 实体描述（`team_shooting` / `team_lineups` / `team_on_off` / `game_referees`）？是否需要统一加 `br_` 前缀区分数据源？
7. **球员键桥接**：① Lineups / ② On-Off 的球员如何用现有 `player_name_map` / `player_id` 桥对齐 BR 球员 slug？是否存在历史球员缺桥需补？
8. **裁判实体化**：③ Referees 用裁判姓名字符串存储，还是需新建 `referees` 引用表分配 `ref_id` 以支持跨队统计？
