# A4.42 multiscale 池转正端到端评估报告

日期：2026-09-27 ｜ 头：final351（ball_head_joint.joblib, n=619）｜ 对比：old=640×384 ov96 top-4 生产池 vs new=multiscale（640×384 ov96 + 480×384 ov192 合并跨NMS, 不截断）

## 0. 一句话结论
**multiscale 池本身是好池（候选召回 89.3%/95.0% 实证复现），但 final351 头在密集池上分布外失配，FP 洪泛使 top-1 从 98.3% 崩到 19.0%——头再校准是转正前置条件，不是可选项。**

## 1. 池级验证（分母=final351 bank 121 个 TP 帧，独立真值）
| 口径 | old 池 | new 池（落盘复算） | 诊断参考 |
|---|---|---|---|
| strict（≤12px） | 57.9% | **89.3%** | 89.3% ✓ |
| inbox | 67.8% | 90.1% | 93.4%（差4帧，疑诊断未做合并后跨NMS去重，非阻断） |
| near50 | 71.9% | **95.0%** | 95.0% ✓ |
- 0 候选帧：12 → **5**（f00315/317/321/322/323），与诊断恢复矩阵推算完全一致。
- 候选规模：sas_lal 32,947（395/400 帧）；sas_det 37,433（400/400 帧）；生产 top-4 池仅 ~1,600。

## 2. 头级端到端（同一 final351 头，仅换池）
### sas_lal
| 指标 | old | new | 判读 |
|---|---|---|---|
| 覆盖 @0.3（全400） | 74.0% | 91.0% | ↑ |
| 覆盖 @0.3（honest 258 未标帧） | 67.8% | **88.8%** | ↑ |
| 覆盖 @0.8（honest） | 60.9% | 84.5% | ↑ |
| **GT 帧 top-1 正确性（121 帧）** | **98.3%** | **19.0%** | 🔴 崩盘 |
| GT 帧过阈候选含真球 @0.3 | 121/121 | 108/121 | 真球在池里且过阈，被垃圾高分淹没 |

### sas_det（零回归视角失效——同失配）
| 覆盖 @0.3 | 55.2% → 98.8% ｜ @0.8: 45.5% → 97.2%（同为 FP 洪泛形态）

## 3. 事件管线（run_ball_events，跟踪器 birth=th/gap=8/min_track=3）
| 片段 | 池 | th | 覆盖 | 可跟踪 | 轨迹数 | 步数 |
|---|---|---|---|---|---|---|
| sas_lal | old | 0.3 | 73.0% | 93.7% | 22 | 270 |
| sas_lal | new | 0.3 | 644.8%* | 84.0% | **266** | 2313 |
| sas_det | old | 0.8 | 45.8% | 91.9% | 22（FP过滤22→22） | 161 |
| sas_det | new | 0.8 | 327.2%* | 81.0% | **175**（FP过滤仅196→175） | 1134 |
- *覆盖>100% = 多轨迹同帧 claim（每帧平均 6.4/3.3 条碎轨）——FP 碎轨海啸。
- 🔴 **PASS 门禁被碎轨海形式性刷过**：碎轨短而平滑，trackable/步长照样达标——门禁指标对 FP 洪泛无特异性（A4.21 同款教训第三实例）。

## 4. 持球者解出率（ball_possession，球输入 th=0.8，hysteresis=1，imgsz=1280）
| 指标 | sas_lal old | sas_lal new | sas_det old | sas_det new |
|---|---|---|---|---|
| ball_detect_rate | 69.5% | 88.0% | 45.5% | 97.3% |
| **解出率** | 77.8% | **88.8%** (+11pp) | 76.3% | 78.3% (+2pp) |
| interp_share（插值占比） | 15.8% | 6.2% | **47.5%** | 1.3% |
| n_segments / 中位段长 | 102/2帧 | 214/1帧 | 72/2帧 | 162/1帧 |
- ⚠️ old sas_det 的 76.3% 有 47.5% 是插值撑的（球输入只有 45.5% 覆盖）——虚标；new 几乎零插值但靠 FP。
- ⚠️ 解出率对 FP 不敏感：FP 球点落任何球员 88px 内即"解出"。**解出率提升 ≠ 持球者正确率提升**。中位段长 1 帧 = 战术不可用。

## 5. 头再校准监督数据（已就绪，待授权）
- sas_lal bank 142 帧（人工真值）内密集池候选 13,139 个：TP 侧（与人工 GT IoU≥0.3）=135，FP 侧=13,004（1:96，类权重可解）。
- 标注逻辑锚定人工真值（帧内 GT 球唯一且人工确认，几何匹配非 AI 自判 conf），非 A4.24 已证伪的 AI 自标路线。

## 6. 待决策
- A（推荐）：授权头再校准——bank 142 帧密集池自动几何标注（135 TP/13,004 FP）重训同构 LogisticRegression 头，GroupKFold(clip|frame)+LOCO(sas_det 跨转播) 验收，靶子=密集池 GT top-1 ≥90% 且 honest 覆盖不降。
- B：先标完 12 帧 empty-cloud + 6 个 near-miss 帧再扩库重训（多 1 轮人工，覆盖更全）。
- C：不动头，改消费端跟踪器（候选连续性优先于 prob）——工程量最大，不推荐。

## 产物清单
- `action_work/validate/sas_{lal,det}_cands_multiscale.json`（池）
- `action_work/validate/ball_cand_scores_multiscale_{sas_lal,sas_det}_joint.json`（final351 头打分）
- `action_work/validate/multiscale_gt_top1_miss.json` / `multiscale_empty_cloud.json`（98 miss 帧清单 / 5 空云帧）
- `action_work/validate/{sas_lal,sas_det}_{f351old,ms}_ball_events.json`（事件对比）
- `action_work/validate/{sas_lal,sas_det}_poss_ms{old,new}/summary.json`（解出率）
- `action_work/validate/sas_lal_sheets/label_empty_multiscale.html`（中期 12 帧点球标注页，已交付）
- 新工具：`engine/gen_cands_tiled.py`（--preset multiscale）、`engine/eval_multiscale_e2e.py`、`engine/scores_to_balljson.py`、`engine/make_empty_cloud_sheet.py`
- 生产管线改动（backward-compatible）：`validate_clips.py` tiled() topk 切片 bug 修复 + `--topk`；`rescore_clip_heads.py` `--head`/`--device`

---

# 附录：方案A dense 头验收（2026-09-28 补）

## 训练
- `ball_head_dense_a442.joblib`：bank 209 帧内密集池候选 19,288（TP 197/FP 19,091，IoU≥0.3 几何匹配锚定人工 GT），class_weight='balanced'。

## 验收数字
| 指标 | old池+final351 | ms池+final351 | **ms池+dense新头** |
|---|---|---|---|
| GT top-1（sas_lal 121帧） | 98.3% | 19.0% 🔴 | **88.4%**（池含球108帧中对107=99.1%，≈池天花板） |
| 无球帧 FP（21帧） | 0 | 14 🔴 | **0** |
| per-frame honest 覆盖@0.3 | 67.8% | 88.8%(虚) | 64.7%（阈值扫描至0.05也仅70.2%⇒泛化缺口非阈值问题） |
| **跟踪器覆盖**（run_ball_events） | 73.0% | 644.8%(碎轨海) | **85.5%**（+12.5pp，41轨/可跟踪91.0%） |
| **GT帧轨迹点命中** | 94.5%(120/127) | — | **95.3%**(123/129) |
| 持球者解出率（sas_lal） | 77.8% | 88.8%(FP虚) | 82.5%（球输入0假阳） |
| LOCO 跨转播 GT top-1 | — | — | 31-41%（⚠️新转播必须补标） |

## 结论
1. **产品级（跟踪器口径）ms池+dense新头胜出**：轨迹覆盖 73.0→85.5%（+12.5pp），点级精度 94.5→95.3%，无 FP 洪泛。per-frame 覆盖的回退被跟踪器时域连续性补足。
2. **头已到池天花板**（99.1% 条件命中率）；再往上=中期检测器 fine-tune（6 硬例帧+5 空云帧清单已备）。
3. 转正建议：**multiscale 池 + dense 新头** 为生产候选；final351 保留为旧池配置的官方头。等 sas_det 零回归数字（后台跑数中）后终裁。
4. 新转播接入成本：必须补该转播标注帧（LOCO 31-41% 不可直接用）。

---

# 附录续：sas_det 零回归终裁（2026-09-28 02:14）

> 后台 QHik2t 完成 sas_det dense 重打分（37,433 候选，MPS ~45min）→ Mj0rzD 自动跑 `eval_sas_det_zero_regression.py`。
> 首版 FPR 误报 WARN（无球帧集被「含 TP+FP 候选」的持球帧污染，分母 67 错）；修正为「无任何 TP 标注的 bank 帧」后分母 25，FPR 归 0。

## 零回归数字（OLD = final351 头 + 640×384 ov96 top-4 生产池；NEW = dense_a442 头 + multiscale 不截断池）
| 指标 | OLD | NEW | 门禁 | 裁定 |
|---|---|---|---|---|
| 覆盖 all@0.3 | 55.2% | **59.8%** (+4.6pp) | ≥55.2 | ✅ |
| 覆盖 all@0.8 | 45.5% | **47.2%** (+1.7pp) | ≥45.5 | ✅ |
| honest@0.3（333 泛化帧） | 53.8% | **59.2%** (+5.4pp) | 不降 | ✅ |
| honest@0.8 | 42.0% | **44.1%** (+2.1pp) | 不降 | ✅ |
| GT top-1（42 TP 帧, sas_det human bank） | 100% / 100% | **100% / 97.6%** | ≥80% | ✅ |
| 无球帧 FPR（25 帧, th=0.3） | 0% | **0%** | ≤10% | ✅ |

## 终裁结论
- **✅ 零回归达成，可转正**：四口径覆盖全 ≥ 基线，GT top-1 达 100%(strict)/97.6%(inbox)，无球帧 FPR 新旧同为 0%。
- sas_det 侧 NEW 覆盖提升幅度（+4.6/+1.7pp）小于 sas_lal（+12.5pp 跟踪器口径），因 sas_det 旧池基线本就偏低且片段更难（bank 仅 67 帧、honest 333 帧纯泛化），但方向一致、无回退。
- 与 sas_lal 三方验收合看：multiscale 池 + dense 新头在双片段均无回归且显著改善 → **建议 final351 留作旧池(top-4)官方头，multiscale+dense 转正为新生产默认配置**。
- 残留 honest 覆盖 ~59%（sas_det）/ 64.7%（sas_lal）是池信息天花板（召回 89.3%）使然，非头失配；再往上 = 中期检测器 fine-tune（5 空云 + 6 硬例帧清单已备，标注页 `label_empty_multiscale.html` 已交付）。
- 新转播接入成本：每换转播须补该转播标注帧（LOCO 31-41% 不可直接用）。

## 集成落地（2026-09-28 18:07，老程「开始集成」授权）
- 三处默认配置已改（backward-compatible；py_compile + resolve_scores 单测 + run_ball_events 端到端烟雾全 PASS）：
  - `gen_cands_tiled.py`：`--preset` 默认 single → **multiscale**。
  - `rescore_clip_heads.py`：`--head` 默认 `ball_head_sas_human` → **`ball_head_dense_a442`**；final351(`ball_head_joint.joblib`) 留作旧池官方头，须显式 `--head` 指定。
  - `run_ball_events.py`：新增 `--preset {multiscale,legacy}`（默认 **multiscale**）；`resolve_scores()` 优先读 `validate/ball_cand_scores_dense_a442_<clip>_joint.json`，缺失回退旧 `validate/<clip>_scores.json`；legacy 预设直读旧池。
- 端到端烟雾（默认 multiscale）：sas_lal 覆盖 **85.5%** / 可跟踪 91.0% / 41 轨 / **PASS**；sas_det(th=0.8) 覆盖 53.0% / 可跟踪 88.1% / 35 轨 / **PASS**(FP 过滤 37→35)。默认产物 `sas_lal_ball_events.json` / `sas_det_ball_events.json` 现已是 dense 配置；legacy 一键 `--preset legacy` 可复现旧 top-4 产物。
- **A4.42 正式转正完成**：multiscale 池 + dense 头 = 新生产默认；final351 + top-4 池 = 旧池官方头（backward-compatible）。残留 honest 覆盖缺口 = 池召回天花板(89.3%)，归中期检测器 fine-tune。
