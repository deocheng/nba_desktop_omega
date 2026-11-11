# 自我纠错 + 坐标系根因定量报告（2026-10-03）

> 触发：老程要求路线①后继续。开工前只读复核磁盘，发现**上一份报告
> `tacboard_truth_and_model_mismatch_20261003.md` 存在三处事实错误**，本文逐条订正并给出根因定量证据。
> **本报告不含任何代码改动**，全部为只读复核+ 只读诊断脚本（跑在内存，不落盘不写仓库）。

---

## 〇、订正声明（老程先看这节）

上一份报告我写了三个数字/结论，**本次逐条核实为错**。按项目铁律「严禁假完整/ 数字必须现读」，现全部订正：

| # | 上一份报告的说法 | 核实后的事实 | 错因 |
|---|---|---|---|
| ① | 「13 个真值中 11 个结构性不可达」 | **key_primitive 门直接阻断 4/13**（zone_23 / slob / wedge_screen / short_roll）。另7/13 是 need 含不可达项（可部分得分，非阻断）。 | 我把「need 含不可达项」与「key 门阻断」混为一谈，前者是软约束后者才是硬阻断 |
| ② | 「检测器可产 SPOT_UP / POST_UP / POP / CUT.* 等一批原语」 | **检测器实际只能产 13 种**：`SCREEN` / `SCREEN.DOWN` / `SCREEN.CROSS` / `SCREEN.STS` / `SCREEN.GHOST` / `SCREEN.EXIT` / `SCREEN.TOUCH` / `HANDOFF` / `CUT` / `PASS` / `DRIVE` / `EXCHANGE` / `ROLL`。SPOT_UP **产不出**。 | 我凭模型库词表倒推「检测器应该能产」，没读 `detect_primitives` 源码，凭印象填的可达集 |
| ③ | 「模型库语义错位（比词表缺口更根本）是 hit@k 低的主因」 | 方向对，但**主因是坐标系**。见下。 | 把战术板（俯视系）上观察到的语义缺口的权重，高估到了广播素材上 |

**未受影响的结论**：hit@k = 2/11 = 18.2%（从 `batch_results.json` 现读复算一致）、`SCREEN.TOUCH×64 / SCREEN.CROSS×52 / SCREEN.STS×44 / PASS×36` 等原语频次、A 类修复有效性。

---

## 一、hit@k 现读复算（口径与上一份一致）

从 `action_work/tactic_notes_batch_fix1/batch_results.json` 的 `rows` 键复算：

| ep | GT 模型 | GT最佳 rank | hit@1 | hit@3 | hit@k |
|---|---|---|---|---|---|
| ep10 | pistol_5 | **1** | 1 | 1 | 1 |
| ep11 | exit_screen, zone_23 | None | 0 | 0 | 0 |
| ep12 | slob | None | 0 | 0 | 0 |
| ep13 | exchange_down | None | 0 | 0 | 0 |
| ep14 | horns | **2** | 0 | 1 | 1 |
| ep15 | stagger_screen | None | 0 | 0 | 0 |
| ep16 | wedge_screen | None | 0 | 0 | 0 |
| ep17 | roll, short_roll | None | 0 | 0 | 0 |
| ep18 | roll, short_roll | None | 0 | 0 | 0 |
| ep19 | ghost_screen, sts | None | 0 | 0 | 0 |
| ep20 | touch_screen | None | 0 | 0 | 0 |

**合计 n=11： hit@1 = 1 (9.1%)、hit@3 = 2 (18.2%)、hit@k = 2 (18.2%)**

---

## 二、严格按源码重算的可达性表（订正 ① ②）

读 `engine/tactic_match.py:60-126`（`detect_primitives` 全文）与 `engine/tactic_primitives_ext.py` 确认，检测器**真实可产 13 种**原语名（经 `_prim_name` = `type[.sub]` 拼接）：

```
SCREEN  SCREEN.DOWN  SCREEN.CROSS  SCREEN.STS  SCREEN.GHOST
SCREEN.EXIT  SCREEN.TOUCH  HANDOFF  CUT  PASS  DRIVE  EXCHANGE  ROLL
```

其中 `detect_primitives` 只产 `SCREEN.{DOWN,CROSS,None}` / `HANDOFF` / `CUT`（`_screen_sub` 源码 line128-138 只返回 DOWN/CROSS/None），其余 9 种来自 ext 模块。

| GT 模型 | key_primitive | key 门 | need 中检测器产不出的项 |
|---|---|---|---|
| pistol_5 | None | OK | — |
| exit_screen | SCREEN.EXIT | OK | SPOT_UP |
| zone_23 | ZONE_23 | **阻断** | ZONE_23 |
| slob | INBOUND | **阻断** | INBOUND, SCREEN.STAGGER, SCREEN.FLARE |
| exchange_down | EXCHANGE | OK | — |
| horns | SCREEN.CROSS | OK | CUT.BACKDOOR |
| stagger_screen | SCREEN.DOWN | OK | — |
| wedge_screen | SCREEN.WEDGE | **阻断** | SCREEN.WEDGE |
| roll | ROLL | OK | — |
| short_roll | SHORT_ROLL | **阻断** | SHORT_ROLL |
| ghost_screen | SCREEN.GHOST | OK | — |
| sts | SCREEN.STS | OK | — |
| touch_screen | SCREEN.TOUCH | OK | PASS.POCKET |

- **① key_primitive 硬阻断：4/13**（不是 11/13）
- **② need 含不可达项：7/13**（软约束，仍可部分得分）
- **③ 模型库词表 45 种 − 检测器可产 13 种 = 缺口 32 种**（上一份报告说 22 种，错在把不可达项算作可产）

---

## 三、🔴 根因：坐标系不一致（本次新发现，优先级高于补原语）

### 3.1 代码假设 vs 实际数据

| 项 | 内容 | 证据 |
|---|---|---|
| 代码假设坐标系 | 半场俯视，x∈[-250,250]、y∈[0,940]、篮筐 y≈57；「y 减小 = 朝进攻篮筐」 | `tactic_match.py:120` `toward = p1[1] < p0[1]`，注释「y 减小 = 朝进攻篮筐」 |
| 实际数据坐标系 | **横屏广播像素**，x∈[7,1277]、y∈[36,716] | 22/22 段 `tracks_cf.json` 现读，x 上界全部 >600（1280×720 画面） |
| 适配器是否做变换 | **无** | `tactic_match_real.py` docstring 自述：「球场配准缺失…本脚本在**图像像素空间**运行」 |

代码里其实**已经承认**了这件事（`tactic_match_real.py` docstring 第 1 条诚实边界：「CUT/DRIVE 的『朝篮筐』方向是**假设**（`--rim-dir`，默认 up，不可靠）」），但这个假设**从未被量化影响**，导致此前把 hit@k低归因到「词表缺口/ 语义错位」。

### 3.2 定量证据 A：SCREEN 子类严重失衡

真实篮球里**下掩护（DOWN）远多于横掩护（CROSS）**。但全11 期事件池：

```
SCREEN.CROSS  52   ← 横掩护
SCREEN.DOWN   10   ← 下掩护     ⇒ 5.2:1 完全反了
```

### 3.3 定量证据 B：判据级根因（只读诊断，n=1420 掩护事件）

复刻 `_screen_sub` 的方向主导轴判据（`|dy|>=2|dx|`→DOWN，`|dx|>=2|dy|`→CROSS），在 22 段上统计：

```
判定分布: DOWN 299 (21.1%)  CROSS 677 (47.7%)  None 444 (31.3%)

|dx| 中位 = 8.4 px      |dy| 中位 = 3.4 px     dy 中位 = +0.0 px
```

**判读**：横屏侧视下球员机动以**横向（dx）为主**，纵向位移极小。`|dx| >= 2|dy|` 因此大量成立 → 绝大多数掩护被误判为 CROSS。`_screen_sub` 的注释写着「尺度无关」，但它隐含假设了**俯视系下纵向机动主导**；这个前提在横屏素材上不成立 ⇒ **判据本身在错坐标系下失效，不是阈值问题**。

**这解释了为什么 `stagger_screen`（key=SCREEN.DOWN）拿不到分**：不是「语料不含梯次掩护」，而是下掩护在横屏素材里**被系统性误标成 CROSS**，判别原语根本产不出来。

### 3.4 定量证据 C：方向类原语几乎不触发

全 11 期事件池里 `DRIVE / EXCHANGE / ROLL` 频次均为 **0**。三者都依赖「朝筐」方向判据（`toward`），坐标系错误 ⇒ 方向判据恒错 ⇒ 结构性零触发。**不是阈值问题**（此前已验证过放宽阈值仍 0 次）。

---

## 四、结论重排（优先级）

| 优先级 | 问题 | 性质 | 可证伪修法 |
|---|---|---|---|
| **P0** | 横屏广播坐标 → 半场俯视坐标缺变换 | **架构断裂**（`tactic_match_real.py` 自述「球场配准缺失」） | 用已有 `half_court_calib.json` + `half_court_spatial_engine.py` 做 pixel→court 单应，在匹配**前**统一坐标系 |
| **P1** | SCREEN.DOWN/CROSS 误判（5.2:1 反转） | P0 的**衍生**症状 | 同P0；坐标系正确后重测判据，**不得先调阈值** |
| **P2** | 方向原语 DRIVE/EXCHANGE/ROLL 零触发 | P0 的衍生症状 | 同 P0 |
| **P3** | 原语词表缺口 32 种 | 真实但次要 | 坐标系修好后，按「哪些 GT 真的需要」逐个补；**不批量硬凑** |
| **P4** | 模型库 need/signature 语义不足 | 真实但次要 | 战术板真值已落盘，等P0 修好后用真值反推该怎么改 |

### P0 的现成阻塞点（已核实）

- `action_work/court_calib/half_court_calib.json`：全库**仅 `ep24_s1` 有标定**，且状态 `UNRESOLVED`（`open_blockers`：近端边线、中线未定；紫漆内白圆是否罚球圈未定；真实三分线未定位）。
- ep10–ep20 **全部无标定**。
- ⇒ P0 卡在**需要老程点选场地线**。这是 A5.14「禁硬凑」纪律下唯一合规的解法：**不点选就不能修**。

---

## 五、待老程裁定（选项已按新证据重排）

**A（推荐）= 先解 P0 坐标系，不动原语**
范围：把 `half_court_spatial_engine.py` 接进 `tactic_match_real.load_clip`，在原语检测**前**做 pixel→court 单应。**前置条件：老程为 ep10–ep20 段点选场地线**（近端边线+ 中线 + 三分线），使标定从 UNRESOLVED → RESOLVED。
预期：SCREEN.DOWN/CROSS 比值回归正常、DRIVE/ROLL/EXCHANGE 从 0 变为可触发 ⇒ 才谈得上重测hit@k。
风险：改动面比补原语大（动匹配入口），但**不碰模型库、不碰检测判据**，可A/B 回退。

**B = 先补 P3 原语词表（在错误坐标系上补）**
诚实评估：在P0 未修前补出的原语，方向类（DRIVE/ROLL）依旧零触发，SCREEN 类依旧误判 ⇒ **大概率白做**。除非只补非方向类（`SPOT_UP` / `PASS.POCKET` / `CUT.BACKDOOR`），这三项不依赖坐标系，可独立验证。

**C = 先回战术板路线②（全自动图标跟踪）**
与广播侧完全解耦，可并行推进，但**不改善广播侧 hit@k**。

**D = 只做路线①已落盘部分（战术板真值 + 模型库语义修订建议）**
已完成，无需追加。

**我的建议**：`A` 为主（但需老程先点选场地线，否则物理上动不了）；若老程暂时不想点线，可先做 `B` 的**非方向类子集**（SPOT_UP / PASS.POCKET / CUT.BACKDOOR）作为低风险并行项。

---

## 附：本次复现命令（只读）

```bash
cd /Volumes/12T/NBA/action_analysis
PY=/Users/deocheng/.workbuddy/binaries/python/envs/action05/bin/python

# ① hit@k 复算
$PY -c "import json;d=json.load(open('action_work/tactic_notes_batch_fix1/batch_results.json'));\
r=d['rows'];print(sum(x['hit_at1'] for x in r),sum(x['hit_at3'] for x in r),sum(x['hit_atk'] for x in r))"

# ② 坐标系核查（22 段 x 上界）
$PY -c "import json,glob,os;[print(os.path.basename(s),max((p['box'][0]+p['box'][2])/2 \
 for fr in json.load(open(os.path.join(s,'tracks_cf.json')))['frames'] \
 for p in fr.get('players') or [] if p.get('box'))) for s in sorted(glob.glob('action_work/tactic_notes_batch_fix1/segments/*'))]"

# ③ 可达性表
$PY -c "import json;ms=json.load(open('action_work/tactic_models.json'));\
ms=ms['models'] if isinstance(ms,dict) else ms;\
print(sorted({x for m in ms for x in m.get('primitives',[])}))"
```
