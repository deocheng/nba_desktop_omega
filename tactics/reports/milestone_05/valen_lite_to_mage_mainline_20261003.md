# Valen 精简版 → Mage-VL 主线：架构转向设计（2026-10-03）

## 0. 决策背景
- **Valen 整体（小模型学生 + 严格 ASR 监督 + 三级验证门）优先级降级**。
- 根因链条：门①-B 身份正确性已裁定为**已知架构边界（Option 1，2026-10-03 老程裁定）** → Valen 维持锁；全局 ID 问题非 `stabilize` 参数或 DINOv2 外观重连可解（路线 A 实测证伪）。
- 但 Valen 设计中**大量块与「身份 / 小模型打分」无关**，可拆出直接接到现行管线或 Mage-VL，把不适合的部分丢掉。
- 本轮目标 = 把 Valen 拆成「保留 / 丢弃」两堆，并定义「Valen 精简版 → Mage 主线」的目标架构。

## 1. Valen 设计分解（保留 / 丢弃 / 工程接法）

| Valen 原设计 | 保留? | 接到现行方案 / Mage-VL 的接法 |
|---|---|---|
| 输入必须是 clip（16–32 帧 / 40–50s） | ✅ 保留 | 直接作为 **Mage-VL 与规则事件的标准输入单位**；已与 `tactic_notes_batch.py --seg-cap 45`（对齐 40–50s）一致 |
| 标签只信任 ASR（不让模型自评） | ✅ 保留 | Mage-VL 生成描述后，**用 ASR 做对照验证**，而不是让 Mage-VL 自己打分 |
| 三级验证门（冒烟 → 信息量对照 → 真值闭环） | ✅ 保留简化版 | 用于 Mage-VL：先跑通 → 对比「单帧 vs clip」信息量 → 用 ASR 留出集评估 |
| 必须同时报随机 + 多数类双基线 | ✅ 保留 | 评估**任何**动作/关系预测时都带上，防止假完整（直接约束 hit@k） |
| RelateAnything 空间关系作为输入 | ✅ 保留 | 继续用，作为 Mage-VL 的**补充结构化信号** |
| 小模型（0.8B / 2B）做候选打分 | ❌ 暂缓 | 等红线解除再考虑；现在用**规则 + Mage-VL 描述**即可 |
| 严格「学生」定位、禁止自生成标签 | ✅ 保留精神 | Mage-VL **只做描述**，不让它直接输出最终战术标签 |

## 2. 转向后目标架构（Valen 精简版 → Mage 主线）

```
标准输入: 统一切成 40–50 秒半场干净片段（已过滤观众 + 裁判）
            ↑ 来自 C→B→A 主线产出
   │
   ├─ 并行两路信号
   │   ├─ Mage-VL ──────────────→ 高层自然语言描述（谁在挡 / 谁切入 / 球权变化 …）
   │   └─ RelateAnything + 现有规则 (detect_primitives) → 结构化关系与事件
   │
   ├─ 真值对齐: 仅用 ASR 做验证（模型不当裁判）
   │
   └─ 评估纪律: 双基线 + 信息量对照（clip 是否真比单帧强）
```

**丢弃项**：不上 Valen 小模型打分器，也不为它强行解决全局 ID 问题。

## 3. 与 C→B→A 主线的依赖关系

| 主线步骤 | 对 Mage 主线的意义 |
|---|---|
| **C** 只在纯净段跑 A | 提供「干净 clip」输入源（无图版污染、无观众/裁判） |
| **B** 先净化语料（镜头切换点统计 + 图版段分离） | 图版段（战术讲解纸板）**不进规则事件**，但可独立作为 Mage-VL 理解层素材 |
| **A** 单应接入 pixel→court | 提供**正确坐标系** → RelateAnything + 规则事件在 court-space 才正确（P0 根因所在） |

⇒ **Mage-VL 主线是 C→B→A 的下游消费者**；RelateAnything + 规则事件必须先过 P0（A 单应接入）才可信。

## 4. 评估纪律落地（接现有铁律）

- **双基线 + 信息量对照** → 直接约束 `hit@k`（已被 2026-10-03 裁定「不是可信 KPI」，须带双基线重评）。
- **三级验证门简化版** → Mage-VL probe 三步：① 跑通（冒烟）；② 单帧 vs clip 信息量对照；③ ASR 留出集闭环。
- **防假完整**：任何「Mage-VL 描述质量高」结论须由 **ASR 留出集 + 双基线** 支撑，不让 Mage-VL 自证。

## 5. 立即可动块 vs 需前置的门

**可立即做（不依赖权重 / 标定）**：
- 写 `mage_vl_tactic_probe.py` 框架（gold-reference 对齐逻辑：ASR + `detect_primitives` 输出做 reference，信息量对照 clip vs 单帧）。
- RelateAnything 继续作为结构化信号接入。

**需前置**：
- Mage-VL 实际推理 → 需下载权重（Q4 ~3–4GB / BF16 ~10GB），**本地当前无权重**（ollama 仅 qwen 文本/代码模型，无 VL；HF cache 无 mage）。
- 规则事件坐标正确 → 需 A 单应接入（P0），**卡老程点选标定**（ep24_s1 UNRESOLVED，ep10–20 无标定）。

## 6. 待老程裁定
1. 权重下载规格：Q4 量化（~3–4GB，快、够用）还是 BF16（~10GB，保真）？或在主线推进后再说。
2. 是否现在写 `mage_vl_tactic_probe.py` 框架（不下载权重，先跑通 gold-reference 对齐逻辑）？
3. 图版段（战术讲解纸板）的处理归属：独立作为 Mage-VL 理解层素材，还是完全剔除出战术分析语料？

---

## 7. 分层协作架构（检测层 + 理解层 + 打分层，老程 16:35 裁定）

> 不是把三个模型硬拼成一个大杂烩，而是**分层协作、职责分离**。

```
原始视频
   ↓
【检测层 · YOLO 系】（必须保留，主力）
   - 球检测（multiscale + dense 头）
   - 球员检测 + pose
   - 半场多边形过滤 + 裁判去除
   - 短时跟踪 + 持球者
   - RelateAnything 空间关系
   ↓
干净的结构化信号（场内球员、球、关系、战术板坐标）
   ↓
【理解层 · Mage-VL】（新增，互补）
   - 输入：40–50s 干净半场 clip + 可选结构化提示
   - 输出：高层战术描述、事件候选
   ↓
【打分层 · Valen】（远期，可选）
   - 只在红线解除后，对候选动作打分
   - 标签严格来自 ASR
```

### 能力矩阵（为什么必须融合，而非二选一）
| 能力 | YOLO 系 | Mage-VL | Valen |
|---|---|---|---|
| 精确球/人定位 | 强 | 弱 | 无 |
| 持球者/轨迹/ID | 强 | 弱 | 无 |
| 空间几何过滤 | 强 | 弱 | 无 |
| 高层战术语义理解 | 弱 | 强 | 中 |
| 动作概率打分 | 无 | 弱 | 强（设计目标）|
| 40–50s clip 总结 | 弱 | 强 | 中 |

⇒ YOLO 解决「谁在哪、球在哪、谁持球」；Mage-VL 解决「这段在打什么战术」；Valen 解决「候选动作里哪个更可能」。三者职责不同，融合才完整。

### 融合方式（由浅入深）
- **最轻（现在就做）**：YOLO 管线跑完 → 干净 clip + 结构化 JSON → Mage-VL 只看视频（或视频+简单文字提示）生成描述；两边结果后对齐，人工/ASR 对比。
- **中等（推荐下一步）**：把 YOLO 关键信息（场上球员数、持球者、主要关系）作为文字提示喂 Mage-VL，让它在「已知检测结果」基础上推理，减少幻觉。
- **深度（远期）**：Mage-VL 描述 + RelateAnything 关系 → 生成候选动作列表 → Valen 打分。此时才需要 Valen。

### 铁律（老程明确）
- **必须融合 YOLO + Mage-VL，但保持分层**：YOLO 做感知，Mage-VL 做理解。
- **Valen 暂不融合**，等场地、裁判、队别、短时 ID 稳定后再考虑。
- **⚠️ 不要试图用 Mage-VL 替换 YOLO 的检测跟踪**——会丢掉已很强的球和持球者信号。

## 8. YOLO 结构化结果 → Mage-VL 提示模板（草案，待老程确认）

> 对应「中等融合」：把检测层 JSON 压成自然语言提示，喂给 Mage-VL 减少幻觉。

### 输入（来自检测层落盘 JSON）
- `ball_tracks.json`：每帧 `ball`(bbox) + `players[]`(box/team/id) + `ball_handler`
- RelateAnything 关系图（每帧 pair 关系）
- `detect_primitives` 事件候选（SCREEN.*/PASS/CUT/HANDOFF…）

### 提示模板（占位符由 JSON 填充）
```
[上下文] 这是一段 {duration}s 的 NBA 进攻回合半场画面（已过滤观众与裁判）。
[已知检测结果 · YOLO]
- 场上：进攻方 {n_off} 人 / 防守方 {n_def} 人
- 持球者：#{bh_id}（{bh_team}，约第 {bh_t}s 起持球）
- 关键空间关系（RelateAnything）：{rel_list}
- 规则事件候选：{event_list}
[任务] 描述这段进攻配合的战术：掩护类型（低位/高位/侧翼）、无球跑动路线、持球人动向、球权转移、终结方式。指出与「已知检测结果」一致或冲突之处。
[约束] 只做描述，不输出最终战术标签；画面信息不足时明确说明。
```

### 设计要点
- 结构化提示**只作先验**，不当裁判（最终真值仍来自 ASR 留出集）——呼应「标签只信 ASR」。
- `rel_list` / `event_list` 来自检测层，须先过 C→B→A 主线（净化 + 标定）产出干净段。
- 模板与「三级验证门简化版」衔接：Mage-VL 描述 ↔ 规则事件候选 先做信息量对照（clip vs 单帧），再用 ASR 留出集闭环。
- 防假完整：Mage-VL 描述质量结论须由 ASR 留出集 + 双基线支撑，不让模型自证。

---

## 9. 探针实现状态（2026-10-03，已落地可跑）

**新件**：`engine/mage_vl_tactic_probe.py`（理解层探针骨架，无权重可跑 harness）。

### 已实现（全部复用既有 engine，不重造、不下载权重）
- `load_structured(seg_dir)`：读 `ball_tracks.json` + `tracks_cf.json`，抽上下文；原语事件**复用** `tactic_match_real.load_clip` + `derive_thresholds` + `tactic_match.detect_primitives`（阈值由本片段实测分布导出）。
- `build_prompt(ctx, rel, event_types)`：§8 模板，占位符由真实 JSON 填充；含 P0 未标定诚实注记。
- `load_asr_gold` / `load_vocab`：读 `asr_segment_annotation.json` 的 `episode_tactics`+`cues`（标签只信 ASR）。
- `evaluate(gold, cand, vocab, corpus_majority_*)`：**双基线 + 信息增益**（随机基线 = |cand|/|vocab|；多数类基线 = corpus 级含多数类的段占比）。
- `clip_vs_frame_info_gain(events)`：三级验证门简化版 step2（clip 级 vs **峰值密度帧**单帧事件集合信息量对照，peak frame = 同时活跃事件最多的帧）。
- `build_alignment_table(asr, rule, mage)`：**对齐表**（Mage 描述 | ASR 真值 | 规则事件 三路并列）；无权重时 Mage 列标 pending。
- `run_batch(seg_root)`：批量跑干净段、收集对齐表 + 评估、落盘 JSON。
- **图版段剔除**：`POLLUTION_SEGS` 注册表（ep10_s1/ep11_s1/ep13_s0/ep14_s0/ep14_s1/ep15_s1/ep19_s1/ep20_s1），`run_segment`/`run_batch` 默认跳过（老程裁定：图版/战术讲解纸板非真实比赛动态，混进污染评估；单留作「示意图理解」测试集，不进主语料/正式探针）。
- `mage_vl_infer`：**STUB**，本地无权重返回 None 不伪造；待老程裁定下载规格后接 transformers/SGLang。

### 冒烟结果（ep10_s0，真实数据，无权重）
- 时长 28.0s/280帧/球覆盖 0.468；真实原语事件 9 个（CUT/HANDOFF/SCREEN/SCREEN.CROSS）。
- 提示生成正常（§8 模板，含 P0 注记、持球者 #288/队别1）。
- ASR 真值 = `pistol_5`。
- **真实发现**：candidate=规则原语类型 时 acc=0.0 / random=0.056 / majority=0.09 / gain=-0.09 → at_or_below_baseline。即**规则原语词汇 ≠ 战术名称**，恰好证明需要 Mage-VL 语义层；已带双基线诚实报出，非假 KPI。

### 批量验证（14 干净段，图版段已剔除，无权重，2026-10-03 16:44）
- 跑 `action_work/tactic_notes_batch_fix1/segments` 下 22 段，8 个图版段按 `POLLUTION_SEGS` 跳过，14 段入主语料。
- **信息量对照真实结论**：clip 级事件类型 > 峰值帧单帧类型 的段 = **11/14**（gain>0）。即「看整段」确实比「看单帧」信息量大 —— 直接验证老程「clip 是否真有增益」的疑问（proxy=规则事件；接 Mage 后把战术集替换进同一结构重算）。
- 对齐表（每段落盘 `action_work/mage_probe_batch.json`）：Mage描述=pending / ASR=episode_tactics / 规则事件=detect_primitives 类型；规则∩ASR 多为空（再次印证需要先验语义层）。

### 老程三项裁定（2026-10-03 16:44）
1. **Mage-VL 权重 = Q4（~3–4GB）**：速度更快、显存友好，定性探针足够；BF16 对比以后若质量不够再补。**当前不下载**，只写框架。
2. **probe 框架同意现在写**：已落地（本文件），只写框架 + gold-reference 对齐逻辑，零重型依赖、逻辑可复用。
3. **图版段剔除主战术语料**：不进 Mage 理解层主素材，单留作「示意图理解」测试集（POLLUTION_SEGS 注册表，batch 默认跳过）。

### 待办（不阻塞）
- 接 Mage-VL 权重（**Q4 已定，延迟下载**）→ 实现 `mage_vl_infer`，用 ASR 留出集跑真实描述评估，对齐表 Mage 列填实。
- 接 RelateAnything（skill `relateanything-action-analysis`）→ 填 `load_relate_anything` 占位符。
- 接 C→B→A 主线：净化段 + 单应标定后，提示去除 P0 注记、RelateAnything 填实。
