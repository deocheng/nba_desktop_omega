# A4.60 战术笔记全量批分析报告 —— 定位管线可用, 但匹配层被证伪

日期: 2026-09-29 ｜ 线索: A4.59(单片段验证) → A4.60(本文, 老程令「逐个分析战术笔记里的视频」)
纪律: 数字全从磁盘现读; 主动推翻自己; 无逐行证据不下"达标"; 裁定归老程。

---

## 0. 一句话结论

**自动定位「实战片段」的管线成功了**(可复用于全部 91 期); 但**匹配层在广播素材上被证伪**:
试点 14 期 **真值命中 top1 仅 1/14 (7.1%)**, 且 `cross_screen` 在 **14/14 期** 都至少有一个实战段排 top1
⇒ **A4.59「ep24 命中 cross_screen」不是能力证明, 而是「该模型在哪儿都排第一」造成的偶然命中**(过拟合)。

---

## 1. 交付物

| 文件 | 内容 |
|---|---|
| `engine/tactic_notes_batch.py` | **批处理驱动**: 视频 → 自动定位实战段 → 追踪 → 匹配 → 与真值对照 → 汇总 |
| `engine/tactic_notes_totracks.py` | 重构出 `convert()` 供批处理复用 |
| `action_work/tactic_notes_batch_pilot/` | 试点 14 期结果 `batch_results.{json,csv}` |
| `action_work/tactic_notes_batch_full/` | 全量 91 期结果(运行中) |

## 2. 实战片段自动定位（✅ 可用, 全量前先自证）

战术笔记视频**混杂** 演播室主持 / 战术板图解(telestration 圈人) / 实战画面。实测可用**人物统计**干净分离:

| 画面类型 | n_person | 中位框高/画面高 |
|---|---|---|
| **实战画面** | 9–24 | 0.13–0.28 |
| 演播室/特写 | 0–3 (或个位数) | 0.5–0.98 |
| telestration 图解 | **0**(画的是圆圈, 检不到真人) | — |

判据: `n_person ≥ 6 且 中位框高 < 0.5×画面高`(几何先验: 宽景球场镜头里人不可能占半屏)。
连续实战帧分组→取最长 ≤2 段。抽样验证 ep24/ep15/ep02 三期均正确切出实战段(如 ep24 → 24–51s 与 81–99s)。

## 3. 试点结果（14 期, 均有真值）

```
真值命中:  top1  1/14 (7.1%)   top3  2/14 (14.3%)   top-k 2/14 (14.3%)
```

| ep | 真值战术 | 各段 top1 |
|---|---|---|
| 24 | cross_screen | **cross_screen** / cross_screen |
| 15 | stagger_screen | cross_screen / cut_family |
| 1 | pick_and_pop | cut_family / cross_screen |
| 2 | backdoor·zipper·zipper_backdoor | cut_family / cross_screen |
| 5 | backdoor | cross_screen / cross_screen |
| 16 | wedge_screen | cut_family / cross_screen |
| 19 | ghost_screen·sts | cross_screen / cross_screen |
| 20 | touch_screen | cross_screen / cross_screen |
| 25 | inverted_pnr·pick_and_roll | cross_screen / cross_screen |
| 26 | twirl_action | (空) / cross_screen |
| 27 | drop_defense | cross_screen / cross_screen |
| 31 | ram_screen | cross_screen / cross_screen |
| 53 | handoff | cross_screen / (空) |
| 70 | pick_and_roll·pnr_1_5 | cross_screen / cross_screen |

🔴 **`cross_screen` 在 14/14 期都至少有一段排 top1**（含 drop 防守、pick&roll、handoff 等与横掩护无关的期）。
⇒ **预测几乎是常数**, 命中率无判别意义。**A4.59 的单期"成功"不能推广。**

## 4. 根因（均带证据）

### 4.1 掩护原语**不具判别性**（首要瓶颈）
`SCREEN.CROSS` 在每 20s 段检出 **13–26 次**, 且与片段内容**无关**:

| 段 | 真值 | CROSS(旧门) | CROSS(严门 hold≤0.25·d_screen) |
|---|---|---|---|
| ep24_s1 | cross_screen | 27 | 15 |
| ep5_s1 | backdoor | 30 | **19** |
| ep27_s1 | drop_defense | 13 | 5 |
| ep15_s0 | stagger | 12 | 3 |

**收紧站定门只是等比缩小, 不能把真横掩护期与其它期分开** → 几何+运动学判据**无法**特异性识别掩护。
(A4.59 的 `_mk_screen` 站定门允许慢者位移到 `3×帧位移`≈26px, 对「谁在跑谁在站」放得过宽。)
真实篮球里横掩护每回合 1–3 次, 检出 26 次/20s ⇒ **绝大多数是假阳性**(任意两人「一慢一快 + 水平位移」即命中)。

### 4.2 广播素材上**球员轨迹严重碎片化**
实战段每帧检出 **24–48 个 person**(场上仅 ~10 人) ⇒ 含替补席/边线观众 + 追踪 ID 断裂。
追踪器是在 **sas_det 固定机位 1080p** 上验证的, 直接搬到**移动机位广播画面**上 ID 稳定性大幅退化 ⇒ 配对几何不可靠。

### 4.3 排序把「覆盖优先」用过头（A4.59 的过拟合）
A4.59 为救 ep24 把 rank 改成 `(已验证, 覆盖率, 绝对分)` 并把 `cross_screen` 的必要集砍到 `[SCREEN.CROSS]`。
后果: **只要检出 1 个 CROSS 就 cov=1.0 → 必胜** → cross_screen 变成新的"eog"。**这是单期调参的过拟合。**

### 4.4 结构缺失（旧账）
无球场配准、无防守人轨迹 → Zone 依赖 signature 与掩护接触判据都算不了(见 A4.58 caveats)。

## 5. 修正方向（按性价比, 待老程裁定）

1. 🔴 **别再调排序救场**——根因是原语层。优先做**掩护特异性**:
   ① 站定门用**绝对**站定量(慢者整段位移 ≤ 0.5×体长? 甚至 ≤ 0.2×)且要求「**通过者路径穿过掩护人**」(距离在段内先减后增, 段内极小于两端);
   ② 用**球/占有权**约束: 掩护发生在**有球半场进攻**中(借 A4.53 占有权), 排除乱跑段与转换。
2. **限制到场上球员**: 用画面中心区/球场色块粗筛, 剔替补席/观众(现每帧 24–48 人不可用)。
3. **重建判别基准**: 先人工标注几期实战段的"确含该战术"窗口(段级真值) —— **期级真值不够**(一期含多个回合)。
4. 结构补齐: 单帧球场配准 + 用 team 字段取防守人 → 再开 signature。

## 6. 诚实状态

- ✅ **定位管线可用**, 已可复用于全部 91 期(产出实战段时间索引 + 原语统计)。
- ❌ **匹配层未达可用**: 试点 7.1% top1 且预测近似常数 ⇒ **不得**用当前匹配声称"在素材里发掘到战术"。
- 🔴 **A4.59 的结论收窄**: ep24 命中 ≠ 能力, 仅为单期偶然; `cross_screen` 的 `[SCREEN.CROSS]` 简化属**过拟合**, 已在本报告记录, 待与老程商定后回退或重构。

---
*本报告数字均从磁盘产物现读; 全量结果以 `tactic_notes_batch_full/batch_results.json` 为准。*

## 7. 全量 91 期结果（2026-09-29 跑完，最终）

```
[汇总] 视频 91 | 有真值 59 | 无真值 32 | 有真值但没定位到实战段 0
       真值命中: top1 2/59 (3.4%)  top3 3/59 (5.1%)  top-k 5/59 (8.5%)
```

**预测≈常数（决定性，比试点更硬）**：全部 **177 个段次**的 `top1` 分布：

| top1 模型 | 段次 | 占比 |
|---|---|---|
| `cross_screen` | **129** | **72.9%** |
| `None`（无候选） | 28 | 15.8% |
| `cut_family` | 20 | 11.3% |

- 命中的 2 期：`ep24`（真值 cross_screen）、`ep35`（真值 cut_family）——**皆因该模型在哪儿都排 top1**，非能力。
- 🔴 全 91 期里**真值含 `cross_screen` 的仅 1 期**（ep24）⇒ 「ep24 命中」**无判别价值**。
- 结论：**全量确认 A4.60 判定**（试点 7.1% → 全量 3.4%）。匹配层当前**不可用**；根因已由 A4.61 定位（**掩护原语无判别性 = 纯几何无法区分掩护/防守**，见 `A4_61_screen_specificity_report.md`）。
- 产出 `action_work/tactic_notes_batch_full/batch_results.{json,csv}`（91 行，逐期 gt/实战段/top1 全量）。
