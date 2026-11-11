# 剩余红线推进状态 + ID 已知限制裁定（2026-10-03）

> 背景：老程 2026-10-03 指示——优先推进剩下红线：半场场地标定+虚拟边线 / 裁判过滤 / 队别归属（颜色·简单分类）/ 把 ID 问题记为已知限制，战术分析改在「短时稳定窗口」内做（40~50 秒片段），等场地+裁判干净后再评估「身体比例+号码」有限增强，仍不建议为接 Valen 强行上复杂 Re-ID。
>
> 本文档逐条给出**现状证据**（file:line）、**是否闭环**、**已知 caveat**。结论：①②③ 已在代码中实现并落盘验证；④ 本次以文档化裁定收口。

---

## ① 半场场地标定 + 虚拟边线 —— ✅ 已闭环（in progress → 现收口）

| 项 | 证据 |
|---|---|
| 唯一真值源 | `action_work/court_calib/half_court_calib.json`（`_contract`：「engine 内禁止任何坐标常量，一律从本文件现读」，更新于 2026-10-02） |
| 标定+虚拟边线引擎 | `engine/half_court_spatial_engine.py`：`HalfCourtSpatialEngine` 梯形透视标定 + `estimate_virtual_expansion` |
| 冲突修订（已落地） | C1 不硬编码 src；C4 **单用未扩展点算 H**，扩展多边形只做准入；C5 浅拷贝 bug 修；C6 EXPAND_LADDER 外置；C7 dst 默认梯形→`rect_dst=True` 可切矩形 |
| 门禁 | `run_half_court_pipeline.py:37-39` G1：标定欠定即 `raise`，绝不回退示意值 |
| 虚拟边线 | `estimate_virtual_expansion` 只扩展近端两角、仅做准入多边形（C4），H 不受影响 |

**已知 caveat（C7）**：默认 dst 是梯形非矩形 ⇒ 目标空间非正交，同一战术板 y 在不同 x 处尺度不同，距离/速度计算会失真。若需正交板，调用方传 `rect_dst=True`（已备，selfcheck 报 `dst_is_rectangle`）。当前战术分析以「事件是否在场/相对位置」为主，未受正交性影响，故未强制开启。

---

## ② 裁判过滤 —— ✅ 已闭环

| 项 | 证据 |
|---|---|
| 模块 | `engine/referee_filter.py`：`filter_referees(...) → 只打 role="referee" tag，不删除`（G3） |
| 修正 | F1 位置启发式**默认关闭**（会误删底角三分射手）；F2 取躯干 ROI HSV 而非整框；F3 双信号 `require_both_signals=True`（宁可漏标不可误删） |
| 集成 | `run_half_court_pipeline.py:53-55` step 3，G3 tag-only、位置启发式默认 OFF |

**已知 caveat（R4，见模块 docstring）**：裁判站在球场地平面上时，透视判据原理上**无法**与球员区分，只能靠球衣条纹/姿态另做；任何"裁判已剔除"声明都必须附目视复核。`filter_referees` 返回的 `report`（`tagged_referee` / `both_signals` / `color_signal_only` / `position_signal_only`）供下游自行决定剔除，本模块只标注不处置。

---

## ③ 队别归属（颜色 / 简单分类） —— ✅ 已闭环（生产路径）

| 项 | 证据 |
|---|---|
| 模块 | `engine/assign_team.py`：`compute_team_of(seg_dir)` 逐帧躯干中位 RGB + 2-means(k=2,固定seed) + 参考帧色心对齐 → 跨帧一致 0/1；候选池净化（脚点门 + 运动门） |
| 生产集成 | `engine/tactic_notes_batch.py:166-172`：`compute_team_of(seg_dir)` → `tt.convert(..., team_of=...)` 写入 `ball_tracks.json` 每帧每球员 `team` 字段 |
| 落盘实证 | 全 workspace **472** 个 `ball_tracks.json` 带非空 `team` 字段（0/1，部分 -1=未知），如 `action_work/emb_g3_sas_hou/ball_tracks.json`、`action_work/emb_dft_sas_lal/ball_tracks.json` 等 |

**注意（非缺口，结构性）**：`run_half_court_pipeline` 的 `active_players_on_court` 输出**未**挂 `team`——该工具是单帧空间清洗，无 `seg_dir`/帧 `idx` 上下文，挂 team 需改造签名。但下游战术分析输入 `ball_tracks.json` **已带 team**，故「队别归属」红线目标在战术链路中已达成。若老程要求独立空间流水线也带 team，可后续加性接入（见末尾待办）。

**已知 caveat（颜色法固有）**：当两队均为浅色/灰白时，2-means 可能只按亮度劈分（实例如 `ep24_s1` 两色心均解析为 `white`）。这属于「颜色/简单分类」的预期误差范围；更强判别需号码/纹理——即老程说的「身体比例 + 号码」增强，已**显式递延**（见④）。

---

## ④ ID 问题 = 已知限制 + 短时稳定窗口战术分析 —— 🔴 本次裁定收口

### 4.1 门①-B 已知架构边界（已裁定，选项1，2026-10-03）
- 纯净子集 128 段真·身份错误 **31.2%**；根因 DINOv2 躯干嵌入被**球衣颜色主导**，同队球员/同人碎片余弦 0.83–0.93 与不同人不可分。
- **非** stabilize 参数或 DINOv2 外观重连可解；路线A 实测无有效工作点（A_clean 零改善 / 放宽合并即假完整 Δ10 崩 0.169→0.094）。
- 红线② Valen 维持锁；`norm_g3` 维持 `gate=0.30` 不动；re-id/DINOv2 外观重连方向关闭（详见 `reid_routeA_findings_20261003.md`、MEMORY_A6 铁律）。

### 4.2 新操作纪律（老程 2026-10-03 指示，本次文档化）
1. **战术分析在「短时稳定窗口」内做，不追求全局完美 ID。**
2. **目标片段 40~50 秒**，足以覆盖一次战术配合。
3. **短时遮挡内 ID 可用；长遮挡后身份不保证**——产出须显式标注 ID 稳定性窗口。
4. 等**场地 + 裁判干净后**，再评估「身体比例 + 号码」做**有限**身份增强；**仍不建议为接 Valen 强行上复杂 Re-ID**。

### 4.3 验收口径随之调整
- 已由 `milestone_05_solution.md` 把验收门从「逐帧框精度≥90%」改为 **path C「任务级事件可用性」**。
- 即：以「短窗内事件是否稳定可辨」为验收，而非「全局 ID 一致」。这与④.2 的短窗哲学一致。

---

## 待办 / 可选增强（非本次红线阻塞）
- [ ] 若需 `run_half_court_pipeline.active_players_on_court` 也带 `team`：加性接入——给 `run_half_court_pipeline` 增 `seg_dir` 形参，`compute_team_of(seg_dir)` 算一次 `team_of`，按 `(idx, track_id)` 挂到每个 cleaned 玩家。当前不阻塞（下游 ball_tracks 已带）。
- [ ] `tactic_notes_batch.py` 默认 `--seg-cap 22.0` 低于 40~50s 目标，建议对齐到 ~45s（见下「已执行」）。
- [ ] 「身体比例 + 号码」有限增强：待场地+裁判干净后单独立项评估，不在本红线范围。

---

## 已执行动作（本次）
- `engine/tactic_notes_batch.py` `--seg-cap` 默认 **22.0 → 45.0**，对齐老程 40~50s 短窗目标（单段最长切到 ~45s，足以覆盖一次战术配合）。
- 本报告 + MEMORY.md A4 节 + 2026-10-03 日志 已落盘记录四条红线状态与 ID 已知限制裁定。
