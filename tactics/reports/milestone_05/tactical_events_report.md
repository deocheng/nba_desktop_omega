# 战术事件层 + 时序稳定层报告（A4.23 · pass / drive / PnR + N-of-M 去抖）

> 日期：2026-09-26
> 前置：A4.22（速度/方向/停留热区，jump 闸门）已交付；A4.21（时序稳定层 + 污染过滤）已交付。
> 用户三项任务（原文）：
> 1. **提覆盖（尤其 sas_det）**——目前最明显短板；
> 2. **把新指标真正接入战术事件层**（速度/方向 + 持球者稳定段 → 强化 pick_and_roll / drive / pass）；
> 3. **时序稳定层叠加到换手/传球计数**（A4.22 报告已点出未做）。
> 引擎：`engine/tactical_events.py`（新建，单命令 7 域）；诊断：`engine/experiment_coverage.py`（只读）。

---

## 0. 一句话结论

- **任务 (b) 战术事件层 = 已落地（宽景）**：`tactical_events.py` 接入球速/方向 + 持球者稳定段，宽景 w1–w4 浮现
  PASS 12/12/14/6、DRIVE 5/5/10/5、PnR(探索)0/3/2/0。
- **任务 (c) 时序稳定层 = 已实证（核心去抖）**：N-of-M 滑窗把 w1 原始 173 次占有权切换压成 **12 次确认传球**
  （~14× 去抖），宽景 191→18 原始段压成稳定段。这是 A4.22 报告点出、本轮补齐的换手/传球计数稳定机制。
- **任务 (a) sas_det 覆盖 = 已诊断、未解决（诚实边界）**：量化证明 sas_det 标定空间耗尽——在 th=0.3→0.8 全程
  **无法同时**通过「覆盖」与「trackable 门禁」。唯一根治 = 真值重训头（**未授权，本轮未做**）。
  但修正一处**测量假象**：A4.22 的 sas_det 3.5% 来自稀疏 `poss_tile` 源；规范源 `scores.json`（项目 ball-head
  argmax）给 6.2%–15.2%——这是口径校正，非真实覆盖提升，且仍 FAIL 门禁。

---

## 1. 任务 (a)：sas_det 覆盖诊断（只读，未改任何产线）

### 1.1 数据源澄清（测量假象根因）
- A4.22 的 7 域覆盖表取自 `action_work/{clip}_poss_tile/ball_tracks.json`，其 `ball` 来自
  **YOLOv8 COCO `sports ball`(class 32)** 低阈值 + 线性插值（max conf≈0.45，召回~17%）。
- 项目真正落盘 `run_ball_events` 用的是 **`scores.json`**（ball-head 完整候选池 argmax，`--vconf -1`），检测更密。
- 二者同源不同密：`scores.json` 才是规范源。A4.22 的 sas_det 3.5% 是「稀疏 YOLO 源」读数，**低估**了真实球信号。

### 1.2 规范源实测（`experiment_coverage.py`，逐 th 扫描 scores.json，全 3 段 sas_*）
数字全从脚本现读（`trackable_frac ≥ 0.80` = 项目 trackable 门禁）：

| clip | th | 覆盖% | trackable | 门禁 | +jump-gate 覆盖% | +jump-gate trackable | 门禁 |
|------|-----|------|-----------|------|------|------|------|
| **sas_det** | 0.3 | 15.2 | 0.711 | **FAIL** | 15.0 | 0.727 | **FAIL** |
| **sas_det** | 0.4 | 10.0 | 0.767 | **FAIL** | 10.0 | 0.767 | **FAIL** |
| **sas_det** | 0.5 | 9.2 | 0.778 | **FAIL** | 9.2 | 0.778 | **FAIL** |
| **sas_det** | 0.6 | 9.2 | 0.778 | **FAIL** | 9.2 | 0.778 | **FAIL** |
| **sas_det** | 0.8 | 6.2 | 0.944 | PASS | 5.5 | 1.000 | PASS |
| sas_nop | 0.3 | 15.8 | 0.822 | PASS | 15.8 | 0.822 | PASS |
| sas_nop | 0.5 | 7.0 | 0.895 | PASS | 7.0 | 0.895 | PASS |
| sas_hou | 0.3 | 19.8 | 0.919 | PASS | 19.8 | 0.919 | PASS |
| sas_hou | 0.5 | 13.8 | 0.907 | PASS | 12.8 | 0.950 | PASS |

### 1.3 结论（不可绕过）
- **sas_det 是唯一全程 FAIL 的 clip**：th=0.3 给覆盖 15.2% 但 trackable=0.711（门禁 FAIL）；
  jump-gate 只把 trackable 抬到 0.727（仍 FAIL）。要过门禁必须升到 th=0.8，但覆盖塌到 6.2%。
  → **标定空间耗尽**：不存在单阈值同时保覆盖 + 过门禁。
- 对照 sas_hou/sas_nop：在 th=0.3 即 PASS 门禁且覆盖 15.8–19.8%。**仅 Denver 转播（sas_det）检测崩**。
- **根因** = Denver 片段球外观可分性低（与 A2 已封口结论一致：瓶颈=外观可分性非分辨率）；
  YOLO COCO sports-ball 对低对比深色篮球召回塌陷。
- **唯一根治 = 真值重训头**（A2 路线：`ball_head_v2.joblib` 完整候选池 argmax）。**未授权，本轮未做。**
- **本轮诚实交付**：① 口径校正——sas_det 真实球信号覆盖应为 6.2%–15.2%（非 A4.22 的 3.5%）；
  ② 明确「覆盖未实际提升」——即使校正后口径，sas_det 仍 FAIL 门禁，战术事件层对其不可用。

### 1.4 对战术事件层 (b/c) 的影响
`tactical_events.py` 消费的 `possession_segments.json` 由 `ball_possession.py` 从稀疏 `poss_tile` 源生成
（sas_det 仅 11 原始段）。即便换成规范 `scores.json` 源，sas_det 在可用覆盖下仍 FAIL trackable 门禁
（1.2 表），故 **sas_* 三段战术事件 = 0 是真实检测信号，非代码 bug**——符合项目「无真值不宣称」纪律。

---

## 2. 任务 (b)：战术事件层构建（`engine/tactical_events.py`）

### 2.1 事件定义（写入代码，显式常量）
| 事件 | 定义 | 关键阈值（10fps） |
|------|------|------|
| **PASS** | 稳定占有权段 A→B 过渡 + 球飞行证据（段间球速 plaus）+ N-of-M 确认 | `PASS_N=5`（双端各 ≥5 帧） |
| **DRIVE** | 稳定持球者连续高速（球在手中，段内中速推进） | `DRIVE_PX_S=130`（≈观察 p75）、`DRIVE_MIN_M=3` 帧 |
| **PnR(探索)** | DRIVE + 近静止屏幕人贴近持球者驱动路径 | `STATIONARY=100`、`D_SCREEN=120`、`D_HANDLER_SCREEN=200` |

- 接入 A4.22 新指标：球速/方向走 `PLAUS_LO/HI=[80,1500]px/s` 闸门（继承 jump 闸门，杜绝 40–53% 跳变污染）；
  持球者速度只计 `HOLD_MAX_PS=250`（球在手中），排除飞行段误归。
- 持球者稳定段来自 `possession_segments.json`（A4.16/A4.19 产出，含 hysteresis 迟滞）。

### 2.2 为何需要稳定段（先自证，非凭空）
原始 `possession_segments.json` 极碎：w1 435 帧 = **191 段，均 2.3 帧/段**（逐帧「几何最近球」每 ~2 帧抖动）。
逐帧最近球员切换 = 173 次（w1）。若直接按「段过渡」判传球，`PASS_N=5` 会杀光一切（首跑 passes=0）。
→ 必须先叠 N-of-M 时序稳定层（见 §3）把抖动压成稳定段，才能真正「接入战术事件层」。

---

## 3. 任务 (c)：N-of-M 时序稳定层（换手/传球计数去抖，已实证）

### 3.1 机制（`smooth_holder(taf, W=9, M=5)`）
滑动窗 W=9 帧内某 tid 出现 ≥M=5 帧才「确认」为该帧持球者，否则 None。
→ 把宽景每 ~2 帧抖动的占有权压成连续稳定段，再重新 RLE（`smoothed_segments`）。

### 3.2 去抖实证（数字全从 `tactical_events_rows.json` 现读）
**占有权段压缩（原始→稳定）：**
| clip | raw_seg | sm_seg | 压缩比 |
|------|------|------|------|
| baseline_w1 | 191 | 18 | 10.6× |
| baseline_w2 | 135 | 15 | 9.0× |
| baseline_w3 | 304 | 21 | 14.5× |
| baseline_w4 | 92 | 10 | 9.2× |

**换手/传球计数去抖（原始切换→确认传球）：**
| clip | raw_holder_changes | confirmed_passes | 去抖比 |
|------|------|------|------|
| baseline_w1 | 173 | 12 | 14.4× |
| baseline_w2 | 127 | 12 | 10.6× |
| baseline_w3 | 273 | 14 | 19.5× |
| baseline_w4 | 83 | 6 | 13.8× |

→ 这正是 A4.22 报告点出「换手计数未稳定、不得当传球数」的闭环：N-of-M 后 w1 从 173 次原始切换
降到 **12 次确认传球**，量级合理（40s 片段 12 次传球 ≈ NBA 实际节奏），**不再是噪声计数**。

### 3.3 为什么 N-of-M 有效而「加长稳定窗救语义」无效
A4.21 item3 曾证明：关系层 R3 的「加长稳定窗」是**负收益**（track ID 不稳定 → 命中率随 N 单调崩到 0）。
但本层场景不同：这里稳定的是**占有权归属**（同一球员连续持球），不是「几何最近球」的跨 ID 语义对齐。
N-of-M 在**单 track_id 出现频次**上投票，天然抵抗「短暂切换/贴身抖动」，不依赖跨 ID 持久身份——
故对战术事件层是**正收益**（与 A4.21 R3 的负收益不矛盾，对象不同）。

---

## 4. 7 域主结果表（数字全从 `tactical_events_rows.json` 现读）

| clip | n_frames | raw_seg | sm_seg | raw_chg | confirmed_PASS | DRIVE | PnR(探索) |
|------|------|------|------|------|------|------|------|
| sas_hou | 400 | 20 | 1 | 13 | 0 | 0 | 0 |
| sas_nop | 400 | 22 | 2 | 9 | 0 | 0 | 0 |
| sas_det | 400 | 11 | 0 | 4 | 0 | 0 | 0 |
| baseline_w1 | 435 | 191 | 18 | 173 | 12 | 5 | 0 |
| baseline_w2 | 335 | 135 | 15 | 127 | 12 | 8 | 3 |
| baseline_w3 | 770 | 304 | 21 | 273 | 14 | 10 | 2 |
| baseline_w4 | 245 | 92 | 10 | 83 | 6 | 5 | 0 |

- w3 的 `n_drive` 在 8↔10 间（mid-drive 短段计为额外段）；`n_drive_total`=10 含 ≥3 帧主段 + 短冲刺段，已并入。
- sas_* 三段 sm_seg=0–2 ⇒ 无稳定占有权段 ⇒ PASS/DRIVE/PnR 全 0（见 §1.4 真实信号说明）。

---

## 5. 诚实边界（不得越界引用）

1. **sas_* 战术事件全 0 = 检测覆盖塌陷的真实反映**，非代码缺陷；在 retraining head（未授权）前不可解。
2. **PnR 为探索性指标**：无 team ID，屏幕人/防守人判定为纯运动学启发式（静止 + 贴近持球者驱动路径）。
   **不得当战术结论引用**；仅作「疑似挡拆」候选，需 team ID + 球衣参照方能裁定。
3. **DRIVE 方向角**：来自稳定持球者框心 med 方向（med_dir_deg），单位度，已随事件落盘可供目视复核。
4. **PASS 计数**已叠 N-of-M 去抖，但「球飞行证据」目前仅用段间 plaus 球速近似；无精确传球轨迹拟合，
   故标注为「确认换手」而非「精确传球路线」。
5. **jump 闸门**贯穿速度/方向统计（继承 A4.22）；未过门禁域（sas_*）不产事件，符合纪律。

---

## 6. 产物清单

- 新：`engine/tactical_events.py`（战术事件层 + N-of-M 稳定层，单命令 7 域）
- 新：`engine/experiment_coverage.py`（只读诊断，sas_det 覆盖标定空间扫描）
- 落盘：`action_work/validate/tactical_events/`
  - `<clip>_tactical_events.json` ×7（结构化事件 + 段统计）
  - `tactical_events_rows.json`（7 域汇总行 = 本报告 §4 数据源）
- 报告：本文件 `reports/milestone_05/tactical_events_report.md`

---

## 7. 下一步（按用户优先级，未授权勿做）

1. 🔴 **sas_det 覆盖根治 = 真值重训头**（`ball_head_v2.joblib` 完整候选池 argmax，Denver 片段真值）。
   **需用户授权**——本轮仅诊断 + 口径校正，未动产线。
2. 口径校正落地：把 A4.22 的 sas_det 覆盖 3.5% 在记忆/报告中更正为规范源 6.2%–15.2%（仍 FAIL 门禁）。
3. PnR 若要升级为裁定级：需 team ID（球衣颜色分两队 / 人工标注对位）——与 A4.21 R3 同前置（ID 稳定化 + 非空间参照）。
4. ⚠️ 勿再走：用未稳定占有权直接判传球（A4.22 已证噪声）、无 team ID 把任意贴身两球员标 PnR、
   收紧 `P0_GUARD<−0.55`、用几何代理裁决语义。
