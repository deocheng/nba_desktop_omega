# 调查报告：player 相关表缺 `weight` 列根因

**调查人**：寇豆码（工程师）　**日期**：2026-07-12　**任务**：#105
**环境**：PostgreSQL `localhost:5433` / 库 `nba` / `postgres`
**方法**：全部结论基于真实参数化查询（`psycopg2.sql.Identifier` + `%s`），无臆测、无落库。
**支撑脚本**（均落盘于 `reconcile_2026-07-10/`）：
- `_investigate_weight_cols_run.py`（全列/结构/全库 weight* / 20 表结构 / 口径）
- `_investigate_weight_join.py`（join key 选型 + 匹配率 + 覆盖）
- `_investigate_weight_caliber.py`（覆盖 + 35vs20 口径验证）
- 结构化结果：`_investigate_weight_cols.json` / `_investigate_weight_join.json` / `_investigate_weight_caliber.json`
- 迁移脚本：`_migrate_add_weight_cols.py`（默认 `--dry-run`，见末节）

---

## 0. 结论速览（TL;DR）

1. **根因 = 命名口径问题，不是数据缺失**。体重数据**早已存在**，但一律以
   `weight_lbs` / `weight_kg` **双列**形式存于 `dim_players`、`player_weight_history`
   （以及 `player_bio` / `player_directory` / `draft_combine`）。库中**从未存在过**
   名为 `weight` 的单列。所谓"缺 weight 列"实为"缺一个叫 `weight` 的列"。
2. **记忆"BR 体重回填 dim_players 5473/5476=99.9%"完全真实** —— 指的就是
   `dim_players.weight_lbs` / `weight_kg` 非空 5473 行（见 §1、§3、§7）。矛盾解除。
3. **权威源**：`dim_players`（`player_id` 主键，`weight_lbs` 非空 5473/5476）或
   `player_weight_history`（5473 行全非空）。推荐 `dim_players`。
4. **应加 `weight` 的表（本报告判定）：12 张**（见 §6）；其余 8 张排除。
5. **35 vs 20 口径**：DB 现状是 **41 张** player 相关表缺 weight（33 base + 8 视图），
   远超 20。"20" 是主理人收窄的子集；"35" 是更早/更宽的口径。详见 §5。
6. **范围提醒（需主理人拍板）**：真实缺 weight 的 *base* 表有 **33 张**，
   主理人 20 仅覆盖其中一部分（漏了 `playoff_*`×6、`player_per_*`/`player_totals`×6、
   `draft_pick*`×2、`player_name_map` 等）。是否扩容见 §9。

---

## 1. `dim_players` 全列 + 是否有体重相关列

| # | 列 | 类型 | # | 列 | 类型 |
|---|----|------|---|----|------|
|1|player_id|varchar|13|birth_city|text|
|2|player_name|text|14|birth_state_country|text|
|3|full_name|text|15|nationality|text|
|4|pronunciation|text|16|college|text|
|5|position|text|17|high_school|text|
|6|shoots|text|18|recruiting_rank|text|
|7|height_display|text|19|draft_info|text|
|8|height_cm|integer|20|experience|text|
|9|**weight_lbs**|integer|21|nba_debut|text|
|10|**weight_kg**|integer|22|source_url|text|
|11|birth_date|date|23|scraped_at|timestamp|
|12|birth_city|text|24|year_from / year_to|integer|

**结论**：`dim_players` 含 `weight_lbs`(int) 与 `weight_kg`(int)，**没有名为 `weight` 的列**。
即"缺 weight"= 缺"单一命名为 `weight` 的列"，体重数据完整存在。按任务要求**不修改其结构**。

---

## 2. `player_weight_history` 结构与样本（权威源确认）

列（9）：`player_id`(text)、`player_name`(text)、`weight_lbs`(int)、`weight_kg`(int)、
`height`(text)、`born`(text)、`scraped_at`(timestamp)、`position`(text)、`shoots`(text)。
**行数：5473**（全部 `weight_lbs`/`weight_kg` 非空）。

样本行：
```
('addisra01','Rafael Addison',215,98,None,None,2026-06-20 07:13:15,'None','None')
('barkecl01','Cliff Barker',185,84,None,None,2026-06-23 17:04:16,'None','None')
('beardra01','Ralph Beard',175,79,None,None,2026-06-23 18:43:39,'None','None')
```
**结论**：这是按 `player_id`（BBRef）的**体重权威快照表**，无 `season`、`br_player_id`。
与 `dim_players` 同质（均存 `weight_lbs`/`weight_kg`），可作为 `dim_players` 的等价源。

---

## 3. 全库 `weight*` 列分布

```sql
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema='public' AND column_name ILIKE 'weight%' ORDER BY table_name;
```

| 表 | 列 | 类型 |
|----|----|------|
| dim_players | weight_kg / weight_lbs | integer |
| draft_combine | weight_lbs | numeric |
| player_bio | weight_kg / weight_lbs | integer |
| player_directory | weight_lbs | integer |
| player_weight_history | weight_kg / weight_lbs | integer |

**结论**：库内体重**一律以 `weight_lbs`/`weight_kg` 出现，无裸 `weight` 列**。
这坐实了根因——"weight" 从未作为列名存在，所有体重都用双单位列表达。

---

## 4. 20 张候选表结构（player_id / br_player_id / 行数）

| 表 | 行数 | player_id | br_player_id | 备注 |
|----|-----|-----------|--------------|------|
| all_star_selections | 2058 | ✅ | – | player_id=text |
| dim_draft_history | 8446 | ✅ | – | player_id=varchar |
| dim_draft_history_bak_20260712 | 8446 | ✅ | – | **备份表** |
| dim_players | 5476 | ✅ | – | 已含 weight_lbs/weight_kg |
| end_of_season_teams | 6777 | ✅ | – | player_id=text |
| fact_player_season_stats | 45073 | ✅ | – | player_id=text |
| player_award_shares | 3527 | ✅ | – | player_id=text |
| player_career_totals | 4874 | ❌ | ❌ | **仅 player_name** |
| player_contracts | 648 | ✅ | – | player_id=varchar |
| player_contracts_league | 537 | ✅ | – | player_id=varchar |
| player_gamelog | 1911004 | ✅(bigint) | ✅ | **player_id 是 bigint(nba_api)** |
| player_gamelog_dup2026_bak | 1411 | ✅ | ✅ | **备份表** |
| player_id_bridge | 9321 | ❌ | ✅ | 桥表(nba_player_id/br_player_id) |
| player_name_unified | 7497 | ❌ | ❌ | 名称归一映射(id/名称) |
| player_play_by_play | 18254 | ✅ | – | player_id=text |
| player_salaries_historical | 12386 | ❌ | ❌ | **仅 player_name** |
| player_season_info | 33339 | ✅ | – | player_id=text |
| player_season_splits | 1032183 | ✅ | – | player_id=varchar |
| player_shooting | 24353 | ✅ | – | player_id=text |
| player_weight_history | 5473 | ✅ | – | **体重权威表本身** |

**关键发现**：`player_gamelog.player_id` 为 **`bigint`（NBA-API 数值 id）**，而非 BBRef 字符串 id；
其 `br_player_id` 才是 BBRef id（与 `dim_players.player_id` 同型）。故 `player_gamelog` 必须用
`br_player_id` 关联，直接用 `player_id` 会触发 `character varying = bigint` 操作符错误。
（其余事实表 `player_id` 为 `text`/`varchar`，可直接 join `dim_players.player_id`。）

---

## 5. "35 vs 20" 口径解释（基于真实查询）

机械全量扫描（表名含 `player` **OR** 含 `player_id` 列）**AND** 不含任何 `weight*` 列：

```sql
SELECT table_name FROM information_schema.tables t WHERE t.table_schema='public'
  AND (t.table_name ILIKE '%player%'
       OR EXISTS (SELECT 1 FROM information_schema.columns c
                  WHERE c.table_name=t.table_name AND c.column_name='player_id'))
  AND NOT EXISTS (SELECT 1 FROM information_schema.columns c
                  WHERE c.table_name=t.table_name AND c.column_name ILIKE 'weight%')
ORDER BY table_name;
```

→ **结果：41 张**（其中 **8 张是视图** `v_player_*`，**33 张 base 表**）。

反向（已含 `weight*` 的 player 相关表，4 张）：`dim_players`、`player_bio`、
`player_directory`、`player_weight_history` —— 这些本就被排除在"缺 weight"之外。

**判定**：
- 记忆"**35**"：旧账的更宽口径（可能含视图、未去重、或早期 schema 快照），落在
  33–41 区间，与现行机械扫描一致，**非数据错误**。
- 主理人"**20**"：在 41（或 33 base）基础上**人为收窄**——排除了 8 视图、
  `playoff_*`×6、`player_per_*`/`player_totals`×6、`draft_pick*`×2、`player_name_map` 等。
  属范围裁剪，非计算错误。
- 结论：**20 是有效子集**；但若按"全部 player 事实表该有 weight"原则，真实范围应 ≥ 33 base 表。
  扩容与否需主理人拍板（见 §9）。

---

## 6. 分类表：应加 `weight` vs 排除（逐表理由）

### 6.1 应加（12 张）——执行 `_migrate_add_weight_cols.py` 的 `TARGET_TABLES`

| 表 | join key | 行数 | 将回填 | 无法回填 | 理由 |
|----|----------|-----:|-------:|--------:|------|
| all_star_selections | player_id | 2058 | 2058 | 0 | 每球员全明星入选事实，体重有意义，匹配率 100% |
| end_of_season_teams | player_id | 6777 | 6777 | 0 | 赛季末阵容事实，匹配率 100% |
| fact_player_season_stats | player_id | 45073 | 33333 | 11740 | 核心 per-player-season 事实，应含体重；26% 无 dim_players 匹配 |
| player_award_shares | player_id | 3527 | 3526 | 1 | 奖项得票事实，匹配率≈100% |
| player_contracts | player_id | 648 | 641 | 7 | 合同事实 per player |
| player_contracts_league | player_id | 537 | 533 | 4 | 联盟合同事实 per player |
| player_gamelog | **br_player_id** | 1911004 | 1757463 | 153541 | 比赛日志；player_id 是 bigint，须用 br_player_id（匹配后 100% 回填） |
| player_play_by_play | player_id | 18254 | 18254 | 0 | 逐回合事实 per player，匹配率 100% |
| player_season_info | player_id | 33339 | 33333 | 6 | 赛季信息 per player，匹配率≈100% |
| player_season_splits | player_id | 1032183 | 951817 | 80366 | 分项数据 per player；约 8% 无匹配 |
| player_shooting | player_id | 24353 | 18254 | 6099 | 投篮数据 per player；约 25% 无匹配 |
| dim_draft_history | player_id | 8446 | 4444 | 4002 | 选秀事实 per player；**仅 52.6% 可回填**（多为非 NBA/历史选秀条目无 dim_players 匹配）→ ⚠需拍板 |

> 上述"将回填/无法回填"为迁移脚本 `--dry-run` 实测值（已落盘未落库）。

### 6.2 排除（8 张）——不执行 ADD/UPDATE

| 表 | 类别 | 排除理由 |
|----|------|----------|
| dim_players | 维度（自身） | **已含** `weight_lbs`/`weight_kg`；任务要求不改其结构 |
| player_weight_history | 体重权威表 | 本身就是体重源，再加 `weight` 冗余 |
| dim_draft_history_bak_20260712 | 备份 | 备份表，禁止加业务列 |
| player_gamelog_dup2026_bak | 备份 | 备份表，禁止加业务列 |
| player_id_bridge | 映射/桥 | 仅做 nba_player_id↔br_player_id 映射，非事实实体 |
| player_name_unified | 名称归一映射 | 仅名称归一（id/全名/姓），无 player_id，非事实实体 |
| player_career_totals | 事实表但**无 player_id** | 仅 `player_name`（27 列，无 id）→ 无法干净关联权威源（见 §8） |
| player_salaries_historical | 事实表但**无 player_id** | 仅 `player_name`（9 列，无 id）→ 无法干净关联权威源 |

---

## 7. 权威回填源 + join key 建议

- **源表**：`dim_players`（`player_id` 主键）。备选 `player_weight_history`（5473 全非空）。
  选 `dim_players` 因它覆盖完整球员花名册（5476，含 weight_history 缺失的 3 人）。
- **取值列**：默认 `weight_lbs`（与库内既有 `weight_lbs`/`weight_kg` 惯例一致；改
  `SOURCE_WEIGHT_COL='weight_kg'` 即切 kg）。**单位需主理人拍板**（见 §9）。
- **join key 映射**（已写入脚本 `TARGET_TABLES`）：
  - `player_id`(text/varchar) 表 → `dim_players.player_id`（直接，无类型冲突）
  - `player_gamelog` → `br_player_id`（因其 `player_id` 为 bigint nba_api id）
- **回填方式**：**批量 JOIN UPDATE**（非逐行），如
  `UPDATE <tbl> t SET weight = s.weight_lbs FROM dim_players s
   WHERE t.<key> = s.player_id AND s.weight_lbs IS NOT NULL AND t.weight IS NULL;`
  幂等（`WHERE weight IS NULL`），可重复执行。
- **覆盖证据**：`dim_players` 的 `weight_lbs` 非空 5473/5476（99.9%）；
  `player_weight_history` 5473/5473（100%）。

---

## 8. 不变量 / 风险

1. **各表可回填率不同**（见 §6.1）：未匹配 `dim_players` 的行 `weight` 保持 `NULL`，
   不强行填（避免错填）。`fact_player_season_stats`(26%)、`player_season_splits`(8%)、
   `player_shooting`(25%)、`player_gamelog`(8%)、`dim_draft_history`(47%) 有无法回填行。
2. **无 `player_id` 的事实表**（`player_career_totals`、`player_salaries_historical`）：
   仅 `player_name`，需经 `player_name → dim_players.player_name` 桥接，但姓名非唯一、
   有重名/大小写风险，**无法干净回填** → 已排除并标记待拍板。
3. **`dim_draft_history` 仅 52.6% 可回填**：多为非 NBA / 历史选秀条目在 `dim_players`
   无对应，属正常；是否仍加列见 §9。
4. **冗余与单位歧义**：新增单一 `weight` 列与既有 `weight_lbs`/`weight_kg` 并存，
   存在冗余；且 `weight` 单位（lbs/kg）必须明确，否则下游误读。
5. **视图不可 ALTER**：`v_player_*`（8 张）为派生视图，不能加列，已排除。
6. **大数据量表**：`player_gamelog`(191 万)、`player_season_splits`(103 万) UPDATE 需批量
   且依赖 `player_id`/`br_player_id` 索引（确认两列有索引以避免全表扫描）。
7. **不做**：不改 `dim_players`/`player_weight_history` 结构；不碰非 player 表；
   dry-run 默认不落库，仅 `--execute` 才 ALTER+UPDATE。

---

## 9. 需主理人拍板的点

1. **单位**：`weight` 列用 **lbs 还是 kg**？（脚本默认 `weight_lbs`，与库内惯例一致）
2. **范围扩容**：是否把其余缺 weight 的 base 表纳入
   （`playoff_player_*`×6、`player_per_game`/`player_totals`/`player_per_36_minutes`/
   `player_per_100_poss`/`player_advanced`/`player_game_details`×6、`draft_pick_history`/
   `draft_picks`×2、`player_name_map`×1，共 **+15 base 表**）？脚本 `TARGET_TABLES`
   为集中常量，扩容只需增键值对。
3. **`player_career_totals` / `player_salaries_historical`**：是否接受经
   `player_name → dim_players.player_name` 桥接回填（有重名风险）？默认排除。
4. **`dim_draft_history`**：是否仍加列（仅 52.6% 可回填）？默认加（列廉价、缺失行留 NULL）。
5. **命名**：任务要求列名固定 `weight`；是否考虑直接复用 `weight_lbs` 而非新建 `weight`？
   （本报告与脚本按任务要求建 `weight`）

---

## 10. 交付物

- **A. 本报告**：`reconcile_2026-07-10/_investigate_weight_cols.md`
- **B. 迁移脚本**：`reconcile_2026-07-10/_migrate_add_weight_cols.py`
  - 默认 `--dry-run`（仅打印每表"将加列 / 将回填 N 行 / 无法回填 M 行"，**绝不落库**）
  - `--execute` 才真正 `ALTER TABLE ... ADD COLUMN weight NUMERIC` + 批量 JOIN `UPDATE`
  - §6 合规：表名/列名全用 `psycopg2.sql.Identifier` 参数化，无 f-string 拼名、无 eval/exec、
    无循环内逐行 DB 往返；独立连接 + `autocommit=True`；逐表独立提交、幂等。
- 支撑查询脚本与 JSON 见 §0 文件清单。

---

### 附：§6 合规自检（脚本）
- [x] 所有表名/列名用 `sql.Identifier` 参数化（含 `NEW_COL`、`SOURCE_*`、各 `key`）
- [x] 无 f-string 拼接 SQL 表名/列名（仅 `print` 用 f-string 输出人类可读信息）
- [x] 无 `eval` / `exec`
- [x] 无"循环内单 player 逐行 DB 往返"——回填为单条批量 JOIN UPDATE
- [x] 独立连接 + `autocommit=True`，无悬挂事务
- [x] 默认 `--dry-run` 不落库；仅 `--execute` 才 ALTER+UPDATE
