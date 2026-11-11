# Ternary-Bonsai-2-27B-VLM 真实 PoC 结果（2026-10-08）

目标：用 PrismML 的 Ternary-Bonsai-2-27B-VLM 当本地视觉判定器，替代人工目测，
判别 NBA 广播帧 LIVE(活球进攻) vs DEAD(吹停/暂停/罚球/转场)，接进 23:10 死球门控。

## 已验证（真实推理，非模拟）

- **构建**：PrismML llama.cpp fork Metal 构建成功 → `bin/mac/llama-server`
  (`0.2.0-dev build 10760`, AppleClang 21, Darwin arm64, Metal 链接)。
- **权重**：`PQ2_0.gguf` 7.21GB (GGUF v3, 851 tensors) + `mmproj-Q8_0.gguf` 0.63GB
  (GGUF v3, 334 tensors)，头校验通过。
- **容量排雷**：`common.sh` 在 M4/16GB 默认 `CTX=16384` → 27B KV 缓存(~9GB)把总量顶过
  16GB **会 OOM**。已用 `BONSAI_CTX=4096` 覆盖（估算 ~12GB，安全）。
- **门控绕过**：沙箱代理占用 `localhost:8080`，使 `start_llama_server.sh` 的端口健康检查
  （`curl … >/dev/null` 只看退出码）误判"已在运行"而退出。绕过：直接起
  `bin/mac/llama-server -m … --mmproj … --port 8077`，就绪判定要求 HTTP 200 + 日志
  `listening`（沙箱特有，老程本机无此代理，8080 原流程可用）。

## 真实三帧证伪（代表帧：cand_1244_DEAD / cand_932_LIVE / possA_full_LIVE）

| 尝试 | 配置 | 结果 |
|---|---|---|
| A | thinking ON, max_tokens=1024 | **2/3**：DEAD✓ / LIVE✓ / frame3=**UNKNOWN**(空, 烧 1024 token 在推理上没答出来) |
| B | `--reasoning-budget 0`, max_tokens=2560 | **2/3**：DEAD✓ / LIVE✓ / frame3=**TIMEOUT**(180s 客户端超时, 服务端仍在生成 1219+ token) |
| C | `--reasoning-budget 0`, max_tokens=48 | **0/3**：三帧全空（推理吃掉 48 token，无答案） |
| D | frame3 单帧, thinking ON, max_tokens=2800, timeout 600s | 生成 **2746 token / 334s(5.6 分钟)** → 答 **DEAD**（**错误**, GT=LIVE） |

## 结论（可证伪，裁定权归老程）

1. **清晰度高的帧能分对**：吹停帧、活球近景帧在足够 token 预算下 2/3 正确。
2. **宽景活球帧被误判为 DEAD**：possA_full_LIVE（真实活球进攻）最终判成 DEAD —— 这是
   **假死球**，在死球门控里会把一段真实进攻配合**错误排除**，正是我们要避免的危险错误类型。
3. **thinking VLM 不可控 + 极慢**：本 PrismML build 不响应 `--reasoning-budget 0`，
   推理链必跑；~8 t/s on M4/16GB，硬帧单帧 5.6 分钟。批量 25 候选帧会到小时级 + 误判风险。
4. **默认 max_tokens 小 → 空答案**：thinking 吃掉预算，content 空 → UNKNOWN，非统计结论。

**⇒ 暂不能接进 23:10 管线当自动化死球门控。** 概念可行（清晰帧 2/3），但当前形态
（thinking、慢、宽景活球误判为 DEAD）不满足"减人工目测"的可靠性/吞吐要求。

## 候选下一步（待老程裁定）

- (a) 换更小/非-thinking VLM（如 Bonsai 小尺寸或别的三值化 VLM）提速降误判；
- (b) prompt 工程压制推理（本 build 的 `--reasoning-budget 0` 实测无效，需确认其他开关）；
- (c) 仅作"慢速人工增强"工具（手动触发，不进自动门控）；
- (d) 先回 yolov8n+目测原流程，Bonsai 留作离线二次校验。

## 推进 (a)：更小非-thinking VLM —— Qwen2.5-VL-3B-Instruct（2026-10-08 23:5x）

方向转"无人工介入全自动分析" → 选项(a)最近。换非-thinking 小模型解决 Bonsai 两大致命伤。

### 选型与落地
- 模型：Qwen2.5-VL-3B-Instruct **Q4_K_M** 1.93GB + **mmproj** f16 1.34GB（lmstudio-community, bartowski 量化）。
  Qwen2.5-VL 是**非-thinking** VLM（thinking 是 Qwen3-VL 才有）→ 无推理 token 爆炸；3B 全量上 M4 GPU。
- 下载：HF 已解除阻断，`curl -L` 直下，头校验通过（GGUF v3，434/519 tensors）。
- 复用：现有 `bin/mac/llama-server`（llama.cpp fork）直接加载，无需重建；`bonsai_poc.py` 不改（同发 image_url+text）。

### 真实三帧证伪（同三代表帧）
| 帧 | GT | Qwen2.5-VL-3B (原 prompt) | Qwen2.5-VL-3B (线索 prompt) |
|---|---|---|---|
| cand_1244_DEAD | DEAD | **LIVE** ✗ | **LIVE** ✗ |
| cand_932_LIVE | LIVE | LIVE ✓ | LIVE ✓ |
| possA_full_LIVE | LIVE | LIVE ✓ | LIVE ✓ |

**准确率 2/3**（两 prompt 一致）。**单帧时延 ~5.5s**（Bonsai 5.6min 的 ~80× 提速）；二次同图靠 prompt-cache 复用降到 ~0.3s/帧。

### 关键发现
1. **速度问题彻底解决**：非-thinking + 3B → 秒级/帧，可批量进 23:10 管线。
2. **活球帧 2/2 全对**（LIVE 判定稳）。
3. **死球帧误判为 LIVE**（cand_1244=裁判吹停转场，模型判 LIVE）→ 假阴性：会把一段停摆当活球保留进候选池。
4. **根因 = 单帧歧义**：吹停/罚球在"静止一帧"里常看起来像活球；老程的 DEAD 判定来自时序/记分牌上下文（门控6：近景有无记分牌=死球关键），单帧 VLM 看不到。

### 裁定（接进自动门控的路径）
- Qwen2.5-VL-3B **不宜作唯一死球门控**（会漏掉停摆）。
- 但它是**又快又准的 LIVE 确认器**（2/2 活球对）+ 极速交叉校验。
- 推荐自动门控设计：**DEAD 以"记分牌 ROI 静态差"(门控6) 为权威信号（已自动化，仅标记不排除）；VLM=DEAD 作二次确认；仅当两者都 LIVE 才判 LIVE**。两路互补 → 近零人工。
- 备选：① 试 Qwen2.5-VL-7B（更大，可能抓死球线索，需再下~4GB）；② 对 VLM 做 few-shot/微调专攻吹停帧；③ 给 VLM 喂多帧/记分牌 ROI 而非单帧。

## 产物（磁盘真源）

- `bonsai_poc.py`（stdlib 客户端，--max-tokens / --expect / --question 可配）
- `run_bonsai_poc.sh`（runner，健康检查要求 HTTP 200）
- `test_poc_mock.py`（mock 端到端，**ALL MOCK TESTS PASSED**，4 个 bug 已修）
- `poc_frames/`（三张代表帧，真源 mp4 切片）
- `poc_verdict.json` / `poc_frame3.json`（判定结果）
- `poc_server.log`（服务端日志，含 token/时延证据）

## 推进 (a) 的延伸：OpenAI Decisions API 客户端骨架待命（2026-10-09）

Qwen 把"死球帧误判 LIVE"（2/3 天花板）的根因是**单帧歧义**——单帧 VLM 看不到时序/记分牌上下文。
Decisions API（`gpt-6-luna`）的 typed answer + **单次请求 ≤128 张内联图**正好对症：可喂多帧时序破单帧歧义，
且直接出 confidence → 高置信自动决、低置信转人工，是通向"无人工介入"的机制。

### 已落地（本机验证，未扣费）
- `decisions_client.py`（stdlib-only）：`choice`/`predicate` 两模式；`--per-image` 单帧对表 或 多帧单请求破歧义；
  `--batch` 多 clip；路由阈值 `--confidence-threshold`(默认 0.90) / `--pred-dead` / `--pred-review-gap`；
  官方端点无 key **直接非零退出**防误扣费；`--print-raw` 首调校正用。
- `test_decisions_mock.py`：`ALL DECISIONS MOCK TESTS PASSED`（choice 3/3 / predicate 3/3 / 多帧构造 / 护栏）。
- 官方 schema 已对 `developers.openai.com/api/reference/decisions` 复核（题型字段 + 128 图上限）。
- **诚实标注**：input 内图像消息 content part 类型名（`input_image`/`input_text`）依官方"user messages w/ images"
  描述做最佳映射，留 `--image-content-type`/`--text-content-type` 可调口，**首调真 key 后用 `--print-raw` 校正**。

### 待老程授权 + 提供 OPENAI_API_KEY 后真跑（命令模板）
```bash
# 单帧对表(与 Qwen 2/3 直接对比): 三代表帧
python3 decisions_client.py --mode choice --per-image \
  --expect DEAD,LIVE,LIVE \
  --out decisions_verdict_choice.json \
  poc_frames/cand_1244_DEAD.jpg poc_frames/cand_932_LIVE.jpg poc_frames/possA_full_LIVE.jpg

# predicate 模式(死球概率 0-1)
python3 decisions_client.py --mode predicate --per-image \
  --expect DEAD,LIVE,LIVE \
  --out decisions_verdict_pred.json \
  poc_frames/cand_1244_DEAD.jpg poc_frames/cand_932_LIVE.jpg poc_frames/possA_full_LIVE.jpg

# 破单帧歧义: 把单个候选窗口的 5-8 帧一次喂入(<=128 图/请求)
python3 decisions_client.py --mode choice --print-raw \
  --out decisions_multiframe.json clip_frames/candXXXX_*.jpg

# 阈值标定: 用老程已裁定 25 窗口(--batch jsonl, 含 expect)
python3 decisions_client.py --mode choice --batch clips25.jsonl --confidence-threshold 0.90
```
卡点：`OPENAI_API_KEY` 仍 **NOT SET**；到我手即按上模板跑出真数据（准确率/confidence/时延）与 Qwen 对表。

## 当前主线状态（2026-10-09）

- 路径 A 真实 PoC：Bonsai-27B **排除**（thinking 不可控 + 5.6min/帧 + 宽景活球误判 DEAD）。
- 推进 (a)：Qwen2.5-VL-3B 已落（5.5s/帧、活球 2/2、死球误判 LIVE）→ 作 LIVE 确认器 + 配门控6 双路。
- Decisions API 客户端**骨架已就绪并通过 mock 自测**，待 key 真跑破 2/3 + 单帧歧义。
- 裁定权归老程；下一步优先级 = 拿到 key 跑三帧真调，达标再上多帧 + 25 窗口阈值标定。

## 推进 (a) 的本地等价：Qwen2.5-VL 多帧 + logprobs 置信度（2026-10-09 实测）

老程倾向本地优先。结论：**没有"本地版 Decisions API"这个产品**（typed predicate/choice/score 端点是 OpenAI 独有），
但机制可 **100% 在本地复刻**，且用盘上已有的 Qwen2.5-VL-3B（零新下载、零云端、零 key）：
- **多图输入**：Qwen2.5-VL 原生支持一张请求喂 N 帧 → 破单帧歧义（同 Decisions 的 128 图上限）。
- **logprobs 置信度**：llama.cpp server 的 `/v1/chat/completions` 支持 `logprobs`+`top_logprobs` →
  取首词 LIVE/DEAD 真实概率分布 = 本地 confidence，等价 Decisions choice 的 probabilities + confidence。
- 备选轻量本地模型：**SmolVLM2-2.2B**（Apache 2.0，GGUF `Q4_K_M` 仅 1.0GB，专为视频帧/多帧设计）或 **Qwen2.5-VL-7B**（同机制 ~4GB）。

### 产物（磁盘真源）
- `local_decisions_client.py`（stdlib-only）：多帧请求构造 + logprobs 解析 + 置信度路由（接口/路由对齐 decisions_client）。
- `test_local_decisions_mock.py`：`ALL LOCAL DECISIONS MOCK TESTS PASSED`（单帧 3/3 / 低置信路由 / 多帧构造）。

### 真实三帧实测（本地 Qwen2.5-VL-3B，端口 8099）
| 帧 | GT | 修正后 verdict | conf (P(LIVE)/P(DEAD)) |
|---|---|---|---|
| cand_1244_DEAD | DEAD | **LIVE** ✗ | 0.98 (0.98/0.02) |
| cand_932_LIVE | LIVE | LIVE ✓ | 0.99 (0.99/0.01) |
| possA_full_LIVE | LIVE | LIVE ✓ | 0.98 (0.98/0.02) |

准确率 **2/3 (67%)**，与早前 free-text Qwen PoC 一致。

### 关键发现（诚实，可证伪）
1. **logprobs 机制可用**：服务端确实回 logprobs，客户端能取出 LIVE/DEAD 真实概率。
2. **子词切分 bug 已修**：Qwen 把 LIVE 切成 `L`+`IVE`、DEAD 切成 `DE`+`AD`；初版只匹配全词 token 会丢弃
   `L`/`DE` 主导概率质量，把置信度低估成 0.74。改用**前缀匹配**（token 是 LIVE/DEAD 的前缀或反之）后修正为真实 ~0.98；mock 回归仍 3/3。
3. **单帧 Qwen 是"自信地错"**：死球帧 cand_1244 的 P(LIVE)=0.98 —— 模型**高度确信**那是活球。
   说明**置信度阈值化救不了单帧**（它不"不确定"，而是真判错）；根因仍是单帧歧义（吹停静止帧像活球）。
4. **结论**：本地要破 2/3，必须喂**多帧时序**（同 clip 的 5–8 帧一次请求），让模型看到"吹停/记分牌/动作中断"的时序信号。
   这正是 Decisions 128 图的能力，本地 Qwen 同样支持多图输入。

### 多帧真机实测（每候选 8 帧，端口 8099，ctx 16384）
从 `clips/tactics_notes_pick/nbacup/` 的窗口 clip 抽 8 帧（480×270，均匀采样），一次请求喂入（不加 `--per-image`）：

| candidate | GT | 多帧 verdict | conf (LIVE/DEAD) |
|---|---|---|---|
| cand_1244.5-1269.0（裁判吹停转场） | DEAD | **LIVE** ✗ | 0.99 (0.99/0.01) |
| cand_932.5-949.0 | LIVE | LIVE ✓ | 0.98 (0.98/0.02) |
| possA_full_444.5-458.0 | LIVE | LIVE ✓ | 0.99 (0.99/0.01) |

**仍是 2/3 (67%)** —— 多帧**没有**把死球帧翻成 DEAD，模型看完整 24.5s 窗口仍判 LIVE(0.99)。
产物：`multiframe_verdict_cand1244.json` / `cand932.json` / `possAfull.json`；帧序列 `poc_frames/multiframe/<cand>/f001..f008.jpg`。

### 结论（诚实，可证伪，裁定权归老程）
1. **本地机制完全跑通**：多图输入 + logprobs 置信度 + 路由，真机验证无误（单帧/多帧请求都成功，置信度解析正确）。
2. **Qwen2.5-VL-3B 精度不够破 2/3**：单帧或多帧都 2/3，且死球帧**高置信错判 LIVE(0.98–0.99)**。
   多帧没救是因为该窗口的吹停信号（裁判/记分牌/动作中断）在 480×270 低清 + 均匀采样下没被模型捕捉到，
   或模型本就缺此类语义——**VLM 不是可靠的 DEAD 判定器**。
3. **本地自动化的正路 = 门控6(记分牌 ROI 静态差) 当 DEAD 权威信号**（已自动化、确定性、无需模型）：
   VLM 只作 **LIVE 确认器**（活球 2/2 高置信对）；候选判 DEAD 必须经门控6 二次确认，而非信 VLM。
   这与早前 BONSAI 结论一致，多帧实测进一步证实 VLM 不能独当 DEAD 门控。
4. **若坚持要 VLM 也判 DEAD**，本地升级方向：Qwen2.5-VL-7B（同机制、更可能抓吹停线索）或更高分辨率/更密采样帧；
   但成本与收益需老程裁定。云端 Decisions(gpt-6-luna) 仍是 DEAD 判定的最强外部候选，待 key 实测。

### 下一步
- **本地落地**：以门控6 为 DEAD 权威 + 本地 Qwen 作 LIVE 确认器，接入 23:10 管线（双路互补，近零人工）。
- 真调阈值标定用 25 窗口裁定（possA_full=标杆、cand1244/cand87=EXCLUDE）。
- 云端 Decisions 真跑待老程提供 key（同三帧对表，看能否破 2/3 + 单帧歧义）。

当前本地 server：Qwen2.5-VL-3B 仍在 8099 运行（后台任务 Ze8HkM）；重启命令：
`cd bonsai && ./bin/mac/llama-server -m models/qwen25vl-3b/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf --mmproj models/qwen25vl-3b/mmproj-model-f16.gguf --port 8099 -ngl 99 --ctx-size 4096`

## 融合判定器落地 + 真机端到端验证（2026-10-09，老程批准「写吧」）

把"门控6(sb_frac)=DEAD 软权威 + 本地 Qwen=LIVE 确认器"双路接进 23:10 管线。
**先核实门控6 真实代码**（不凭记忆）：`sb` 生产者是 `shot_scale_seq.py`（非诊断工具
`find_scorebar3.py`/`roi_ascii.py`），ROI=1920×1080 原生 `x[978,1186] y[943,986]`，逐采样点
`sb = mean(absdiff(roi,prev_roi)) < 12.0`；`refine_candidates.py` 取特写段 `sb` 均值=`sb_frac`，仅标记不自动排除。

### 设计（可证伪，阈值标定自 3 锚点 + 老程定性规则）
纯逻辑 `fuse_verdict(sb_frac, qwen_live)`：
- `sb_frac < 0`（无数据）→ HUMAN_REVIEW
- `sb_frac ≥ 0.85` → **EXCLUDE**（记分牌全程冻结=吹停/replay/timeout，门控6 权威**压住 Qwen**）
- `sb_frac < 0.50` → **KEEP**（特写无记分牌=进攻镜头语言，无需 Qwen）
- `0.50 ≤ sb_frac < 0.85` → 模糊档交 Qwen：`qwen_live ≥ 0.90`→KEEP，否则 HUMAN_REVIEW

### 产物（磁盘真源）
- `fusion_judge.py`（自包含，可作管线阶段 `from fusion_judge import fuse_half`）：
  门控6 同算法现算 `sb_frac`（源视频特写段）、Qwen 多帧 LIVE 确认（前缀匹配聚合 logprobs）、
  三档裁定、JSON+可读报告输出。`--no-qwen` 门控6-only 快速分诊。
- `test_fusion_mock.py`：`ALL FUSION MOCK TESTS PASSED`（11/11：纯逻辑 6 + 编排 5）。
- `validate_fusion_real.py`：3 锚点 clip 端到端真机验证。

### 真机端到端验证（3 锚点 clip，Qwen 重启于 8099，ctx 16384）
实测中修出两个真 bug（均靠终端实测暴露，mock 测不出）：
1. **代理拦截**：urllib 走沙箱代理 → Qwen 不可达；改 `ProxyHandler({})` 绕过本地 server。
2. **响应结构解析错**：真实响应是 `logprobs.content[0].top_logprobs`（**列表** `[{token,logprob}]`），
   初版写成 `logprobs.top_logprobs`（dict）→ KeyError 被吞 → 全 None。已改取 `content[0]["top_logprobs"]` 列表迭代。
3. 健壮：本机 server 单请求图片数上限（8 帧 400）→ `call_qwen_live` 递归减半重试到 1 帧；默认 4 帧。

| candidate | 整段 sb_frac(代理) | Qwen LIVE | 融合 verdict | 老程裁定 |
|---|---|---|---|---|
| cand_1244.5-1269.0 | 1.00 | （不调，门控6压） | **EXCLUDE** | EXCLUDE(吹停转场) ✓ |
| cand_932.5-949.0 | 0.80 | 0.83 | HUMAN_REVIEW | 一次进攻(KEEP) |
| possA_full_444.5-458.0 | 0.75 | 0.95 | **KEEP** | 最完整标杆(KEEP) ✓ |

**诚实标注**：cand932 落 HUMAN_REVIEW 是因为 `sb_frac` 用的是**整段代理**（含远/中景），
非 refine 的特写段窗口。管线真实调用会传 `c["close"]` 段时间窗 → 特写段 `sb_frac` 更干净、
大概率 <0.85 且 Qwen 高置信 → 转 KEEP。此现象是代理标定，非逻辑 bug。
cand1244/possA 两端（门控6 权威 + Qwen 确认）已实证正确。

### 接进 23:10 管线（未改 run_nbacup_pipeline.py，待老程确认再接）
落点：在 `refine` 之后、`cut_and_sheet` 之前插入 `fuse_half(cands_json, clean_src)`，
用融合 verdict 替代当前仅 `is_excluded`（入场仪式硬排除）粗筛：
- KEEP → 自动剪 + 接触表；EXCLUDE/HUMAN_REVIEW → 不自动剪，列入 `fusion_report.md` 交老程。
- 无 Qwen（server 未起）→ 模糊档一律 HUMAN_REVIEW，门控6-clean 仍自动 KEEP（减人工不阻断）。

### 待办（KPI 标定）
- 全 25 窗口跑 `fuse_half`（传真实 `close` 段）+ 对老程 KEEP/EXCLUDE 标签算一致率 → 校准
  `SB_FRAC_HARD/SOFT`、`QWEN_LIVE_MIN` 三阈值。
- 云端 Decisions(gpt-6-luna) 待 key 同三帧对表，看能否破 2/3 + 单帧歧义作为 DEAD 最强外部候选。

## 🔴 全量标定修正：真实 sb 数据推翻"高 sb=EXCLUDE"核心假设（2026-10-09 全量跑前）

跑全量前读 `裁剪依据.md` 第三部分第3条，发现**真实全量 sb 占比**（上半场重扫含 sb）：
`cand1244=1.00(吹停/EXCLUDE)`、`cand932=1.00(一次进攻/KEEP)`、
`cand1119=1.00(一次进攻/KEEP)`、`full_poss428=0.75(KEEP)`、`possA=0.20(活球/KEEP)`。

**⇒ `sb_frac=1.0` 既含 EXCLUDE 也含 KEEP，门控6 对 EXCLUDE/KEEP 无区分力。**
上轮验证里 "cand1244 sb=1.0→EXCLUDE ✓（门控6权威压 Qwen）" 是**碰巧对、逻辑错**——
同规则会把 cand932/1119（sb=1.0 但老程判 KEEP）**误杀**为 EXCLUDE，违背「禁假完整」。
老程亦已裁定"记分牌在≠吹停，第6门控从硬排除改仅标记"。

### 修正（已落 fusion_judge.py + 11/11 mock 回归）
- **删除 `sb_frac≥0.85→EXCLUDE` 分支**。`fuse_verdict` 改为：
  - `sb_frac<0.50` → **KEEP**（门控6 干净：特写无记分牌=进攻镜头语言，possA 实证）
  - `sb_frac≥0.50` → **HUMAN_REVIEW**（高 sb 既可能活球特写也可能吹停，两信号无区分力，交老程）
- Qwen 仍在高 sb 档调用但**仅记录 `qwen_live` 供参考**，不再自动裁定（Qwen 把吹停错判 LIVE 不可信）。
- 诚实结论：当前两信号都不可靠区分吹停 vs 活球特写。自动流程只能做到
  **门控6 干净段自动 KEEP + 其余交老程**（recall 工具非 precision 工具，与老程定性一致）。

### 全量标定运行中
`run_fusion_calibration.py`（后台）：两半场 `shot_scale_seq`+`refine`（落 `nbacup/_fusion/`，非 /tmp）
→ `fuse_half` → 对老程 6 张接触表（时间键 clip[0]±4s）算一致率 + 误杀/漏排数。
输出 `nbacup/_fusion/calibration_report.md`。结果回填本段。
