# A4.31 — HUMAN 头集成 run_ball_events + 语义标注叠加（四步计划·第 3 步收尾）

日期：2026-09-26　状态：✅ 完成
前置：A4.29（T3a 语义层）、A4.30（T3b 重建）、老程两项目视裁定（f120 拾取正确；tid8/f3 深色模糊帧=有球，运球模糊是检测正常工作的产物）

## 1. 做了什么

用户四步计划第 3 步：「当前段做收尾：用偏保守阈值（th=0.80）集成进 run_ball_events，产出带探索级标注的事件指标，先用起来。」

1. **`engine/run_ball_events.py` 最小侵入参数化**：新增 `--scores`（覆盖默认打分源，文件须含 `<clip>` 顶层键）与 `--tag`（产物文件名后缀，防覆盖旧产物）。默认行为零改动（A4.15 口径不变）。
2. **HUMAN 打分落盘**：`action_work/validate/sas_det_scores_human.json`（`{"sas_det": fr}` 包装，供 `--scores` 读取）。
3. **集成运行**：`python engine/run_ball_events.py --clip sas_det --scores ... --tag human`
4. **语义叠加**：`sas_det_human_ball_events.json` × `sas_det_t3a_semantic.json` frame_annotations × T2 possession → `sas_det_human_ball_events_semantic.json`。

## 2. 数字（全部从 JSON 现读）

### 门禁（th=0.80，HUMAN 头，A4.19 FP 过滤开）
| 指标 | 值 | 判定 |
|---|---|---|
| 打分命中帧 | 176/400（44.0%） | — |
| 轨迹覆盖 | 163 点 / 400 帧 = **40.8%** | — |
| trackable_frac | **94.5%** | ≥80% PASS |
| 中位步长 | 25.6 px | <SMOOTH_PX PASS |
| 轨迹数 | 18（FP 过滤 19→18 轨，169→163 点） | — |
| fid 范围 | f003–f353 | f366 起为 T2 判 dead 球段，无轨迹 ✓ 与语义层自洽 |

### 语义叠加（18 轨迹 × 163 点）
- 语义点分布：`{'live_tactical': 163}`——**0 死球点、0 遮挡点**（f366 后无轨迹，与 T2 状态表一致）。
- possession 分段自洽：track 0–12 = SAS 段、track 13–17 = DET 段，与 PBP 时序对齐。
- 结构：每轨迹含 `track / n_frames / fid_range / semantic_tags / pbp_possession / points[{fid, center, semantic}]`。

## 3. 产物清单

| 文件 | 内容 |
|---|---|
| `action_work/validate/sas_det_scores_human.json` | HUMAN 头打分（`--scores` 输入） |
| `action_work/validate/sas_det_human_ball_events.json` | 18 轨迹球事件 |
| `action_work/validate/sas_det_human_fp_events.json` | FP 过滤明细（before/after） |
| `action_work/validate/sas_det_human_framespace_tracks.jpg` | 帧空间轨迹图（诚实版，非球场） |
| `action_work/validate/sas_det_human_ball_events_semantic.json` | 逐点语义标注叠加 |

## 4. 定位与边界（探索级，勿当交付精度引用）

- **这是「先用起来」的探索级事件层**：th=0.80 保守工作点牺牲覆盖（40.8% vs th=0.30 的 53.0%）换精度。
- 163 点全部落在 live_tactical 且经 A4.19 邻近性过滤 + 老程两项目视裁定背书，**当前段 208 拾取 0 FP 的结论覆盖此工作点**。
- 战术层语义（pass/drive/PnR 计数）仍受 **ID 稳定化卡点**约束（A4.30 teamID NOT_QUALIFIED），事件级产出可用于探索，不可作统计结论。
- 第 4 步（T1/T2 台标+PBP 对齐）已先行完成（A4.27/A4.28），死球否决已内建于此工作点（f366+ 无轨迹即证据）。

## 5. 下一步

→ 四步计划第 1 步：另选高清片段（完整台标/球较多/特写相对少）→ 跑 HUMAN 头 → 50–80 帧人工快速真值 → 第 2 步联合训练。
