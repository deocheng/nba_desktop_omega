# 端到端短窗实证结果：链路健康，但战术匹配层未达 path C 门禁（2026-10-03）

> 对应老程 2026-10-03 指示「A 类 = 端到端短窗实证 + 可证伪 KPI」。本文是 A 类的**实证结论（负结果）**。

## 结论一句话
检测/场地/裁判/队色/球/事件**全链路健康**（视觉自证通过），但**战术匹配层 hit@1/3/k = 0/11**，且真值战术在候选池内却从未返回 ⇒ **path C「任务级事件可用性」在匹配层未达标**；瓶颈已从 ID(门①-B) 转移到**战术匹配评分设计**。

---

## 1. 方法
- 语料：`NBA战术笔记` 第10–20期（11 期，跨段复验，禁单段过拟合）。每期定位≤2 个实战段，`--seg-cap 45`（对齐 40~50s 短窗目标）。
- 链路：探针(实战帧) → 段抽取 → `segment_detect_track`(YOLO person+ball) → `court_filter` → `assign_team`(队色) → `tactic_notes_totracks` → `tactic_match.detect_primitives` → `match_windowed` → GT 比对(`hit@1/3/k`)。
- GT 来源：`tactic_library.json`（期级标题战术）经 `alias_index` 映射到模型 id。

## 2. 链路健康度（冒烟 ep10 + 视觉自证）
- 单段 s0（t0=70，280帧/28s）1m1s 跑通，检出事件 9 个（CUT1 / SCREEN.CROSS3 / HANDOFF3 / SCREEN2）。
- **队色归属视觉自证（f140，BOS白 vs MIA黑）**：红框=黑球衣(MIA)、青框=白球衣(BOS)，**两队干净分离**；球(绿框)在位。⇒ 此前 `team_info.center_names` 两队都显示 'white' 是**锚点命名过粗的显示假象，非功能失效**（视觉自证纠正了一次错误预判）。
- 球覆盖 131/280 帧(47%, sparse，合理)；队色 0/1/None 均落盘。
- 注：`ball_tracks.json` 契约键为 `frame/file/ball/players`，球键是 `bbox`；无 `ball_handler` 键（convert 不写，非故障）。

## 3. 战术命中 KPI（跨 11 期，22 段）
| 指标 | 结果 |
|---|---|
| hit@1 | **0/11 (0.0%)** |
| hit@3 | **0/11 (0.0%)** |
| hit@k | **0/11 (0.0%)** |

- top1 跨 11 期**恒为泛化 primitive**：`cross_screen`×7 / `handoff`×2 / `cut_family`×1 / `None`×其余；**从未出现任何一个该期的具体真值战术**。
- 每期均定位到 2 个实战段（非「没找到段」）。

## 4. 排除「配置假象」——真值在候选池内
- 初查曾因类型混淆（`models` 是 list，`g in models` 按值比对）误判「真值不在池」。**已纠正**。
- 复查：候选池 55 模型，`pistol_5 / exit_screen / zone_23 / slob / exchange_down / horns / stagger_screen / wedge_screen / roll / short_roll / ghost_screen / sts / touch_screen` **全部 in_pool=True**。
- ⇒ **不是配置 bug，真值是可被返回的候选**；返回 0 是匹配器真实失效。

## 5. 根因（数据坐实）：复杂度偏见的饱和评分器
`tactic_match.match`/`match_windowed` 机制：
- 模型按「所需原语 need 是否在 6s 窗事件池中」计分：精确命中 +1.0、同类弱命中 +0.5；`cov = hit/len(need)`；`cov>=min_cov(0.5)` 且 `hit>0` 即入围。
- 排序 `(unverified, -coverage, -score)`；`signature_evaluated=False`。

坐实证据：
| 模型 | need | 原语 | key 门 | seq |
|---|---|---|---|---|
| cross_screen | **1** | SCREEN.CROSS | SCREEN.CROSS | F |
| cut_family | **1** | CUT | CUT | F |
| handoff | **1** | HANDOFF | HANDOFF | F |
| pistol_5 | 3 | SCREEN.DOWN+DRIVE+PASS | — | F |
| exit_screen | 3 | SCREEN.EXIT+CUT+SPOT_UP | SCREEN.EXIT | F |
| slob | 4 | INBOUND+STAGGER+FLARE+CUT | INBOUND | F |
| exchange_down | 2 | EXCHANGE+SCREEN.DOWN | EXCHANGE | **T** |
| sts | 3 | SCREEN.STS+CUT+SCREEN.DOWN | SCREEN.STS | **T** |

- **单原语模型一出现即拿满分** `score=1.0, cov=1.0`（同时也是最高覆盖率），结构上压过任何 `cov<1.0` 的多原语真值。
- **55 模型中 13 个是 need=1 的"易饱和"模型**（cross_screen/cut_family/handoff/zone_23/backdoor/…）。
- 真值战术需 2–4 个原语在 6s 窗内按序共现，且 `signature_evaluated=False` 时 `seq_dependent` 真值（exchange_down/stagger_screen/sts）被标记 unverified → 排序下沉。

⇒ **hit@k=0/11 是评分设计的必然**：匹配器近似恒返回「窗口内最常见的单原语战术」，与真实战术脱钩。**不是 ID 问题、不是队色问题、不是配置问题——是匹配器评分层缺陷。**

## 6. 对 path C 门禁的含义
- `milestone_05_solution` 已把验收门改为 path C「任务级事件可用性」。本次实证表明：**该门禁当前未通过**，卡在战术匹配层（而非门①-B 的 ID 层）。
- 短窗(40~50s)哲学本身未被否定——链路能跑、队色/球/事件都正常；**失败的是"从事件判定具体战术"这一步的判别力**。

## 7. 推荐修法（需老程授权后再改代码；当前仅诊断，未动）
1. **复杂度归一化 / 单原语地板**：对 `need==1` 模型降权或设最小原语数门槛，避免满分泛型霸榜；或改排名用「加权覆盖率 + 复杂度惩罚」。
2. **开启序列/签名评估**：`signature_evaluated=True` 并让 `seq_dependent` 模型参与正常排名（否则 exchange/stagger/sts 类真值永远下沉）。
3. **收窄原语粒度**：现有 `SCREEN.* / CUT / HANDOFF` 太粗，泛型战术天然易命中；需更判别性的原语或 team/handler 上下文。
4. **KPI 重定义（重要）**：GT 是期级标题战术、段级未必含该战术（跑批脚本自带诚实边界）。在匹配器修好前，**hit@k 不可作为可信 KPI**，否则即"假完整"。建议先修评分器 + 收紧 GT 口径，再重测。

## 附：产物
- 冒烟：`action_work/tactic_notes_batch_smoke/`（ep10，2 段）+ `/tmp/ep10_s0_overlay/`（视觉自证图）
- KPI：`action_work/tactic_notes_batch_kpi/batch_results.{json,csv}`（11 期）
