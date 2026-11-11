# 端到端球事件产品报告（A4.16 · run_ball_events 统一入口）

> 日期：2026-09-25（续 7/7 全 PASS 之后）
> 前置：A4.13b 路径 A 已落地、A4.15 零人工 7/7 全 PASS（scope 解除收窄：宽景 AND 常规转播均可用）
> 本步目标：把「scores → 跟踪器 → 门禁 → 球事件轨迹」收敛为**一条零人工命令**，并落盘可视化工件。

## 1. 修复的阻塞 bug

`engine/run_ball_events.py` 的 `_load_track_ball()` 原用 `__import__("importlib").util.spec_from_file_location(...)`，
但 `__import__("importlib")` 只返回顶层模块、不会自动导入 `.util` 子模块 → `AttributeError: module 'importlib' has no attribute 'util'`。
**修复**：顶部 `import importlib.util`，改用 `importlib.util.spec_from_file_location(...)`。已修，无副作用。

## 2. 统一入口（零人工、一键）

```
python engine/run_ball_events.py --clip sas_hou          # 单片段：落盘工件 + 打印裁定
python engine/run_ball_events.py --all-clips              # 7 域统一跑（复用 recalib 工作点）
```

工作点 `th`：默认取 `action_work/validate/gate_tracked_recalib.json` 的 `operating_th`
（sas_hou/sas_nop/基线四窗=0.3，sas_det=0.8），缺省回退 0.3；`birth=th、gap=8、min_track=3`——与 A4.15 口径一致。

## 3. 落盘工件

- `<clip>_ball_events.json`：持续轨迹（`min_track=3` 过滤后的存活轨迹），每条含 `frames / centers / probs`。
  - 单片段实测 `sas_hou_ball_events.json`：17 条轨迹，长度 [3,8]，帧序连续（如 track0 = 帧 14–16，球心 [760.4,753.2]）。
- `<clip>_ball_courtmap.jpg`：1920×1080 球场空间图，各轨迹同色连线球心（半场中线+中圈底图）。
  - 单片段实测 `sas_hou_ball_courtmap.jpg`（~80 KB）。

## 4. 门禁复现（7/7 全 PASS，数字逐位一致）

| 域 | th | 覆盖 | 可跟踪 | 步长(px) | 步数 | 轨迹 | 裁定 |
|----|----|----|----|----|----|----|----|
| sas_hou | 0.3 | 19.8% | 91.9% | 28.1 | 62 | 17 | PASS |
| sas_nop | 0.3 | 15.8% | 82.2% | 29.2 | 45 | 18 | PASS |
| sas_det | 0.8 | 6.2% | 94.4% | 23.8 | 18 | 7 | PASS |
| baseline_w1 | 0.3 | 47.6% | 90.7% | 26.2 | 183 | 24 | PASS |
| baseline_w2 | 0.3 | 35.5% | 91.5% | 35.0 | 106 | 13 | PASS |
| baseline_w3 | 0.3 | 40.5% | 92.2% | 20.7 | 281 | 31 | PASS |
| baseline_w4 | 0.3 | 43.3% | 97.9% | 18.9 | 94 | 12 | PASS |

门禁判据（任务级事件可用性）：可跟踪率≥0.80 且 中位步长<80px 且 n_steps≥10。全部满足。

## 5. 与球员移动战术分析的集成 seam（已连通状态）

`tactical_movement.py::handler_id(fr, pad)` 读 `fr.get("ball")["bbox"]` 判持球者；
输入 `action_work/{w}_poss_tile/ball_tracks.json` 逐帧含 `players`(track_id+bbox) 与 `ball`。

- **宽景四窗 w1–w4：seam 早已 live**。其 `fr["ball"]` 来自 milestone-05 已验证球检测
  （实测 w1：435 帧中 433 帧含 `ball.bbox`；`handler_id` 实时解出持球者 tid 5）。
  → 端到端战术分析（player-movement + 持球者归属）**已交付**。
- **常规转播 sas_hou/sas_nop/sas_det：信号已产出，但持球者归属暂不可做**。
  根因：这三段无 `action_work/{c}_poss_tile/ball_tracks.json`（即无球员 tracking 帧）。
  `run_ball_events` 已给出每帧球心轨迹，但要喂给 `tactical_movement.handler_id` 还需先为这三段生成
  球员 tracking（YOLO11n-pose + BotSort，与 w1–w4 同链路）。**此步未授权、不在本轮 scope**，列为下一步。

> 诚实边界：run_ball_events 对 w1–w4 是「同管线泛化验证」，生产球仍用 milestone-05 已验证球（质量更高）；
> 对 sas_* 则无替代来源，run_ball_events 即其球事件权威信号。

## 6. 已知 FP 污染（诚实入账，来自 A4.15）

低阈值（th=0.3）下 sas_nop 召回饥饿被救活，但混入 FP：抽查 3 条持续轨迹 = 2 真球 + 1 观众席高光 FP。
这是「按域重标定 + 跟踪器时序一致性」门禁的固有代价——覆盖与可跟踪率达标，但单轨迹不保证全真。
产品消费时建议对长轨迹优先（track_metrics 已按 min_track=3 过滤短噪），重度场景可叠加 `label_ball_app` 少样本真值重训头降 FP（治本路，未授权勿做）。

## 7. 结论

球事件信号端到端产品**已收敛为一命令、零人工、7/7 可复现**，并附轨迹 JSON + 球场空间图双工件。
宽景战术分析早已端到端打通；常规转播域的球事件信号已可用，持球者级战术整合待球员 tracking 就绪。
路径 A/B/C 三路至此收束：A（宽景滤过+重标定）交付、C（时序跟踪器）交付且泛化到常规转播、B（少样本域适应）被「零人工」指令替代为 C 的同管线按域重标定，无需人工标注。
