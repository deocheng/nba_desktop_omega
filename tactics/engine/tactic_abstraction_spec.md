# 战术抽象表示规范（Tactic Abstraction Spec）

> 目的：把「人声讲解」里的战术，提炼成**机器可推理、可与比赛轨道匹配**的抽象数据。
> 这是从「语音转文字」迈向「理解 + 在素材中发掘」的中间层。
> 语义仍来自人声讲解（不凭空造），但**结构/原语/判别信号由本规范固化**，使工具能计算。

---

## 1. 核心思想

一个战术 = **一组有序的抽象事件（原语）+ 空间约束 + 触发条件 + 判别信号**。
- **原语（primitive）**：可被跟踪数据识别的最小动作单位（掩护/空切/手递手/突破/外弹…）。
- **空间约束（zone）**：事件发生的球场区域（弧顶/侧翼/底角/肘区/低位/禁区…）。
- **触发（trigger）**：战术成立所利用的防守反应（换防/抢前/沉退…）。
- **判别信号（signature）**：从轨道**可直接计算**的、区分本战术与其他战术的可观察量。

> 匹配 = 从轨道抽原语 → 与各战术的 `sequence`+`signature` 对齐打分 → 候选战术（老程裁定）。

---

## 2. 原语词表（Primitives）

### 2.1 行动原语（Action）
| 原语 | 含义 | 可观察代理（从轨道） |
|---|---|---|
| `SCREEN(type)` | 掩护 | 两球员距离收敛到 < d 且一者近零相对位移、另一者贴身通过 |
| `CUT(type)` | 无球切入 | 球员速度骤增且方向指向篮筐 |
| `HANDOFF` | 手递手 | 两球员近距离(<d)且球在二人间转移 |
| `DRIBBLE_ENTRY` | 运球推进 | 持球人由后场到前场/落位 |
| `PASS` | 传球 | 球离手、由 A 到 B |
| `DRIVE` | 突破 | 持球人连续高速且朝篮筐 |
| `POP` | 外弹 | 掩护后掩护人向三分线外移动 |
| `ROLL` | 顺下 | 掩护后掩护人向篮筐移动 |
| `SLIP` | 假掩护顺下 | 掩护动作未完成即顺下 |
| `POST_UP` | 背身要位 | 球员在低位静止+接触防守 |
| `REJECT` | 拒绝掩护 | 持球人反向绕过掩护 |
| `SPOT_UP` | 定点接球 | 外围接球直接出手 |
| `ISO` | 单打 | 全员拉开、持球人单点 |

### 2.2 掩护子类（screen subtype）
`DOWN`(下掩护) · `PIN_DOWN`(背掩护/下掩护) · `BACK`(后掩护) · `GHOST`(幽灵，**不接触**) ·
`CROSS`(横掩护，**轨迹与底线平行、穿禁区**) · `STAGGER`(梯次，**连续两个下掩护**) ·
`RAM`(为掩护人做的掩护) · `WEDGE`(小给大掩护) · `FLARE`(远切掩护) · `RIP`(转入掩护) ·
`ELEVATOR`(电梯门) · `FLEX` · `SLIP`

### 2.3 切入子类（cut subtype）
`BACKDOOR`(反跑后门) · `ZIPPER`(借掩护到外线接球) · `45`(45度切入) · `CURL`(卷切) ·
`FLARE`(远切) · `FADE` · `L_CUT` · `GIVE_GO`(给球走)

### 2.4 球场区域（Zone，需球场配准）
`BACKCOURT` `TOP`(弧顶) `WING_L` `WING_R` `CORNER_L` `CORNER_R`
`ELBOW_L` `ELBOW_R`(肘区/罚球线两端) `BLOCK_L` `BLOCK_R`(低位) `PAINT`(禁区) `RIM`

### 2.5 角色（Role）
`ball_handler` `screener` `cutter` `receiver` `roller` `popper` `spacer`

---

## 3. 战术模型结构（JSON Schema）

```jsonc
{
  "id": "zipper_backdoor",
  "names": ["zipper backdoor", "拉链挡拆", "zipper", "backdoor"],
  "goal": "一句话：这个战术想达成什么",
  "trigger": "利用防守的什么反应/条件（战术成立的前提）",
  "setup": { "formation": "起手站位描述",
             "zones": { "ball_handler": "TOP", "big1": "ELBOW_L", ... } },
  "primitives": ["SCREEN.DOWN", "CUT.ZIPPER", "CUT.BACKDOOR"],
  "sequence": [
    { "step": 1, "role": "ball_handler", "action": "DRIBBLE_ENTRY", "to_zone": "TOP" },
    { "step": 2, "role": "cutter",       "action": "CUT", "cut": "ZIPPER", "to_zone": "WING_L" },
    { "step": 3, "role": "cutter",       "action": "CUT", "cut": "BACKDOOR", "to_zone": "RIM",
      "condition": "defender_overplays_handoff" }
  ],
  "signature": [   // 🔴 从轨道可直接计算的判别量 —— 匹配的核心
    { "feat": "trajectory_reversal", "desc": "一球员先向外(zipper)后速度反向直指 RIM", "params": {} },
    { "feat": "defender_on_high_side", "desc": "防守人偏上线/抢前", "params": {} }
  ],
  "discriminative": "与最像的战术的关键差别",
  "source": { "clip": "第2期", "ts": [6.5, 79.4] }
}
```

---

## 4. 从轨道到战术的匹配流程

```
稳定化球员轨迹 + 球轨迹 + 球场配准
      │
      ▼  ① 区域映射：每帧每人 -> Zone（TOP/WING/CORNER/ELBOW/BLOCK/PAINT/RIM）
      ▼  ② 原语检测：SCREEN/CUT/HANDOFF/POP/ROLL/DRIVE ...（几何+运动学，带置信）
      ▼  ③ 序列对齐：把检测到的原语串 与 各模型 sequence 对齐（顺序+角色+区域约束）
      ▼  ④ 打分排序：命中 sequence 且满足 signature 的模型 -> 候选战术(带分)
      ▼  ⑤ 输出候选（老程裁定）—— 工具只提名，不盖章
```

匹配打分（草案）：`score = Σ w·(原语命中) · 顺序一致 − 违反约束惩罚`；低于阈值不出候选。

---

## 5. 与既有资产的关系
- **球场配准**（A2 已封口）→ 提供 Zone 映射。
- **球/球员轨迹**（A4.42/43、A4.51-54）→ 提供原语检测输入（球 93%、teamID QUALIFIED）。
- **战术库**（A4.56 ASR）→ 提供 `goal/trigger/discriminative` 的文字与来源；本规范把其中**可结构化的部分**固化为 `sequence/signature`。
- 🔴 纪律：`signature` 只允许**可观察量**；不得写"意图"这类不可计算项。语义来源仍是人声讲解；原语/结构是本规范的**形式化约定**，不是新发明的战术。
