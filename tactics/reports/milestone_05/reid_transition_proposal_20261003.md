# 门①-B 收尾 · Re-ID 转向方案调研报告

> 主线：`/Volumes/12T/NBA/action_analysis/`
> 关联：`ball_holder_identity_report_20261002.md` §5.6 / §5.8
> 状态：**调研方案（未动手）** —— 按纪律 A1「报告 bug 不动手，修 bug 才动手」「严格按老程范围」，本文只给设计与裁定项，待老程拍板后再实现。
> 日期：2026-10-03

---

## 0. 结论先行（已核实事实）

门①-B（身份正确性）在**所有被测 stabilize 变体**（G3_base / long_persist / loose_gate / long_loose / tight_gate）下**均未过**。外观审计（`id_identity_audit.py`）证伪了 `gate=0.50` 的「假完整」——可见 replace+twin 率从 31% 降到 19.9%，但 `Δ10` 0.237→0.217↓、`adj_brk` 0.066→0.089↑、`PASS` 3/12→1/12，说明 track 续命但遮挡后**静默跟错人**。

根因不是参数（`gate` / `track_buffer` / `zombie_buffer` 扫过无效），而是**当前跟踪器架构没有真正的 re-id（重识别）能力**：

- 外观只用 **EMA 滑动平均**做帧间软代价，不是 gallery 检索；
- track 死亡（出 zombie 窗口）后其外观**被直接丢弃**，无跨时检索；
- 全代码库 grep `reid|gallery|track_bank|knn` 仅命中 4 文件，逐一确认**无一处实现 gallery / 跨时重连**；
- `botsort_stable.yaml` 第 29 行 `with_reid: False`，注释明写「本地无权重」——原始检测器那一路 reid 也是关的。

**结论：身份错误是架构结构性瓶颈，stabilize 参数修不了，必须转向 re-id / 外观重连。** 这是门①-B 真正的出路，与老程 `转向re-id` 指示一致。

---

## 1. 结构性缺陷诊断（逐条对应代码，可证伪）

### 缺陷 A — 外观是 EMA 平均，不是 gallery
`engine/stabilize_tracks_v2.py` 第 320–325 行：
```python
# EMA 外观
if tr["emb"] is None:
    tr["emb"] = embs[j].copy()
else:
    tr["emb"] = (1 - 0.3) * tr["emb"] + 0.3 * embs[j]
    tr["emb"] /= np.linalg.norm(tr["emb"]) + 1e-9
```
- track 的外观表示是一个**持续指数平均**，只朝「当前匹配上的检测」移动。
- 一旦在遮挡期 tracker 静默跟错了人，错人的嵌入被**永久烤进 EMA**，无法回锚到干净外观。
- 没有任何「重锚」机制（如 inlier 中位数、或高置信帧重置）。

### 缺陷 B — 死亡 track 的外观被丢弃（无持久 gallery）
第 276 行：
```python
cand = {t: v for t, v in tracks.items() if v["missed"] <= a.zombie_buffer}
```
- `tracks` 字典只保留 `missed <= zombie_buffer`（G3=600 帧）的 track。
- 一旦 `missed > zombie_buffer`，该 track 对象（含其 `emb`）从 `cand` 剔除 → **彻底丢弃**。
- 同一球员重新入框 → 拿到**全新 track_id**。没有任何机制说「这个新检测看起来像 200 帧前死掉的 #5 → 重连」。
- **这正是「长遮挡后无法恢复身份」的直接代码根因。**

### 缺陷 C — 无跨时最近邻重连
- 每帧匹配是 `active_tracks × current_dets` 的贪婪匈牙利（第 284–310 行）。
- **没有任何一步**去「搜索全部历史嵌入（含死亡 track）找该新检测的最佳匹配」。
- `zombie` 机制（第 278、310 行）只是**几何耐心窗口**（keep-alive），不是外观 re-id：
  ```python
  zombie_tids = [t for t in cand if cand[t]["missed"] > a.track_buffer]
  ...
  try_match(zombie_tids, a.zombie_app)   # app_min 提高，但仍是同帧贪婪匹配
  ```

### 缺陷 D — 原始 BoT-SORT 也关了 reid
`botsort_stable.yaml` 第 29 行 `with_reid: False`，本地无 reid 权重。两条追踪链路（raw botsort → stabilize 二次稳定）都缺真 re-id。

### 附带事实 — `segment_track_selected.py` 更弱
纯几何二次匹配（脚点 + 尺寸对数比，第 51–102 行），**完全无机外观**。同源思路、同结构局限，不能作为 re-id 解法。

---

## 2. Re-ID 三路线（A 推荐，B 升级，C 最重）

我们**已经有 DINOv2-small 384d 嵌入**（已缓存于 `~/.cache/huggingface/hub/models--facebook--dinov2-small`，离线可加载），且 `stabilize_tracks_v2.py --dump-emb` / `dump_player_embeddings.py` 都能落 `emb_dump.json`。**最便宜高价值的路线是「在既有嵌入上做 gallery 重连」，无需下载新模型**。

### 路线 A — 离线外观 gallery + k-NN 重连（推荐，零新模型）
- **做法（加性，不改跟踪器内核）**：
  1. 建全局 gallery：每段 stabilize 后，把每条 track 的逐帧嵌入存成 `track_bank.json`（`{seg: {track_id: [emb_per_frame]}}`）。
  2. 跑**后处理重连 pass**（`reid_relink.py`）：对每个「在 gap 后新开」的 track，拿其首帧嵌入去比对同段内**已死亡 track 的 gallery**；若 top-1 余弦 ≥ τ 且几何可迁（脚点位移/尺寸合理），则**合并 ID**。
  3. 输出重连后的 `ball_tracks.json` + `relink_log.json`（合并了哪些 ID、在哪一帧、cos 多少）。
- **为何推荐**：
  - 零新模型、离线、**加性模块**不碰 `stabilize_tracks_v2.py` 内核 → 风险最低，符合纪律。
  - DINOv2 在 torso 裁切上已给出 `Δ10=0.237` 的簇内/簇间分离（外观审计实测），段内 ≤10 球员的 k-NN 尺度足够。
  - 可直接用门①-B 双指标验收（见 §3）。
- **风险**：DINOv2 是通用嵌入非 person-reid 专用，长遮挡 + 视角剧烈变化可能边界模糊，需 τ 调参。

### 路线 B — 在线外观 bank（改跟踪器内核）
- 把 EMA 换成**小缓冲 bank**（如保留最近 10 个 inlier 嵌入），匹配用 bank 的 best/median 余弦而非单一 EMA；并对「近期死亡 track」每帧用高 `app_thresh` 检索。
- 这是「正统」修法，但触及核心匹配循环（第 284–346 行），必须在修 ①-B 的同时**不回退 ①-A**（保真率 / 并发 [8,16] / 中位寿命 ≥30）。风险中高。

### 路线 C — 专用 re-id 模型（BoT-SORT `with_reid=True`）
- 启用 `with_reid: True` + 下载 reid 权重（如 BoT-SORT 捆绑 osnet）。
- 冲突点：A0 环境 `TRANSFORMERS_OFFLINE=1` + 「本地无权重」→ 需联网/hf-mirror 取权重；且 BoT-SORT reid 在检测级运行，与我们的「先选 10 人再稳定」两段式管线不兼容。
- 最重、最不可控，**仅当 A、B 都失败且老程批准下模型下载时**才考虑。

**建议顺序：先 A（加性、可证伪），不足再升 B；C 视为兜底。**

---

## 3. 验收口径（复用门①-B 双指标，不可单指标博弈）

门①-B 失败已证明：**单看 replace+twin 率会被 gate 博弈成假完整**。验收必须双指标同时满足：

| 指标 | 来源 | 当前基线 | 通过线（提议） |
|---|---|---|---|
| 外观一致性 | `id_identity_audit.audit()` | `Δ10=0.237`, `adj_brk=0.066`, `PASS 3/12` | `Δ10 ≥ 0.15` 且 `adj_brk ≤ 0.05` 且 `PASS` 提升 |
| 身份错误率 | `ball_switch_clean.classify_on()` 纯净子集 | `replace+twin = 31.2%` | `replace+twin ≤ 20%`（相对 31.2% 为实质性下降） |

**硬约束（不得回退）**：
- 门①-A 不退化：保真率 ∈ [0.80,1.25] 且 中位寿命 ≥30 帧 ⇒ 仍 174/177；并发恒在 [8,16]。
- re-id 重连**不得**靠「放宽 gate 续命」实现（那是已被证伪的假完整路径）。

---

## 4. 实现草图（方案级，待裁定后落地）

### 路线 A 落地产物
- **新建 `engine/reid_relink.py`**
  - 输入：`ball_tracks.json` + `emb_dump.json`（或复用 `dump_player_embeddings.py` 生成）。
  - 逻辑：建 per-segment gallery → 对每个 gap 后新开 track 做同段死亡 track 的 k-NN（top-1 余弦 ≥ τ）→ 合并 ID → 写回 `ball_tracks.json` + `relink_log.json`。
  - 不改 `stabilize_tracks_v2.py`。
- **新建 `engine/eval_reid.py`**
  - 对重连后输出跑 `id_identity_audit.audit()` + `ball_switch_clean.classify_on()`，与 `norm_g3` 基线并排对比，出 Δ10 / replace+twin / 并发 三表。
- **复用**：`id_identity_audit.audit()`、`ball_switch_clean.classify_on()`、既有 `norm_g3` 产物做基线。

### 路线 B 落地产物（若 A 不足）
- 改 `stabilize_tracks_v2.py` 匹配循环：EMA→bank、加死亡 gallery 检索。需独立回归 ①-A + ①-B。

---

## 5. 待老程裁定项（最终裁定权归老程）

1. **路线选择**：A（离线 gallery，零新模型，推荐）/ B（改内核）/ 先 A 后 B。
2. **re-id 检索范围**：段内（≤10 球员，干净，推荐）/ 跨段（更难）。
3. **合并阈值 τ**：起步 0.6，用外观审计扫描调参；或老程给定。
4. **门①-B 通过线 X%**：提议 `replace+twin ≤ 20%`（相对 31.2% 实质下降），是否采纳 / 收紧。
5. **是否授权动手**：本文为方案，**未经老程明确批准，不修改 `stabilize_tracks_v2.py` 内核、不下载新模型**。

---

## 附：已核实代码锚点
- `stabilize_tracks_v2.py:320-325` EMA 更新（缺陷 A）
- `stabilize_tracks_v2.py:276` 死亡 track 丢弃（缺陷 B）
- `stabilize_tracks_v2.py:284-310` 同帧贪婪匹配 + zombie 几何耐心（缺陷 C）
- `botsort_stable.yaml:29` `with_reid: False`（缺陷 D）
- `segment_track_selected.py:51-102` 纯几何、无机外观
- grep `reid|re_id|gallery|track_bank|knn` 全库仅 4 命中，均无 gallery 实现
