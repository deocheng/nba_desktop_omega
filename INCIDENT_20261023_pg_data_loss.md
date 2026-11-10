# 🔴🔴 PG 数据事故报告：nba 库 4 张核心表文件缺失（2026-10-23）

**状态：✅ 已恢复。4 张受损表已从 9-11 备份回填活库（16,075,435 行，逐表/逐季校验与母盘完全一致），27 个索引约束逐字重建，3 个依赖视图恢复可用。剩余：2026-27 赛季增量待爬虫补抓、磁盘健康待检查。**

---

## 0. 用户指令执行结果

指令：「先把当前数据库备份，不要覆盖掉原来的备份文件」

| 项 | 结果 |
|---|---|
| 全量备份（原计划） | ❌ **不可能完成** —— pg_dump 在 `fct_pbp_shots` 上失败（堆文件在磁盘上缺失，见 §2） |
| 实际产出 1：数据备份 | ✅ `nba_partial_excl_broken4_20261023_003039.dump`（**587MB**，排除 4 张不可读表，145 张表数据全在内，TOC 校验通过） |
| 实际产出 2：结构备份 | ✅ `nba_schema_full_20261023_003039.dump`（**504KB**，含**全部**表结构，包括 4 张受损表的 DDL，供恢复用） |
| 是否覆盖既有备份 | ✅ **否**。既有 `nba_full_20260911.dump`（916MB）、`fiba_full_20260911.dump` 原封未动；新文件均为唯一时间戳名（`_20261023_003039`），且启动前有 `[ -e ]` 存在性守卫 |
| 失败残留物 | `nba_full_20261023_001638.dump.partial`（53MB 半成品，**已改名保留为证据**，未删除） |

---

## 1. 一句话结论

活动库（数据目录 **`/Users/deocheng/nba_pg`**，boot SSD，PG18，PID 957）中，**4 张核心表 + 3 个索引的堆文件在磁盘上整体消失**（catalog 完好、文件不在）：`player_gamelog`、`player_shot_chart`、`player_lineups`、`fct_pbp_shots`，合计约 **5.5GB / 70 万页**，占全库（9,008MB）约 **61%**。连 `SELECT ... LIMIT 1` 都读不了。

---

## 2. 症状与证据链

### 2.1 直接证据（服务端报错，PG 日志 `/Users/deocheng/Library/Logs/pg5433.log`）

```
2026-10-22 14:00:59 ERROR: could not open file "base/16384/63026": No such file or directory
  STATEMENT: SELECT count(*) FROM player_gamelog WHERE gameid='22600085' AND season=2027
  （此后 90 秒内同类错误 ×13，日更爬虫的去重检查全部失败）
2026-10-22 21:27:18 ERROR: could not open file "base/16384/59058"  (player_shot_chart)
2026-10-22 21:27:18 ERROR: could not open file "base/16384/56534"  (player_lineups)
2026-10-23 00:16:52 ERROR: could not open file "base/16384/61273"  (fct_pbp_shots, pg_dump COPY)
```

### 2.2 全量审计（1100 个关系逐一比对 catalog ↔ 磁盘文件）

**7 个关系"catalog 说有数据（relpages>0）但文件不存在"：**

| relfilenode | 关系 | 类型 | catalog 页数 | 8-5 旧副本中的文件大小 |
|---|---|---|---|---|
| 63026 | `public.player_gamelog` | 表 | 39,053 (305MB) | 319,922,176 B ✅在 |
| 59058 | `public.player_shot_chart` | 表 | 215,034 (1.68GB) | 1,073,741,824 + 687,816,704 B ✅在 |
| 56534 | `public.player_lineups` | 表 | 64,393 (503MB) | 527,507,456 B ✅在 |
| 61273 | `public.fct_pbp_shots` | 表 | 200,056 (1.53GB) | 1,073,741,824 + 565,116,928 B ✅在 |
| 59067 | `public.uq_player_shot_chart` | 索引 | 101,420 (792MB) | 830,832,640 B ✅在 |
| 61283 | `public.fct_pbp_shots_pkey` | 索引 | 42,746 (334MB) | 350,175,232 B ✅在 |
| 61839 | `public.uq_fct_shot` | 索引 | 40,979 (320MB) | 335,699,968 B ✅在 |

其余 1093 个关系文件全部在位；0 个"从未写过"的异常。

### 2.3 时间线（文件何时没的）

| 时间 (CST) | 事件 |
|---|---|
| 2026-09-11 12:55 | 全量备份 `nba_full_20260911.dump` **成功产出且含这 4 张表的数据** → 当时文件都在 |
| 2026-10-22 02:00:42 | PG 重启（[1903]） |
| **2026-10-22 10:23:01** | PG 重启为当前实例（**[957]**，`data_directory=/Users/deocheng/nba_pg`） |
| **2026-10-22 10:24** | `base/16384/` 目录 mtime —— 该目录内发生文件增删事件（重启后 1 分钟） |
| 2026-10-22 14:00:59 | 首个"文件缺失"错误暴露（日更爬虫撞上 player_gamelog） |
| 2026-10-23 00:16 | pg_dump 撞上 fct_pbp_shots → 本次全面审计 |

**结论：文件消失于 9-11 ～ 10-22 14:00 之间；最强指向 10-22 10:23–10:24（重启后即刻）。** 删除者无法从现有证据确定：shell 历史无相关 `rm` 记录、废纸篓为空、无 APFS 本地快照、无 TRUNCATE/DROP 痕迹（catalog 未变、fsm/vm 文件日期仍是 8-5）。

### 2.4 附带异常：磁盘写入严重变慢（健康警报）
同一日志内 checkpoint 写盘耗时（boot SSD）：

```
wrote 540 buffers (3.3%)  write=54.871 s   → ~0.10 s / 8KB 缓冲
wrote 956 buffers (5.8%)  write=97.098 s   → ~0.10 s / 8KB 缓冲
wrote 61  buffers (0.4%)  write=6.176 s    → ~0.10 s / 8KB 缓冲
```

读盘正常（今日 3.5GB 数据备份 60 秒完成 ≈ 58MB/s），**唯独写盘每缓冲约 100ms**。这不是正常 SSD 表现，建议尽快做磁盘健康检查（SMART / `diskutil verifyVolume`）。文件缺失与写入异常是否同源（SSD/文件系统故障）**无法确认**，但并存值得警惕。

### 2.5 回填时发现的第二个坑：陈旧 FSM 阻断插入路径（已解决）

首次 COPY 回填**全部 4 张表失败**，报同一个 `could not open file`（行号 783/280/211/462 ≈ 各表 64KB COPY 输入缓冲的行数，实为首行即败）。根因：**堆文件没了，但 `*_fsm`（自由空间映射）文件还在**，里面全是旧表的剩余空间记录 → 插入路径按 FSM 指引去读一个不存在堆文件的页面 → ENOENT。单行 INSERT 实验证实（连插一行都失败、且不产生文件）。

**解法：`TRUNCATE TABLE`**——TRUNCATE 会分配新 relfilenode 并丢弃旧 FSM/VM，插入路径随之恢复正常（已在回滚事务中验证：TRUNCATE → INSERT 0 1 → count=1）。正式回填即采用 TRUNCATE + COPY 链，一次成功。

> 教训：PG 数据文件被外部删除后，**光把数据灌回去不够，必须先让关系换存储身份**（TRUNCATE/重建表），否则陈旧 FSM/VM 会让 INSERT 静默失败。

---

## 3. 影响面

- **数据不可读**：4 张表约 1,650 万行（catalog 估计：gamelog ~1.5M、shot_chart ~6.09M、lineups ~680k、fct_pbp_shots ~7.83M）
- **3 个视图失效**：`v_player_shot_stats`、`v_team_clutch_shooting`、`v_player_clutch_by_distance`（均依赖 fct_pbp_shots）
- **无外键依赖**（pg_constraint 查询 = 0 行）→ 恢复时无引用完整性问题
- **DDL/约束/索引定义/序列全部完好**（都在 catalog 里；今天已产出全量 schema 备份）
- **未受影响**：`play_by_play`（PBP 逐回合）、`dim_games`、`game_metadata`、`team_pbp_raw`、`team_page_raw`、`player_onoff`、`player_advanced`、`player_per_game`、薪资/EPM 等全部可读；2026-27 开季 14 场 dim_games 数据完好
- **2026-27 赛季增量**：这几张表的新赛季数据本就极少（开季仅 10-20/10-21 两天），且日更爬虫 10-22 14:00 起去重检查即失败 → 新赛季增量实际损失≈0，重爬即可

---

## 4. 恢复资源盘点（三重保障）

| 来源 | 内容 | 时效 |
|---|---|---|
| ① `backups/nba_full_20260911.dump`（916MB） | 4 张表**完整数据**（TOC 已核实 TABLE DATA 条目在） | 截至 **9-11** |
| ② `/Volumes/12T/NBA/nba_pg/base/16384/` 旧副本 | 7 个缺失文件的**字节级原件**（大小与 catalog 页数精确吻合） | 截至 **8-5**（stale） |
| ③ 重爬（UC 后端已被证明可用 + raw_archive 24G 缓存） | 可补 9-11 → 10-22 缺口 | 最新 |

> ⚠️ 记忆库中"数据目录 = /Volumes/12T/NBA/nba_pg"**已过期**：那只是 8 月初的旧快照副本。活动库一直在 `/Users/deocheng/nba_pg`（9-11 备份、昨日爬虫落库、当前 postmaster.pid 均证明）。

---

## 5. 恢复方案（需用户裁定后执行）

### 方案 A（推荐）：数据级恢复，零停机、可回滚
1. ✅ **已完成**：恢复库 `nba_recovery_20261023`（9-11 全量 dump 还原，exit 0，活库零接触）。4 张表数据立即可查：
   `player_gamelog` **1,501,084** 行 / `player_shot_chart` **6,097,167** 行 / `player_lineups` **686,360** 行 / `fct_pbp_shots` **7,790,824** 行（合计约 1,607 万行）
2. ✅ **已完成（2026-10-23 01:05，用户授权「那就做吧」）**：活库回填。执行链：
   - drop 全部 27 个索引/约束（保留 FK 与 NOT NULL）→ 结构比对确认 4 表列名一致 →
   - **TRUNCATE 4 张表**（分配新 relfilenode 105655–105664，根除陈旧 FSM/VM，见 §2.5）→
   - COPY 回填 16,075,435 行（逐表 exit 0，行数与恢复库逐一相等）→
   - 按事故前定义**逐字重建 27 个索引/约束**（名称/定义 diff 完全一致）→
   - setval 序列（gamelog→5,434,005 / lineups→987,545 / fct→8,531,001，均取「丢失前序列值 ∪ max(id)」较大值防撞车）→ VACUUM (ANALYZE)
3. ⏳ **待办**：缺口重爬 9-11 → 10-22 的增量。经逐季分布比对，4 张表现状与 9-11 快照**完全一致**；2026-27 赛季（season=2027）gamelog 两库均为 0 行——新赛季数据本就未成功写入过（日更爬虫 10-22 14:00 起去重检查即失败），需在爬虫恢复后补抓（14 场，量小）。`fct_pbp_shots` 可由完好的 `play_by_play`（含 2026-27 的 14 场）重建，且能重建得比 9-11 更新（catalog 估计显示丢失前该表约有 4.3 万行增量）。
- 优点：不动 PG 文件、不停机、每步可验证可回滚
- 代价：9-11 之后的增量需重爬（量小）

### 方案 B（不推荐）：文件级恢复
停 PG → 从 /Volumes 旧副本拷回 7 个文件 → 起 PG。
- 秒级完成，但数据只到 **8-5**（比 9-11 dump 还旧），且存在把旧副本潜在损坏静默引入的风险；需先做新备份。**除用户明确要求外不建议。**

### 方案 C：纯重爬重建
全部靠爬虫重抓。shot_chart 爬虫虽在现役 registry，但源站 BR 的队级 zone 数据已变形状；全量重爬成本高、完整性难保证。仅作兜底。

---

## 6. 已做 / 未做（红线合规）

**已做**：全量关系审计、日志取证、两份新备份（唯一时间戳名、未覆盖任何既有文件）、半成品改名留存、新建恢复库（`CREATE DATABASE`，可 `DROP` 回滚）、**活库回填（用户 2026-10-23 01:00 授权「那就做吧」；全部在显式事务内执行，每步带行数/清单校验）**。

**未做**：未停/重启 PG、未以文件级方式触碰 PG 数据目录、未删任何既有备份、未动 git、未重爬（待爬虫链路就绪）。

## 7. 回填完成验证（2026-10-23 01:05）

| 校验项 | 结果 |
|---|---|
| 4 张表行数 vs 恢复库 | 1,501,084 / 6,097,167 / 686,360 / 7,790,824 **逐一相等** ✅ |
| 逐赛季行数分布 vs 恢复库 | gamelog 80 季输出全等；shot_chart/lineups/fct_pbp_shots 分布 **md5 逐一相同** ✅ |
| 索引/约束重建 | 27/27，与事故前 `pg_indexes` 快照**逐字 diff 一致**；无效索引 0；6 个 pkey/uq 约束在位（唯一索引建成即证明无重复键）✅ |
| 依赖视图 | `v_player_shot_stats`（25,430 行）/ `v_team_clutch_shooting` / `v_player_clutch_by_distance` **全部恢复可用** ✅ |
| 序列 | gamelog→5,434,005、lineups→987,545、fct_pbp_shots→8,531,001（≥ max(id) 且 ≥ 丢失前序列值）✅ |
| 终态体积 | 4 表合计 3,829MB（gamelog 498 / shot_chart 1,437 / lineups 386 / fct 1,508），全库 11GB ✅ |

## 8. 建议的立即动作

1. **磁盘健康检查**（写盘 0.1s/缓冲是最大疑点）：SMART 状态 / `diskutil verifyVolume /Users/deocheng` / 观察后续 checkpoint
2. ~~爬虫链路就绪后补 2026-27 赛季 gamelog（14 场，量小）~~ **✅ 已完成（2026-10-23 03:20）**：322 人全部入库（316 主爬 + 6 缺口补爬），14 场逐场与 PBP 对账零缺口；另产恢复后首个全量备份 `nba_full_20261023_013448.dump`。`fct_pbp_shots` 从 `play_by_play` 重建仍未做（可比 9-11 多约 4.3 万行）
3. 后续把"每日全量备份"固化为看门狗/日更管线的一环（本次若无 9-11 备份，损失将不可挽回）
4. 确认稳定运行一段时间后，可 `DROP DATABASE nba_recovery_20261023` 回收 ~9GB（留作对照母盘亦可）

---

## 附录：本次产物清单

| 文件 | 大小 | 说明 |
|---|---|---|
| `/Volumes/12T/NBA/backups/nba_partial_excl_broken4_20261023_003039.dump` | 615,313,127 B | 数据备份（排除 4 张不可读表） |
| `/Volumes/12T/NBA/backups/nba_schema_full_20261023_003039.dump` | 515,929 B | 全量结构备份（含受损表 DDL） |
| `/Volumes/12T/NBA/nba_pg_backup_20261023_003039.log` | — | 备份运行日志（exit=0、TOC 校验 1190 行 / 145 TABLE DATA） |
| `/Volumes/12T/NBA/nba_pg_backup_20261023_001638.log` + `.dump.partial` | 53MB | 首次全量备份失败残留（证据留存） |
| `/Volumes/12T/NBA/nba_recovery_restore_20261023.log` | — | 恢复库还原日志 |
| `/Volumes/12T/NBA/backups/recovery_data_4tables_20261023.dump` | 312,366,663 B | 4 张表 data-only 导出（回填中间产物，可留存） |
| `/Volumes/12T/NBA/backups/prebackfill_indexes_20261023.txt` | — | 回填前索引快照（diff 基准） |
| `/Volumes/12T/NBA/backfills/backfill_20261023.log` | — | 回填全流程日志（drop→truncate→restore→recreate→setval→vacuum） |
| `/Volumes/12T/NBA/backfills/recreate_indexes_20261023.sql` | — | 索引重建脚本（与事故前定义逐字一致） |
| 恢复库 `nba_recovery_20261023` | ~9GB | 9-11 全量快照（4 张丢失表共 1,607 万行可查；可随时 DROP） |

*取证命令与原始输出已逐条留存于本会话；本报告所有数字均来自实跑查询，无估算替代。*
