# T3b 报告 — sas_det 球轨迹重建 + 战术事件层重跑 + teamID 交叉验证

日期：2026-09-26 · 产出：`action_work/validate/sas_det_t3b_tactical.json`
代码：`engine/t3b_rebuild_tactical.py`（DB 零写）

## 0. 结论

1. ✅ **球轨迹重建成功**：HUMAN 头（th=0.30）top1 → 球覆盖 **52.0%（208/400）**，
   对比旧 poss_tile 稀疏源 **3.5%**（A4.23 判「指标不可用」）——sas_det 的战术事件层
   第一次建立在可信球信号上。
2. ✅ **战术事件重跑**：N-of-M 稳定后 PASS 6 个 / DRIVE 7 个 / PnR 0 个；
   事件全部落在活球段（死球 veto 0 个，与 T2/T3a 状态表一致）。
3. 🔴 **teamID 不可入账（NOT_QUALIFIED）**：球衣亮度二分（Otsu V=119.8）与
   PBP possession 交叉验证一致率仅 **71.5%**（全部可判帧）/ **74.2%**（仅球在手中帧），
   <90% 门禁。**根因 = track ID 不稳定（A4.21 已封口根因）**：400 帧出 42+ 个稳定
   track、裁判与运动模糊帧混入 tid 池——A6#1「ID 稳定化」第三次被实证为 teamID 的
   硬前置。颜色特征本身可分（样本 crop 实证白/深清晰），卡点不在特征在 ID。

## 1. 事件清单（语义标注已附）

| 类型 | 帧 | live/semantic | team(NOT_QUALIFIED) |
|---|---|---|---|
| PASS | f032/f062/f111/f239/f322/f349 | live/live_tactical | — |
| DRIVE | f011/f073/f142 | live/live_tactical | SAS(white) |
| DRIVE | f042/f241/f274/f349 | live/live_tactical | DET(dark) |

⚠️ 上表 team 列**仅供探索**，verdict=NOT_QUALIFIED（同 JSON xval_possession）。
PASS 的 from/to tid 同理未打 team（cross_team 字段在 JSON 中为 null/不可信）。

## 2. 交叉验证方法与数字（诚实双口径）

- **口径1 全部可判帧**：一致 108 / 不一致 43 → 71.5%（151 帧）
- **口径2 仅球在手中帧**（球速<250px/s，排除球飞行段 nearest 误配）：一致 46/62 → 74.2%
- 飞行段排除只回收 ~2.7pp——**主根因不是飞行段**，是 track ID 不稳定。
- 诊断证据：`sas_det_t3b_xval_bad.png`（6 个不一致帧渲染）、
  `sas_det_t3b_tid_samples.png`（10 个 tid 特征样本：白/深可分、裁判 tid5 混入、
  模糊 tid13/16）。

## 3. 对路线图的含义

- **ID 稳定化（A6#1）从「前置」升级为「唯一卡点」**：球信号（52% 覆盖、0 FP）、
  钟/状态层（T1/T2）、语义层（T3a）都已可用，逐帧 teamID 与稳定持有者身份是
  战术层（PnR team 归属、pass 网络）的最后一块缺失。
- ID 稳定化之前，DRIVE/PASS 的 team 标注一律 NOT_QUALIFIED；tactical_events 的
  PnR 探索性标注继续保留。
- 球速/方向指标（A4.22 框架）在重建轨迹上可直接复算——但本片段事件层已含，
  无需单独出数。

## 4. 产物

- `sas_det_t3b_tactical.json` — 13 事件（含语义标注与 team NOT_QUALIFIED verdict）+ 重建元数据
- 诊断图 3 张（见 §2）
