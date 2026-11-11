# 战术板验证集 + 路线①洞察：模型库原语定义与真实战术语义错位（2026-10-03）

> 老程提供 4 个勇士經典戰術动画（tactical-board.com，理想俯视半场）。本文记录目视提取的
> 动作序列真值，及**对照模型库后暴露的错位**——这是比"原语词表缺口"更根本的一层。

## 一、资产核实
- 4 文件全部有效：608×1080 竖屏，11.8–21.2s，共 274 帧。已抽帧入 `action_work/tacboard/<name>/`。
- **进攻朝上（y 减小=朝筐）**——与我代码 `zone_of`/朝筐判据的坐标系假设**一致**（SpiltStagger/WeaveSpiltSTS 目视确认）。
- 每帧含 2 层圆图标（勇士黑圈=进攻、白圈=防守）、橙球、红圈/箭头标注、**中文字幕=动作步骤白话描述**。
- 已抽帧 4fps。`engine/tacboard.py` 已建（木纹定位球场 + 标定拟合 + 基础圆检测；**全自动图标跟踪尚不达标**，见 §四）。

## 二、动作序列真值（目视提取字幕，存 `action_work/tacboard/action_ground_truth.json`）

### 1. Screen Klay's Own（给 Klay 自己做掩护）
1. Wiggins 单打底角 → 2. 被迫传给低位的 Looney → 3. Looney 挡自己的防守者（Curry 防守者恍神）
→ 4. **对位沟通失误 Klay 直接切入** → 5. 获得空档
判据：**掩护人(Looney) 替切入人(Klay) 挡其对位人(Drummond)** + 低位接球 + 切入。

### 2. Spilt Action（Split Action 交叉跑位接球）
1. Curry 大角传球给 Wiggins → 2. Wiggins 传给低位的 Looney → 3. **Klay 跟 Wiggins 往彼此方向跑**
→ 4. Wiggins 帮 Klay 掩护 → 5. Klay 继续跑位并接球 → 6. 获得空档
判据：**两人往彼此方向交叉跑位(Weave) + 掩护 + 接球**。

### 3. Spilt Stagger（错位掩护）
1. Draymond 绕过掩护到强边接球 → 2. Wiggins 绕过 Klay 的挡拆 → 3. Wiggins 往内线卷曲切(Curl)
→ 4. **Klay 绕过 Looney 的掩护** → 5. Klay 往中间攻击 → 6. **对位归位时沟通失误** → 7. 获得空档
判据：**一个人绕过两个不同掩护人的屏**（Looney 换防沟通失误）= stagger 核心语义，**强时序**。

### 4. Weave Spilt STS（低位掩护接力）
1. 外围球员彼此手递手(Weave) → 2. **Curry 在低位帮 Draymond 掩护** → 3. Curry 帮 Wiggins 设下背挡
→ 4. **Curry 藉由 Moody 的掩护接球** → 5. 获得空档
判据：**低位起手 → 掩护 → 绕过该掩护接球**（STS=Side-To-Side 后场接力掩护）。

## 三、🔴 关键洞察：模型库原语定义与真实战术语义**错位**（比词表缺口更根本）

对照 `tactic_models.json`（55 模型）发现：

| 真实战术 | 真实语义所需 | 模型库 `need` | 错位性质 |
|---|---|---|---|
| **Spilt Stagger** | 绕过**两个不同掩护人**的屏 + 顺序 | `stagger_screen.need=[SCREEN.DOWN,SCREEN.DOWN,CUT]` | 两个 DOWN **不区分掩护人是否不同**，也**不验顺序**。真 stagger 核心=「换防沟通失误」，需**对位人切换**语义 |
| **Weave Spilt STS** | 低位起手→掩护→绕过**该掩护人**接球 | `sts.need=[SCREEN.STS,CUT,SCREEN.DOWN]` | 混了 STS/CUT/DOWN，但**无"低位(post)"概念**；且 STS 语义实为「手递手+低位掩护接力」，库定义过窄 |
| **Spilt Action** | 两人**交叉跑位**(Weave) | `sts` 近似 | **WEAVE 原语完全缺失**（`Spilt Action` 全程以 Weave/Split 跑位为主特征） |
| **Screen Klay's Own** | 掩护人替切入人挡**其对位人** | `pick_and_roll.need=[SCREEN.DOWN,DRIVE,ROLL]` | pick_and_roll 语义≈挡拆切入，但真动作是**低位传切+对位沟通失误**，非标准 PR |

**⇒ 根因再深化**：不只是"检测器产不出某些原语"，而是
1. **真值原语缺口**：`SPOT_UP`(接球后站定/投篮准备)、`WEAVE`(两人交叉跑) 当前**产不出**；
2. **判据语义不足**：`SCREEN.DOWN×2` 无法表达"绕过**不同**掩护人"这一 stagger 核心，也**不验时序**；
3. **缺"低位(post)"分区语义**：4 个战术中 3 个以低位发起点起，我现有 `zone_of` 有 LOW_POST 但原语层未用。

⇒ **即使把 WEAVE/SPOT_UP 补出来、hit@k 仍难上去**，因为模型库对 stagger/sts 的判据本身不够表意。这需要**同步修订 `tactic_models.json` 的 need/signature 定义**（模型库工程），非仅改检测器。

## 四、路线②（全自动图标跟踪）现状
- 木纹定位球场 + 单应标定：**可用**（4 个战术 calib 均拟合成功）。
- 球员圆检测：仅 Weave Spilt STS（蓝防守圈）部分成功；黑圈队检出率低；**Hough 噪声过大（40+/帧）不可用**。
- ⇒ 路线②需**重做图标检测**（模板匹配/边缘+圆度联合），当前**不阻塞路线①结论**。

## 五、下一步建议（待老程裁定）
- **A（推荐）**：先把 `SPOT_UP` + `WEAVE` 两个原语补进检测器（可证伪判据），**并同步评估**是否修订模型库 `stagger_screen/sts` 的 need 定义（加"掩护人不同"约束）。改动小、直击语义错位。
- **B**：先做路线②全自动管线（工程量大，收益暂不确定）。
- **C**：暂停战术识别，先回广播侧坐标系/GT 口径（hit@k 天花板的另一独立因素）。
