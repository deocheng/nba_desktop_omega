# SAS 重点战术优先池 + 验证片段筛查

来源: A4.56 战术库(人声 ASR) ｜ 模型: `action_work/tactic_models.json` `priority.sas`

---

## 1. SAS 重点战术池（6 个模型）

| 模型 id | 库条目 | 目的(人声蒸馏) | 判别信号(可观察) | 来源 |
|---|---|---|---|---|
| `zipper_backdoor` | zipper backdoor / backdoor (SAS) | 借下掩护外切(zipper)作饵，防守抢前时反跑后门切篮 | 轨迹反转(先外后内冲筐)+防守偏上线 | 第2期 ZipperBackdoor |
| `zipper` | zipper / 拉链挡拆 (SAS/CHN) | 强侧拉链掩护让侧翼到外线接球 | 借掩护到**外线**接球(非篮下) | 第2期 / 世界杯EP01 |
| `cross_screen` | cross screen (SAS) | 横掩护(弱→强横穿禁区)造低位机会 | 掩护人轨迹**平行底线**横穿禁区+低位接球 | 第24期 文班亚马 |
| `backdoor` | backdoor (SAS) | 反跑后门直切篮下接高吊 | 方向**反转**指向篮筐+防守抢前 | 第2期 |
| `horns` | horns (DEN/MIA, 马刺体系常用) | 牛角起手+横切掩护 | 两肘区站位+横掩护事件 | 第14期 |
| `motion_offense` | motion offense (读作马刺体系) | 连续手递手/传切自由流动 | ≥2 段 handoff/传导循环+无固定套路 | 第28期 |

> 说明：`priority.sas` 取自库中**以 SAS 标注**的 4 条(backdoor/cross screen/zipper/zipper backdoor)，
> 另并把马刺体系常用的 horns / motion_offense 一并纳入。`zipper` 与 `zipper_backdoor` 都源自第2期。

## 2. 验证片段筛查（用 `tactic_match_real.py` 跨片段跑）

⚠️ **以下数字只反映「原语产出量」，不构成「该片段含某战术」的证据**（见 A4.58 报告第3节）。

| clip | 球源 | 原语总数 | SCREEN.DOWN | SCREEN.CROSS | HANDOFF | CUT | 备注 |
|---|---|---|---|---|---|---|---|
| sas_det | A4.54 occluded | 19 | 8 | 5 | 6 | 0 | 老程裁定=非战术回合 |
| sas_lal | dense_head_top1 | 33 | 12 | 11 | 7 | 3 | 老程已裁裁判 tid7/8/38 |
| sas_hou | tracks.ball(稀疏) | 22 | 15 | 5 | 0 | 2 | 球源稀疏→手递手缺失；裁判未裁 |
| sas_nop | tracks.ball(稀疏) | 28 | 16 | 6 | 0 | 6 | 同上 |

**筛查结论（诚实）**：
- 4 个片段都产出掩护类原语，但**无一**能把 SAS 特征战术(`zipper_backdoor`/`cross_screen`)**判到**，
  原因=signature 未计算(Zone/防守人相对位置缺失) + 原语计数驱动。
- 因此**当前不可据此挑"验证片段"**。需要老程裁定哪一段确实是含战术的回合。

## 3. 解锁判别力的最短路径（按性价比排序）

1. **单帧球场配准**（`court_fit` 换清晰窗口 / 多帧联合，A2 记录 w1 失败 F≈8-9 R≈19）
   → 解锁所有 **Zone 依赖** signature（CORNER/WING/BLOCK/ELBOW、低位接球、外线接球）。
2. **防守人相对位置**：现有轨迹已含 `team` 字段 → 可用「最近异队球员」近似防守人
   → 解锁掩护**接触**判据、抢前(deny)判据（`defender_high_side`）、cross/backdoor 方向。
3. 有了 ①② 再开 **signature 评估**，把「原语计数」降为次要项。

## 4. 需要老程裁定的决策点

- **A**: 现 4 片段(或 sas_hou/sas_nop)里，哪一段**确含**一个可命名的战术回合？（给时段即可）
- **B**: 若无，是否授权从《NBA战术笔记》对应期号的比赛里另取一段"教科书式"片段做验证素材？

---

## 5. 🔴 老程裁定（2026-09-29，A4.58 追加）

> 老程看自证图后裁定：「**你给的图片，不算战术，算是简单配合吧**」。

- 结论：**现有 4 个片段（sas_det / sas_lal / sas_hou / sas_nop）呈现的是「简单配合」，不是战术。**
  ⇒ 决策点 A 的答案是**否**（这些片段不能用来验证战术匹配）。
- 据此对管线的改动：
  1. `tactic_models.json` 增加 `tier` 字段（**草案**：`basic`=简单配合/单动作，`system`=战术/多动作有序序列），
     分级规则**待老程定**（现按「子类级互异原语数 ≤1 → basic」自动判，分布 basic 13 / system 42）。
  2. `tactic_match_real.py` 输出改为**「窗口候选（非战术认定）」**，并写入 `tactic_claim=false` +
     `old_cheng_ruling`；每个窗口标注 `〔简单配合〕/〔战术(草案)〕`。
- 因此：**验证战术匹配必须换一段「确含战术」的片段**（决策点 B）。

**术语（待老程确认）**
| 层级 | 定义 | 例 |
|---|---|---|
| 简单配合 | 单个可观察动作（掩护/空切/手递手/单打），无固定战术意图编排 | 一次下掩护、一次手递手、一次背切 |
| 战术 | 多动作**有序编排** + 明确目的 + 针对防守反应 | horns、拉链后门、梯次掩护、EOG/ATO |
