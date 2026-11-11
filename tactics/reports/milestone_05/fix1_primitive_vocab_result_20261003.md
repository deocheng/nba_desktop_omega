# A类修复·第一步结果：hit@k 0 → 18.2%（真实修复，但未达标）（2026-10-03）

> 对应老程授权「修」。第一轮修复（原语词表扩展 + 复杂度先验）跨 11 期复测结果。

## 一、修复内容（3 处，全部参数化可回退）
1. **新件 `engine/tactic_primitives_ext.py`** —— 扩展原语词表（原 `detect_primitives` 只产 5 种）。
   - 球/持球人派生：`PASS`(人换+球真走) / `DRIVE`(持球人朝筐) / `EXCHANGE`(近球两人x次序翻转) / `ROLL`(掩护后朝筐滚)
   - 掩护子类几何（平行追加，不覆盖原 DOWN/CROSS）：`STS`(同向) / `GHOST`(均非持球人) / `EXIT`(掩护人背离球) / `TOUCH`(极短)
   - 🔴 诚实边界：**不硬凑** `WEDGE/STAGGER/FLARE`(序列复合)、`SHORT_ROLL`、`ZONE_23`、`INBOUND`。
2. **`tactic_match.match/match_windowed`** —— 复杂度先验 `min_evidence`（默认 2）：cov 分母 = `max(len(need), min_evidence)`，解单原语泛型满分霸榜。`min_evidence=1` 退回旧公式。
3. **`tactic_notes_batch.py`** —— 接 `ext.augment` + `--min-evidence` / `--no-ext-primitives`（A/B 开关）。

## 二、复测结果（11 期，22 段，同一 seg-cap 45）
| 指标 | 修复前 | 修复后 |
|---|---|---|
| hit@1 | 0/11 (0%) | **1/11 (9.1%)** |
| hit@3 | 0/11 (0%) | **2/11 (18.2%)** |
| hit@k | 0/11 (0%) | **2/11 (18.2%)** |

- 命中：ep10 `pistol_5` **rank=1**（score 2.0/cov 0.667）；ep14 `horns` rank=2。
- 新原语真实触发（11期合计）：`SCREEN.TOUCH`×64 / `SCREEN.CROSS`×52 / `SCREEN.STS`×44 / `PASS`×36 / `SCREEN.EXIT`×11 / `SCREEN.GHOST`×9。
- **key_primitive 门放行 3/13 → 7/13**；top1 不再被单原语泛型垄断（出现 `pistol_5`/`sts`/`touch_screen` 等多原语模型）。

## 三、未达成部分（诚实诊断，不粉饰）
1. **`DRIVE` / `EXCHANGE` / `ROLL` 真实 0 次**。经内部量核查：ep10_s0 全 280 帧中「持球人朝筐且有位移」仅 **1 帧**，连续 run≥3 为 **0** ⇒ **是数据事实（该片段持球人几乎全程不在朝筐移动/球权多在转移站定），非判据阈值缺陷**。补这三类需**含突破/换防的语料**，非调参。
2. **6/13 真值仍 key 受阻**：`zone_23`/`slob`（难原语，按诚实边界未做）、`exchange_down`(EXCHANGE 0次)/`roll`(ROLL 0次)/`short_roll`(0次)（原语已实现但样本无触发）、`wedge_screen`(WEDGE 序列复合未做)。
3. **hit@k 18.2% 仍低于可用线**；且 GT 为期级标题战术、段级未必含该战术（段级口径未收紧，构成独立上限）。

## 四、结论
- 第一步**真实有效**：把「结构性不可达」从 11/13 降到 6/13，hit@k 首次从 0 动到 18.2%，**根因判断（原语词表缺口为主因）得到验证**。
- 但 hit@k 未达标。下一步的杠杆**不在继续硬补原语**，而在：① 换/加**含突破、换防、界外球**的语料段（让 DRIVE/ROLL/EXCHANGE 有触发机会）；② 收紧**段级 GT 口径**（否则分母不对）；③ 决定是否投入**序列复合原语**(WEDGE/STAGGER)。
- **纪律**：不为提高 hit@k 而硬凑判据（保持数字可证伪）。

## 五、产物
- `action_work/tactic_notes_batch_fix1/batch_results.{json,csv}`（修复后，11期）
- `action_work/tactic_notes_batch_kpi/batch_results.{json,csv}`（修复前对照，11期）
- `action_work/tactic_notes_batch_smoke/`（冒烟 ep10 + `/tmp/ep10_s0_overlay/` 视觉自证）
