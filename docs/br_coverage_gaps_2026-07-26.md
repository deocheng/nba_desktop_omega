# BR 数据覆盖缺口诊断（2026-07-26）

> 只读诊断，连接 `127.0.0.1:5433 / nba`。slug 宇宙以 `player_shooting`（1997-2026）为准。
> 注：Playoffs 真实宇宙 = 有 Playoffs shooting 数据的 `(slug,season)` 对 = **6,099**（非 14,569）；其余为非季后赛球员（BR 返回 404，属伪缺口，不应反复重爬）。

## 总览

| 域 | 状态 | 覆盖 | 真实缺口 |
|---|---|---|---|
| player_shooting | ✅ 完整 | 14,569 Regular + 6,099 Playoffs（1997-2026） | 0 |
| player_onoff | ✅ 基本完整 | Regular 14,565/14,569（100%）、Playoffs 6,086/6,099（99.8%） | ~13 |
| player_lineups | ⚠️ 未完成 | Regular 12,038/14,569（82.6%）、Playoffs 1,896/6,099（31.1%） | **~6,733** |
| player_gamelog | ⚠️ 小缺口 | 3,485 distinct br_player_id | ~210 slug 无记录 |
| play_by_play | ⚠️ 部分 | 38,990/74,321 场有 PBP（52%） | ~35,331 场无 |
| team_shooting（提案） | ❌ 空 | 0 | 全缺 |
| team_lineups（提案） | ❌ 空 | 0 | 全缺 |
| team_on_off（提案） | ⚠️ 部分 | 4,523 行 | 大部分缺 |

## 详细说明

### 1. player_lineups（主缺口，建议优先）
- **Regular 缺口 2,530**：均匀分布在 2018-2026 各季（每季约 80-84% 完成，缺口 ~100-114/季），非集中在新季。
- **Playoffs 缺口 4,203**：仅 31.1% 完成，是最大短板。
- ⚠️ 隐患：自动跑批曾把"非季后赛球员"也当 Playoffs 目标，导致大量 404 未隔离（`player_lineups_404` 仅 1 行）。补爬前需先修隔离逻辑，否则会重蹈 on-off 死循环覆辙。

### 2. play_by_play（部分覆盖，已知）
- 按 source 拆分：br_crawler 31,863 场（主体）/ nba_api 5,882 / ESPN 513 / BBRef 732。
- 35,331 场**无任何 PBP**（多为早期赛季与特殊场次）。动画引擎仅对 br_crawler 真实 xy 场有效。
- 铁律提醒：诊断 PBP 覆盖必须 `SELECT DISTINCT gameid FROM play_by_play`（全源），只看 `source='BBRef'`（仅 732 场）会严重误判。

### 3. player_gamelog（小缺口）
- 210 个 shooting slug 完全无 gamelog（如 `ajincal01`、`allenti01`，多为短生涯/国际球员）。
- 注意：`gamelog.br_player_id` 连接键与 `shooting.player_id` 口径不同，跨表关联需谨慎。

### 4. team 级 gapfill（br_gapfill 提案表，新域）
- `team_shooting` / `team_lineups` **完全空**（未爬）。
- `team_on_off` 有 4,523 行（部分）。
- 这些属"新提案域"，不在既有三域（shooting/lineup/on-off）范畴内。

## 关于"用新爬虫测试"

新爬虫（基于 Scrapling 的 `BRPlayerPageCrawlerStealth`）目前**仅有设计文档** `docs/crawler_scrapling_inherit_design.md`，**业务代码库中无任何 Stealth 实现**（Grep 仅命中 `research/Scrapling/` 克隆仓与文档）。

因此当前无法"用新爬虫测试"——必须：
1. **P2** 安装 scrapling；
2. **P3** 写 `BRPlayerPageCrawlerStealth`（仅覆写 `fetch_team_page` 接入 Scrapling Fetcher，其余继承现有基类一字不改）；
3. 再对一小批缺口（建议先拿 lineup Regular 缺口里的 ~20-30 个目标）做小规模验证。

上述构建属**执行动作**，超出此前"仅设计、不改动"的授权范围，需你明确批准后再做。
