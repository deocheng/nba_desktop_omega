# 新赛季（2026-27）全量爬取计划 · v1

> 状态：**计划文档，未执行**。所有爬取/改码动作待用户批准后实施。
> 制定依据：已加载 `nba-br-crawler` / `nba-dunksandthrees-epm` 方法论；已只读核验库内现状（见文末"已核验事实"）。

---

## 0. 范围与前提（已核验事实）

- 当前各表最大赛季 = **2026**（= 刚结束的 2025-26 NBA 赛季，BR 以结束年命名）。
- **新赛季 = 2026-27 NBA 赛季，BR 标记为 `2027`**。季前赛 ≈ 2026-09 末 / 10 月初，常规赛 ≈ 2026-10 下旬，季后赛 ≈ 2027-04。
- on-off 已完成（covered 14,565 = universe 14,565，缺口 0）。
- `dim_games` 字段仅有 `season` + `season_type`，**无独立 preseason 列** → 季前赛如何存储待 Phase 0 查清。
- `player_id_bridge`：`(nba_player_id, player_name, br_player_id, match_strategy)`；新秀初始 `br_player_id=NULL`，日后补链。

---

## 1. 总体原则（沿用既有铁律）

| 原则 | 做法 |
|---|---|
| cache-first | 先 `save_html` 落 `raw_archive` 再解析；线上只"请回本地"。 |
| 本地去重 | gap 查询 `NOT EXISTS` / `LEFT JOIN _404` 跳过已落库；修复一律走本地重放，零 BR 重抓。 |
| 限速 + CF 熔断 | PBP ≤15 请求/分；gamelog 3–6s/人；CF 全局熔断自恢复（`common/cf_breaker`）。 |
| 榨干字段 | 页面所有结构化字段都抽，原始 HTML 必落盘。 |

---

## 2. 数据集范围（全量）

**BR 域**
- `player_shooting`（投篮分布）
- `player_lineups`（5/4/3/2-man，Regular + PO `lineups-post-{n}-man`）
- `player_onoff`（Regular + PO `on-off-post`）
- `player_gamelog` / per_game / advanced / per_36 / per_100（`nba_daily_crawler --datasets player`）
- `play_by_play`（PBP，BR 文字表、**无坐标**）
- `dim_games` 球队/赛程补全（`br_fill_teams` / `games`）

**EPM 域（dunksandthrees.com）**
- `player_epm`（`/epm` 预测版 + `eskills` 历史版，PK 含 `source`）
- `player_epm_actual`（`/epm/actual`）
- 全历史 `eskills` 遍历（2852 人，自动含 2026-27 新季）

---

## 3. 🔴 新秀发现机制（核心难点）

**现状**：球员级爬虫的 `(slug, season)` 宇宙来自 `player_shooting` —— 2026 届新秀**不在其中** → 纯靠它会漏掉全部新秀。必须加**独立发现层**。

**方案（三层交叉，每轮重建宇宙）**：
1. **dim_games 参赛者派生**：2026-27 比赛进 `dim_games` 后，从 boxscore/PBP 提取参赛 `player_id` → 经 `bridge` 解析 BR slug（新 slug 走 名称→slug 规则或 lookup）。
2. **EPM 球员索引**：dunksandthrees 任意页 `resolve(1)` 搜索索引（`rookie_year` 至 2026，含现役新秀）→ 直接给 `nba_player_id`，过 `bridge`。
3. **BR 联盟赛季花名册页**（若有）：逐赛季 roster 列出全部球员 slug。

→ 三源 `UNION` 成 2026-27 的 `(slug, season)` 宇宙，与"已落库"做 gap，只爬缺口。
→ 新秀 `bridge` 缺失：先以 `br_player_id=NULL` 入库（EPM 技能已验证此路径），赛季中/末刷新 `bridge` 自动补链。

---

## 4. 本地缓存去重（避免重复爬取）

- 所有 fetch 先 `save_html` 到 `raw_archive/br_players/{slug}/{dataset}_{year}.html`（原子写）。
- 解析前 `is_cached` 命中即返、零请求；未命中才线上抓。
- 新赛季首跑：缓存全空 → 全量线上抓**一次**；之后每轮只补缺口（赛季进行中增量）。
- **修复/补字段一律本地重放**（`rework_from_archive` / `backfill_*`），不重抓。

---

## 5. 从季前赛开始（编排）

- 用 `br_crawler.py --loop --since 2026-09-25`（或季前赛开赛日）启动**向前增量**编排：自动捕获 季前赛→常规赛→季后赛 的新比赛。
- 注意分层：
  - **比赛级**（PBP / gamelog / 赛程）：季前赛即有，开赛即爬。
  - **球员赛季聚合页**（shooting / lineup / onoff）：BR 按赛季聚合，随比赛累积；编排**每轮重爬该赛季页**（cache-first，仅新增比赛数据被补入）。故"从季前赛起"= 开赛即挂上，无需等常规赛。
- EPM：季前赛样本小、EPM 几乎不动；`/epm` 的 `2027` 季页面随赛季推进自动出现，每周 `--force` 刷新即可。

---

## 6. 运维硬化（必须，源于本次 on-off 故障）

- 🔴 **修 auto-runner 死循环**：`run_player_onoff_auto.sh` / `run_player_lineup_auto.sh` 的裸 `while true`（仅 `gap=0` 才退出）遇"少数不可抓玩家"会**永不退出、每几秒重连 Chrome 开关窗口**。加守卫：**gap 连续 N 轮不降 → 自动把卡住玩家隔离进 `_404` 并 `exit DONE`**。
- 保留 cache-first / CF breaker / 限速 / `caffeinate -s` 防睡眠 kill。
- 双 Chrome 实例隔离：lineup=9222，onoff=9223，显式 `export CHROME_CDP_URL`。

---

## 7. 分阶段时间线（预估）

| 阶段 | 时间窗 | 动作 |
|---|---|---|
| **Phase 0** 准备 | 现在~开赛前 | ① 查清 `dim_games` 季前赛存储方式 + `season_type='Preseason'` 处理；② 建"新秀发现层"（§3）；③ 修 auto-runner 守卫（§6）；④ 复用既有 DDL（表 PK 已按 season 设计，直接追加 2027）。 |
| **Phase 1** 季前赛 | ~2026-10 | 挂上 `--loop --since`；PBP + gamelog 季前赛；EPM 开始跟踪 2026-27。 |
| **Phase 2** 常规赛 | ~2026-10 下旬 | 全量球员页爬取（veterans 走 `player_shooting` 宇宙 + 新秀走发现层）；EPM 每周刷新。 |
| **Phase 3** 季后赛 | ~2027-04 | PO 表（`lineups-post-{n}-man` / `on-off-post`）parser 已修，自动纳入。 |
| **Phase 4** 休赛期 | ~2027-07 | EPM 全历史终版快照归档；刷新 `bridge` 补新秀链。 |

---

## 8. 风险与待确认

- ❓ `dim_games` 季前赛如何表示（无独立列）→ Phase 0 必须查清，否则"从季前赛开始"无法对齐赛程。
- ❓ BR 是否发布季前赛 PBP / lineup / onoff（历史看 PBP 仅子集）→ 季前赛覆盖率可能低，属预期。
- ⚠️ auto-runner 守卫必须先在**现有** lineup / onoff 上修好（lineup 当前缺口 3,243 推进中，同样会撞死循环），再上线新赛季。

---

## 附：已核验事实（只读，2026-07-25）

```
on-off: covered 14,565 对 = universe 14,565 对 → 缺口 0
        Regular 2,859 人 / Playoffs 1,664 人
        隔离 _404: chandty01/2020, hendrta01/2024, richapo01/1998, richapo01/1999
各表最大赛季: shooting/lineups/onoff/gamelog/epm/epm_actual/pbp 均 = 2026
dim_games 字段: season, season_type（无 preseason/stage 列）
player_id_bridge: (nba_player_id text, player_name varchar, br_player_id varchar, match_strategy varchar)
```
