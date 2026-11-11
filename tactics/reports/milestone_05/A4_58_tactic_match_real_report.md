# A4.58 战术「理解层」推进报告 —— 抽象模型扩容 + 真实素材接入

日期: 2026-09-29 ｜ 线索: A4.56(战术库 ASR) → A4.57(抽象+匹配层) → A4.58(本文)
纪律: 语义来自人声；signature 只用可观察量；匹配只提名，裁定归老程；无逐行证据不下"完整/达标"。

---

## 1. 交付物

| 文件 | 内容 |
|---|---|
| `action_work/tactic_models.json` | **55 个**可计算战术模型 + `alias_index`(61 库条目→模型) |
| `action_work/tactic_models_overview.md` | 模型人读总表(goal/trigger/sequence/signature/判别) |
| `engine/tactic_match.py` | 匹配引擎：原语检测(阈值可注入+站定门) / 窗口匹配 / 覆盖率自证 |
| `engine/tactic_match_real.py` | **真实素材桥**：稳定球员轨迹+球轨迹 → 原语 → 窗口候选 + 视觉自证 |
| `action_work/validate/<clip>_tactic_match_real.json` | 每片段结果(primitives/windows/caveats) |
| `action_work/validate/<clip>_tactic_match_real_selfevid.png` | 原语事件画回原帧(自证) |

## 2. 第①步：61 条战术 → 55 个去重可计算模型（完成）

- 读全部 61 条人声原文（`tactic_library_dump.md`），按 `tactic_abstraction_spec.md` 逐条蒸馏为
  `sequence`(有序原语) + `signature`(可观察判别量) + `discriminative`(与最近邻战术的差别)。
- 重复库条目（handoff/手递手战术、stagger/tiered screen、lift/上提+分散挡拆、sideline/边线球、
  zipper/拉链挡拆 等）**并入同一模型**，由 `alias_index` 保证 61 条全部可解析。
- 自证：`tactic_match.py --coverage` → 模型 55 / 库条目 61 / 指向不存在的模型: 无。
- 合成 demo 回归：`horns_backdoor` → **horns 榜首**(1.50/cov0.75)；`handoff` → **handoff 榜首**(1.00/cov1.00)。

## 3. 第②步：真实素材接入（链路已通，质量门未过）

**链路**（`tactic_match_real.py`）：稳定轨迹(A4.43) + 球轨迹(A4.54 遮挡补全) → 剔非球员(老程裁定 tid)
→ 轨道契约(图像像素) → 原语检测 → **时间窗匹配**(战术=局部序列) → 候选 + 自证图。

实测（阈值全部由本片段分布导出，非手写）：

| clip | 球源 | 中位体长 | 中位帧位移 | d_screen | v_cut | 原语(个) |
|---|---|---|---|---|---|---|
| sas_det | A4.54 occluded | 254.9px | 14.7px | 127.5 | 50.7 | 19 (CROSS5/DOWN8/HANDOFF6) |
| sas_lal | dense_head_top1 | 236.4px | 9.9px | 118.2 | 63.1 | 33 (CROSS11/DOWN12/HANDOFF7/CUT3) |

### 🔴 诚实边界（未解，勿当作结论）
1. **球场配准缺失**：本素材无 pixel→court 单应（`court_fit` 在 w1 失败 F≈8-9 / R≈19，A2 已记录）。
   → 依赖 **Zone** 的 signature（CORNER/WING/BLOCK 判定）**未计算**；CUT/DRIVE 的「朝篮筐」为**假设**。
2. **无防守人轨迹** → 无法验证「掩护是否真发生接触」(spec 的实质判据)；掩护检测用**站定门**近似
   （一者近零位移、另一者通过），**不收横向穿场的 cross screen**。
3. **signature 未评估**：匹配当前**只用 primitives**（`signature_evaluated=False`）。故候选分被
   「原语计数」驱动 —— sas_det/sas_lal 榜首均为 `eog`，是**原语泛化**所致，**不是**「该片段是 EOG 战术」。
   （🔴 此缺陷已在 §5 修复：判别原语门 + 时序依赖降级 + 方向主导轴子类。修复后 `eog`/`stagger`/
   `second_screen` 不再虚假霸榜。）
4. **样本不含战术**：sas_det 经老程裁定为「即兴配合且失败」的非战术回合 → 本报告**不**下任何战术结论。
5. 自证图显示：站定门后 FP 明显减少，但仍有靠近边线相互站立的误报 → 原语检测**特异性未达标**。

**结论**：真实素材 → 原语 → 候选的**链路已打通且可复现**；但**特异性/判别力未达标**，
根因=配准缺失 + 无防守人相对位置 + signature 未计算。**在错位/缺失证据上不得产出"发掘结果"。**

## 4. 第③步：SAS 重点战术优先 + 验证片段（下一步）

- 马刺体系相关模型已就位：`zipper_backdoor` / `cross_screen` / `horns` / `motion_offense` 等。
- 验证片段前提（老程裁定）：需一段**确含战术**的片段；现有 2 片段均**非**战术回合。
  → 候选素材：`sas_hou` / `sas_nop` / `w1–w4`（有帧与稳定轨迹），**其内容是否为战术回合须老程裁定**。
- 补齐判别力的最短路径（按性价比）：
  ① 单帧球场配准（线模型拟合，`court_fit` 换更清晰窗口/多帧联合）→ 解锁 Zone 依赖 signature；
  ② 防守人相对位置（现有轨迹已含对手队，可按 team 字段取「最近异队」近似防守人）→ 解锁掩护接触/抢前判据；
  ③ 有了①②再开 signature 评估，并把「原语计数」降为次要项。

---

## 5. A4.59：用《战术笔记》实战片段验证匹配（闭环 ✅）

> 老程指令：「战术笔记里的片段都是战术啊，你可以自己截取完整战术然后对比战术解析。」
> → 战术笔记里的**实战片段本身=战术**（有当期讲解作真值），截取出来跑分析，再与讲解对照。

### 5.1 验证链（新增工具）

| 文件 | 作用 |
|---|---|
| `engine/tactic_notes_extract.py` | 从《战术笔记》视频按 `--ss/--to/--fps` 抽帧 → `frames/`+`frames.json`+`meta.json`（**只截取，不判断**） |
| `engine/tactic_notes_totracks.py` | `segment_detect_track.py` 的 `tracks.json` → 匹配引擎契约 `ball_tracks.json` |
| `action_work/tactic_notes_clips/ep24_crossscreen/` | 第24期 `82–103s` 截取（202 帧@10fps，源 1280×720@25） |

### 5.2 首轮结果（修正前）暴露 3 个造假源

片段真值 = `cross_screen`（第24期标题 + 画面字幕「让文班亚马和科林斯互相做**横掩护**」）。
但修正前候选榜首是 `eog`（4.00/cov0.80），`cross_screen` **未进前 3**。逐行诊断出 3 个造假源：

1. **子类判据错**：CROSS/DOWN 用 `|dx|>2.5·disp 且 |dy|<1.5·disp`（disp_med=7.75 → 19px/11px），
   把 111px 的横移（f136-139）误标 **DOWN**、把 20px 的漂移误标 **CROSS** → 28 个原语中大量噪声。
2. **多原语计数灌分**：`eog` 需 `CROSS+STS+3×DOWN`，命中 4/5 → 绝对分 4.0 霸榜；其判别量 `SCREEN.STS`
   **根本检不出**，且本片段非末段场景 → 纯属计数堆叠。
3. **`cross_screen` 被不可检的 `POST_UP` 卡死**：其 `discriminative` 明写判别量=「掩护人横穿禁区」，
   即横掩护本身（**可检**），却被 `POST_UP`（需防守人相对位置，检不出）拉低覆盖率。

### 5.3 三处修正（`tactic_match.py` + `tactic_models.json`）

| 修正 | 内容 |
|---|---|
| **A. 方向主导轴子类** | `_screen_sub(dx,dy)`：`|dy|≥2|dx|`→DOWN；`|dx|≥2|dy|`→CROSS；否则 None（通用 SCREEN，仅 0.5 弱命中）。尺度无关。 |
| **B. 通行距离门** | `_mk_screen` 叠加 `hi ≥ 1/4·中位体长`（=35.6px）→ 剔除「两人相邻漂移」的假掩护。 |
| **C. 判别原语门 + 时序依赖降级** | 模型新增 `key_primitive`(判别量直指的原语，缺失则出局) 与 `seq_dependent`(判别量=次序/重复，signature 未评估时降级)。rank 改为 `(已验证, 覆盖率, 绝对分)`。`cross_screen` 的必要集收紧为 `[SCREEN.CROSS]`（`POST_UP` 移入 `confirm_primitives`）。 |

### 5.4 修正后结果（✅ 真值胜出）

**原语**：28 → **15**（`SCREEN.CROSS`×11 / `CUT`×2 / `SCREEN.DOWN`×1 / `SCREEN`×1）——
11 个 CROSS 全部 `travel=63–116px` 且 `|dx|≥2|dy|`（真横移），噪声消失。

**候选榜单**（全池 & SAS 重点池一致）：

| rank | 模型 | 分/覆盖率 | 备注 |
|---|---|---|---|
| **1** | **`cross_screen`** | **1.00 / cov 1.00** | 判别量 `SCREEN.CROSS` 已验证 ✅（win f35-95 / f65-125 / f95-155 / f125-185） |
| 2 | horns / split_cut | 1.50·0.75 / 1.00·0.50 | 需 `CROSS+CUT.BACKDOOR`，后门缺 → 仅部分满足 |
| — | `eog` | — | **被判别原语门剔除**（无 `SCREEN.STS`） |
| — | `stagger_screen` / `second_screen` | — | **时序依赖降级**（判别量=「连续两个/重复」，当前验不了） |

**视觉+文本自证**（`..._v2_selfevid.png`）：检出框所在帧字幕逐字出现「横掩护」
（「让文班亚马和科林斯互相做横掩护」「这并不是文班使用横掩护得分的唯一回合」）→ CROSS 检出为**真**。

**回归**（4 片段全部跑通，无 `eog`/`stagger`/`second_screen` 虚假霸榜）：

| clip | 原语 | 榜首 | 说明 |
|---|---|---|---|
| ep24_crossscreen（真值 cross_screen） | 15 | **cross_screen** | ✅ 真值胜出 |
| sas_det（老程裁=简单配合） | 8 (HANDOFF6/CROSS2) | handoff + cross_screen | 诚实候选，非战术认定 |
| sas_lal（老程裁=简单配合） | 13 (HANDOFF7/CROSS2/CUT3) | handoff + cross_screen | 同上 |
| demo horns_backdoor | 2 | cross_screen / cut_family | ⚠️ 排序改为**覆盖率优先**后，全满足的单原语模型排在部分满足的 `horns`(0.75) 之前 |

### 5.5 诚实边界（仍然成立）
- **排名改动的代价**：`(已验证, 覆盖率, 绝对分)` 覆盖率优先 → **单原语模型易得 cov=1.0**，
  会压过「多原语但部分满足」的模型。这是「完整命中 > 部分命中」的取舍，已显式披露；
  泛型类模型（`cut_family`=无球终结总类、`handoff`）出现在榜内属**原语真实**但**非战术认定**。
- **Zone / 防守人仍缺**：`signature` 仍未评估；`cross_screen` 的第 2 signature（低位接球）与
  `horns` 的起手落位（牛角）**未验证** —— 故只可说「检出横掩护原语」，**不可**说「已确认该回合就是该战术」。
- **裁定归老程**：本闭环证明「真值战术在原语层可被正确提名」，**不等于**战术理解已完成。

---
*本报告数字均从磁盘产物现读；无逐行证据处已显式标注未解。*
