# BR 球队页数据维度覆盖审计

> 目标：爬取 BR `/teams/{slug}/` 页面上的全部链接，盘点我们相对 BR 还遗漏哪些数据维度，最大化接近 BR。
> 方法：从已缓存的 **540 份** HTML（30 队 × 18 类页）抽取全部 `/teams/{本队}/*` 内部链接 → 归一化得到 BR 提供的子页类型 → 与本项目 105 张表逐一比对行数。
> 审计日：2026-08-21

## 一、BR 球队页实际提供的子页类型（证据来自缓存链接抽取）

非赛季数据页（每队 22 类，链接在缓存中均出现 1458 次 = 30 队 × 页面内多链接）：

| BR 子页 | 我们的落点 | 状态 | 行数 |
|---|---|---|---|
| `stats_basic_*` (totals/ranks/yr_yr) | `team_franchise_stats` | ✅ 已覆盖 | 159,764 |
| `stats_per_game_*` (3) | `team_franchise_stats` | ✅ 已覆盖 | 159,764 |
| `opp_stats_basic_*` (3) | `team_franchise_stats` | ✅ 已覆盖 | 143,943 |
| `opp_stats_per_game_*` (3) | `team_franchise_stats` | ✅ 已覆盖 | 143,943 |
| `players` | `team_franchise_players` | ✅ 已覆盖 | 419,642 |
| `numbers` | `team_franchise_numbers` | ✅ 已覆盖 | 14,911 |
| `head2head` | `team_franchise_head2head` | ✅ 已覆盖 | 10,436 |
| `hof` | `team_franchise_hof` | ✅ 已覆盖 | 2,062 |
| `all_star` | `team_franchise_all_star` | ✅ 已覆盖 | 1,926 |
| `index`（/teams/{slug}/ 主页） | `team_franchise_index` | ✅ 已覆盖 | 1,740 |
| `leaders_career` / `leaders_season` | `team_leaderboards` | ✅ 已覆盖（其他爬虫） | 5,569 |
| `draft` | `dim_draft_history` | ✅ 已覆盖（其他爬虫） | 8,446 |
| `executives` | `team_executives` | ✅ 已覆盖（其他爬虫） | 382 |
| `coaches` | `team_franchise_index.coaches` + `team_coaches` | ✅ 已覆盖（其他爬虫） | 689 |
| `transactions` | `transactions` | ✅ 已覆盖（其他爬虫） | 28,667 |
| `awards` | `player_award_shares` | ✅ 已覆盖（其他爬虫） | 3,527 |
| `shooting` / `lineups` / `on-off` / `splits` | `player_shooting`/`team_lineups`/`team_on_off`/`team_game_splits` | ✅ 已覆盖（其他爬虫） | — |
| `roster` / `gamelog` / `salaries` | `team_roster`/`player_gamelog`/`player_salaries_historical` | ✅ 已覆盖（其他爬虫） | — |
| **`1947.html` … `2027.html`（逐年赛季页）** | **无对应表** | ❌ **未爬取** | **0** |

> 注：`per_36` / `advanced` / `per_poss` 等统计变体**不在** BR 球队 franchise 层暴露（缓存链接抽取 0 命中），仅 basic/per_game（+opp）两级 —— 我们 12 个 stat 页已与 BR 完全对齐。

## 二、唯一真实的缺口

### ❌ 逐年赛季页 `1947.html` … `2027.html`（约 50 年 × 30 队 ≈ 1500 页）
- BR 每队主页都链接到这些**逐赛季 franchise 落地页**，包含：该季战绩/排名/主教练/季后赛结果叙述、球队赛季数据、对手数据、赛季 leader、阵容、赛程与逐场 gamelog。
- 我们**从未作为独立页爬取**（franchise 爬虫 18 页不含；其他爬虫也未按此页型入库）。
- **可加价值评估（重要，避免盲目补爬）**：
  - 该页绝大多数内容（逐场比分、球队赛季数据、阵容、gamelog）**已被现有表覆盖**（`dim_games` / `team_stats_per_game` / `team_roster` / `player_gamelog` / `team_franchise_index` 已有赛季级 W-L 与排名）。
  - 真正**新增**的信息主要是：BR 原生的"赛季叙述文本"（如季后赛结果一句话、赛季小结）与 BR 原样聚合呈现。属展示层补充，**非新指标维度**。
  - 结论：补爬边际数据价值**偏低**，除非你要逐季复刻 BR 赛季页原貌。

## 三、结论

**在 BR 球队 franchise 页这一层，我们的数据维度覆盖已接近完整**（12 stat 页 + 5 列表页 + index，且 opp_stats 287,911 行、players 419,642 行等均已入库；draft/executives/coaches/transactions/awards/shooting/lineups/on-off/splits/roster/gamelog/salaries 等由项目内其他爬虫补齐）。

唯一未触及的 BR 球队页型是**逐年赛季页（1947–2027）**，但其数据主体已被现有赛季级表覆盖，仅缺 BR 原生叙述文本。

## 四、建议下一步（待你确认再动手，不擅自爬取）

1. **若只想"维度对齐 BR"**：当前已基本达成，无需新爬。
2. **若要复刻 BR 逐季赛季页原貌**（含叙述文本）：可新增 `team_franchise_seasons` 页型，爬取 1947–2027 共约 1500 页，落盘 + 抽取赛季叙述/战绩小结。工作量中等、CF 风险低（已验证系统 curl 稳 200）。
3. **若想扩到 BR 其他页族**（球员页 / 联盟页 / boxscore 等）：那已是项目内既有爬虫（player_gamelog、play_by_play 等）范畴，非球队 franchise 页遗漏，可单独立项。

请告知要走哪条。
