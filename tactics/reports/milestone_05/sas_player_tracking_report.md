# 给 sas_* 补球员 tracking —— 打通「球事件 → 持球者归属 → 战术」(A4.18)

> 日期:2026-09-26
> 目标:让战术分析从「只覆盖宽景四窗 w1–w4」扩展到**常规转播片段** sas_hou / sas_nop / sas_det
> 结论:**seam 已接通**(持球者归属在有球帧解出 76–93%);但**逐球员聚合仍不可靠**(ID 中位寿命仅 ~1s),
> 且已证明简单调 BotSort 无法在不丢球员前提下解决。

---

## 0. 摘要

| 项 | 结论 |
|---|---|
| 球员 tracking 是否建成 | ✅ 三段各 400 帧,均值 9–12 人/帧 |
| **持球者归属是否接通** | ✅ **解出率 76.1% / 82.4% / 92.9%**(有球帧口径) |
| 战术分析是否可跑 | ✅ `tactical_movement.py --windows sas_hou sas_nop sas_det` 已出产物 |
| 是否用了伪球/插值 | ❌ 全程 `--no-smooth`,`interp_share_of_possession = 0.0` |
| 遗留问题 | ⚠️ ID 碎片化(中位寿命 ~1s)⇒ 逐球员指标不可靠 |
| 碎片化能否靠调参解决 | ❌ 不能(见 §4,调参代价是丢真实球员) |

---

## 1. 为什么必须自己补,以及关键设计选择

`tactical_movement.py::handler_id(fr, pad)` 读 `fr["ball"]["bbox"]` 判持球者,
输入是 `action_work/<w>_poss_tile/ball_tracks.json`(逐帧 `players[track_id,bbox]` + `ball`)。
w1–w4 有此文件,sas_* 原本没有 ⇒ 战术侧永远只覆盖宽景四窗。

**关键设计选择(避免踩 fabrication 红线)**:
`ball_possession.py` 自带球检测走 YOLO COCO `sports ball`(对篮球召回仅 17–30%),
且默认 `--max-gap 15` 会**线性插值补洞**。两者都与项目铁律冲突(「平滑≠正确」「只消费真实检测」)。
故做法:

- 球员 tracking:复用现成 `ball_possession.py`(YOLO11n-pose person + BotSort)
- 球:**外部喂入**我们自己 A4.15/A4.16 已验证的 Kalman 轨迹(`--ball-json`),并 `--no-smooth` 关闭插值

---

## 2. 实施链路

| 步 | 组件 | 说明 |
|---|---|---|
| ① | `engine/make_ballfeed.py`(新) | 把持续轨迹(≥3帧)的真实检测点转成 `{f00001.jpg:[{bbox,conf}]}`。键=帧文件名,与 `ball_possession` 读取处一致;bbox 按中心回查 scores **原始框**(非合成) |
| ② | `ball_possession.py` + `--tracker`(新参数) | `--player-model weights/yolo11n-pose.pt`、`--no-smooth`、`imgsz 1280`、`device mps` |
| ③ | `engine/detect_cuts.py`(新) | 切镜检测(帧差 MAD),用于判断是否需要 reset 跟踪器 |
| ④ | `engine/make_pose_timebase.py`(新) | 生成 `pose_motion.json` **仅时间基准**(tactical_movement 只消费 `series[*].t` 与 `events`) |
| ⑤ | `tactical_movement.py`(改) | 加 `--windows` 参数;SVG 配色不再按 w1–w4 硬取(否则新片段名 KeyError) |

### 2.1 球喂入 JSON(零插值、数字与门禁表逐位吻合)

```
sas_hou: th=0.3 持续轨迹=17 真实检测点=79 覆盖帧=46
sas_nop: th=0.3 持续轨迹=18 真实检测点=63 覆盖帧=34
sas_det: th=0.8 持续轨迹=7  真实检测点=25 覆盖帧=14
```

与 `gate_tracked_recalib.json` 的 `n_claims`(79 / 63 / 25)**完全一致** ⇒ 喂入的就是门禁验证过的同一批真实检测。

---

## 3. 结果

### 3.1 球员 tracking

| 片段 | 帧 | 球员/帧(均值) | 空帧 | track_id 数 | ID 中位寿命 | ID 最长寿命 |
|---|---|---|---|---|---|---|
| sas_hou | 400 | 11.03 | 7 | 256 | **10** | 178 |
| sas_nop | 400 | 12.81 | 9 | 222 | **11** | 125 |
| sas_det | 400 | 11.63 | 3 | 260 | **8** | 186 |

### 3.2 🔑 持球者归属(核心交付)

| 片段 | 有球帧 | **持球者解出帧** | **解出率** |
|---|---|---|---|
| sas_hou | 46 | 35 | **76.1%** |
| sas_nop | 34 | 28 | **82.4%** |
| sas_det | 14 | 13 | **92.9%** |

⇒ **「球事件 → 持球者归属」这条 seam 在常规转播素材上已接通。**

### 3.3 战术分析产物(已跑通)

```
sas_hou: spacing 642.2px  off-ball 202.0px/s
sas_nop: spacing 685.2px  off-ball 154.0px/s
sas_det: spacing 617.9px  off-ball 149.6px/s
```

产物:`action_work/tactical_movement_sas.json`、`reports/milestone_05/tactical_movement_sas.html`

---

## 4. 🔴 遗留问题:ID 碎片化(含一个被数据推翻的假设)

**现象**:场上仅 ~10–12 人,却出现 222–260 个 track_id,**中位寿命仅 8–11 帧(≈1 秒)**。
⇒ 逐球员聚合(速度/空切)不可靠:如 `tid=997 空切32帧(74.4%)` 是 1 秒级碎片算出的,
**不能与 w1–w4(ID 整窗稳定 435 帧)的指标相提并论**。

**假设被推翻(诚实记录)**:我最初推测成因是「转播镜头切换」因而写了 `detect_cuts.py`。
实测三段**全部 0 处硬切**:

| 片段 | MAD 中位 | p99 | max | 阈值(6×中位) | 判定切镜 |
|---|---|---|---|---|---|
| sas_hou | 21.88 | 56.36 | 73.20 | 131.30 | **0** |
| sas_nop | 21.48 | 44.62 | 98.16 | 128.88 | **0** |
| sas_det | 23.81 | 36.24 | 52.80 | 142.86 | **0** |

分布平滑、无任何数量级跳变 ⇒ 是**连续摇镜/变焦**,不是硬切。
真实成因:摇镜使球员频繁**进出画面 + 短暂遮挡**,检测断续即被判轨迹丢失并重开 ID。

**调参对照实验(sas_hou,单段 18s 可复跑)**:

| 配置 | 每帧球员数 | ID 数 | 中位寿命 |
|---|---|---|---|
| 默认 `new_track_thresh=0.25, track_buffer=30` | **11.03** | 256 | 10 |
| `nt=0.60, buf=90`(`botsort_stable.yaml`) | 9.06 ⚠️ | **147** | **15** |
| `nt=0.35, buf=90` | 10.85 | 231 | 11 |

判读:

- 单纯加大 `track_buffer` 几乎无效(231/11 vs 256/10)
- ID 减少几乎全部来自 `new_track_thresh=0.6`,但它**把真实球员也吞了**(11.03→9.06,已低于场上 10 人)
- ⇒ **简单调 BotSort 无法在不丢球员的前提下解决碎片化**

**规范产出因此保留默认配置**(保住全部球员):
逐帧类指标(spacing、off-ball 速度、**持球者归属**)不依赖 ID 稳定性,完全可用;
仅「逐球员聚合」需后续手段。

---

## 5. 诚实边界(务必随产物一起阅读)

1. **`pose_motion.json` 是时间基准存根,不是姿态测量**:只含 `series[*].t` 与空 `events`,
   由已知抽取参数 `-ss 60 -t 40 fps=10` 推导(400 帧 / 40s ⇒ dt=0.1s),属**元数据**。
   **未**伪造 `max_air` / `n_tracks` / jumps / contests。
2. **未做比赛时钟对齐**:`t` 是片段相对时间(0–39.9s),不是比赛计时;`events` 为空。
3. **球信号仍有已知 FP**(承 A4.15):低阈值工作点下 sas_nop 抽查曾见观众席高光 FP;
   持球者归属继承了这一污染(这也是下一步「降 FP」能用持球者信息反哺的原因)。
4. **逐球员战术指标暂不可用于跨片段比较**(见 §4)。

---

## 6. 下一步建议(按 ROI)

| 优先 | 事项 | 说明 |
|---|---|---|
| 1 | **降 FP**(用户既定次选) | 持球者信息已就位,可立即用于过滤「球不在任何球员附近」的 FP |
| 2 | ID 稳定化(若要逐球员指标) | 需 ReID 外观权重(本地不可达)或**轨迹拼接**(按外观/运动把短轨迹缝合) |
| 3 | 提覆盖 | 工作点/候选池优化,把 sas_det 仅 3.5% 的球覆盖率提上去 |
| 4 | 丰富事件指标 | 有了持球者后,速度/方向/停留热区才有战术意义 |

---

## 7. 文件清单

**新增**:`engine/make_ballfeed.py`、`engine/detect_cuts.py`、`engine/make_pose_timebase.py`、
`engine/botsort_stable.yaml`(调参实验件,非规范产出)

**修改**:`engine/ball_possession.py`(新增 `--tracker`)、
`engine/tactical_movement.py`(新增 `--windows`、SVG 配色 fallback)

**产出**:`action_work/{sas_hou,sas_nop,sas_det}_poss_tile/ball_tracks.json`(规范,默认 tracker)、
`action_work/validate/*_ballfeed.json`、`action_work/validate/*_cuts.json`、
`action_work/*/pose_motion.json`、`action_work/tactical_movement_sas.json`、
`reports/milestone_05/tactical_movement_sas.html`

**实验件(保留作证据)**:`action_work/sas_hou_poss_stable/`、`action_work/sas_hou_poss_t35/`
