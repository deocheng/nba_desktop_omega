# 已归档爬虫（解析目标失效 / 不再投产）

本目录存放**经实测确认解析目标已失效**或**已被取代**的爬虫。归档 ≠ 删除：代码保留以便追溯，
但不再挂进 `crawler_console/registry.py`（现役爬虫登记表），也不应再被任何 `run_*.sh` 驱动。

---

## crawl_br_team_shooting.py（＋ run_br_team_shooting_fill.sh）

**归档日期**：2026-10-22
**归档原因**：爬虫解析的目标表 `team_shooting` / `opponent_shooting`（队级出手区域分布）
在 BR 现行队页中**不存在**，实跑必然 0 行、且逐队写 `crawl_failures`。

> ⚠️ 更正一次误判：初版归档说明写的是"BR 已下线队级 zone 数据"。**这是错的。**
> 队级距离数据仍在页面上，只是换了形状（见下"数据实际在哪"）。
> `orchestrator_tasks.py:266` 早在 2026-08-05 就已记录此事实。

### 失效证据（2026-10-22 实测）

爬虫假设队页 `#all_shooting` 区块含 `team_shooting` / `opponent_shooting` 表。实测：

| 检查项 | 结果 |
|---|---|
| `team_shooting` 表 id（raw HTML） | **0 次**（SAS 2015/2020/2023/2024/2025/2026 全赛季） |
| `team_shooting` 表 id（含全部 ~220 个 HTML 注释节点） | **0 次** |
| `Restricted Area` / `Mid-Range` / `Above the Break` / `0-3 Feet` | **0 次** |
| `/teams/{slug}/{year}_shooting.html`（下划线变体） | HTTP 404 |
| `/teams/{slug}/{year}/shooting/`（子目录变体） | HTTP 404 |

该区块注释内的表 id 全集为：
`team_and_opponent, team_misc, totals_stats, per_poss, advanced, adj_shooting, shooting, pbp_stats, salaries2`
—— 无 `team_shooting` 及其 `_post` 变体。BR 队页**从来没有过**这个表 id，
故本爬虫自编写起就解析不到任何行。

### 数据实际在哪（可复活，但语义不等价）

2026-10-22 实测 SAS/2024 队页：数据在**球员级 `shooting` 表**里，以
**距离桶列** + **tfoot "Team Totals" 行**的形式存在（不是独立的队级表）：

```
表头(30 列): [Rk, Player, Age, Pos, G, GS, MP, FG%, Dist.,
              2P, 0-3, 3-10, 10-16, 16-3P, 3P,   ← % of FGA by Distance
              2P, 0-3, 3-10, 10-16, 16-3P, 3P,   ← FG% by Distance
              2P, 3P, %FGA, #, %3PA, 3P%, Att., Md., Awards]
tfoot:        ['', 'Team Totals', ..., 82, 82, 19830, .462, 12.7,
               .599 .258 .200 .088 .052,   ← %FGA：2P .599 + 3P .401 = 1.000 ✓
               .539 .692 .445 .427 .338,   ← FG%：2P 内四桶合计 .598 ≈ .599 ✓
               .625, .914, .066, 437, .235, .384, 16, 0, '']
```

**关键约束（决定为何不能简单改 URL 复活）**：tfoot 只给出**百分比**
（各距离桶的 %FGA / FG%）与少数计数（corner3 次数 437、1/2 court 出手 16），
**不提供分桶的原始命中/出手数与分钟**（`fg`/`fga`/`mp`）。
而 `team_shooting` 表结构要求每 zone 一行且含 `fg/fga/mp/fg_pct/...`。
→ 即便重写解析器，也只能填出**百分比口径**，`fg`/`fga`/`mp` 将永远为 NULL，
与原表语义**不等价**。

### 若要复活，三条路（须先定语义）
1. **接受降级 schema**：新建 `team_phooting_pct` 表，仅存分距离桶的 %FGA / FG%
   （语义清晰、可与球员级对齐），不改 `team_shooting`。
2. **换源**：NBA 官方 Stats API 的 team shotchart 端点（可给原始 make/attempt），
   代价是数据源从 BR 切到 NBA 官方。
3. **维持归档**：若队级分桶命中率/出手分布无下游需求，则不复活。

### 影响面
- `team_shooting` 表**从未建立**（`to_regclass('public.team_shooting')` = NULL），
  本爬虫历史上未成功落库任何数据 → **归档无数据损失**。
- `crawl_failures` 中无任何 `br_team_shooting` 记录（从未真正跑起来）。
- 同族数据不受影响：`player_shooting` / `player_shot_chart`（球员级）仍现役，
  且 `player_shooting` 已覆盖 1997-2026 全 30 季。