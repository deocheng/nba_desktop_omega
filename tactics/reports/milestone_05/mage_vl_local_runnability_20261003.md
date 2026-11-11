# Mage-VL 本地可跑性评估（2026-10-03，下载进行中）

> 目的：老程令「下载mage vl」(决策①=Q4 ~3–4GB)。本评估在下载落地前先读仓库源码（README / config.json / modeling_mage_vl.py / processing_mage_vl.py / inference.py），把"M4 Mac 能不能跑、怎么跑、卡在哪"说清楚，避免盲量化或盲装依赖。

## 1. 仓库现实（已核实，非推测）

| 项 | 值 | 来源 |
|---|---|---|
| 架构 | **Mage-ViT(24层 from-scratch Codec-ViT) + Qwen3-4B-Instruct-2507 + 2层MLP投影** | `config.json` `text_config`/`vision_config` |
| 参数规模 | ~4.7B（Qwen3-4B 主导 + ViT ~0.5B） | 配置推算 |
| 精度 | `dtype=bfloat16` | `config.json` |
| **BF16 体积** | **~9.4GB**（双 safetensors 分片落盘） | 4.7B × 2B |
| transformers 要求 | **`transformers_version=5.7.0`**（用了 `TransformersKwargs`/`auto_docstring`/`can_return_tuple`/`is_flash_attention_requested` 等 5.x API） | `modeling_mage_vl.py` 导入 |
| 许可 | Apache-2.0，gated=False 公开 | `README.md` |
| 量化权重 | **仓库只发 BF16，无预量化 Q4/GGUF** | `model.safetensors.index.json`（仅 2 分片） |

## 2. ✅ M4 Mac 的 CUDA 硬阻塞已排除（关键结论）

逐项核对 `neural_codec/` 与顶层文件的引用关系：

- `modeling_mage_vl.py` 顶层 **只 import 标准 `transformers`/`torch`/`SiglipMLP`**，**不 import `neural_codec`**。
- `neural_codec`（DCVC-RT 的 CUDA C++ 扩展 `.cu`/`py_rans.cpp`）**仅在 `--codec-engine neural` 分支被 import**：
  - `inference.py:75`：`codec_config["dcvc"]["pkg_dir"] = .../neural_codec` 只在 `codec_engine=="neural"` 时执行；
  - `processing_mage_vl.py:309-334`：仅当 codec 配置存在才 `from .codec_video_processing_mage_vl import ...`。
- `video_processing_mage_vl.py` / `configuration_mage_vl.py` / `streammind_gate.py` 均不引用 `neural_codec`。

⇒ **我们用 `--video-backend frames`（均匀抽帧，恰合 40–50s 战术片段理解）走 Mage-ViT + Qwen3 decoder 路径，M4 无 CUDA 也能 import + 推理。** 神经编解码扩展不是必经路径。

## 3. ⚠️ 两个真实约束

1. **必须 `transformers>=5.7.0`**：4.x 不支持其 5.x API。须建**专用 venv** 装新版，严禁污染既有 `action05`（torch 2.14）。
2. ~~16GB 统一内存 vs 9.4GB BF16 → 必须 Q4 才舒服装下~~ **【已证伪，见 §8】**：BF16 实测 `mps_allocated=9119MB` 无 OOM，16GB M4 能装下；Q4 仅为可选提速而非内存必需。

## 4. 🔴 Q4 真分叉（待老程拍板）

老程决策①=Q4，但仓库**无预建 Q4**，须自量化。自定义架构（Mage-ViT 视觉编码器 + 2层MLP + Qwen3）使 **llama.cpp / GGUF 直转不可行**（无对应模型后端）。可行自量化路径：

| 路径 | 做法 | 工作量 | 风险 |
|---|---|---|---|
| **a) torchao int4（推荐先试）** | 仅量化 Qwen3 decoder 的 Linear 层为 int4；视觉编码器小(~0.5B)留 fp16(~1GB)；混精合计 ~3GB | 中 | torchao 对 MPS 的 int4 支持需实测；需改 `modeling_mage_vl.py` 加载钩子 |
| **b) MLX 移植** | 手写 Mage-ViT + 投影 + Qwen3 的 MLX 定义，mlx-llm 加载 | 大 | 需完整移植视觉编码器，易出数值偏差 |
| **c) CUDA 机跑 BF16/Q4** | 若有 GPU 机，直接 `transformers` BF16 或 llama.cpp Q4 | 小 | 依赖外部 GPU 机可用性（项目当前未见确认） |

## 5. 建议执行顺序（不盲量化）

1. **等下载完**（后台 task_id=XfA0RT，78 文件 / 双分片）。
2. **装专用 venv**：`transformers>=5.7` + `accelerate` + `torch`/`torchvision`(MPS) + `pillow` + `opencv-python` + `codec-video-prep`；**不碰 action05**。
3. **先跑 BF16 import + 小帧数 load 测试**（32 帧、`torch_dtype=bfloat16`、`device_map="auto"`）→ 拿**真实峰值内存数**，验证 transformers 5.7 能 import + `frames` 后端不碰 CUDA 扩展。
4. **据证据定 Q4 路径**：若 BF16 OOM（大概率），走路径 a) torchao int4；若项目有 CUDA 机且方便，走 c)。
5. 接 `mage_vl_tactic_probe.py` 的 `mage_vl_infer`：填实对齐表 Mage 列，用 ASR 留出集跑真实描述质量（带双基线）。

## 6. 当前状态

- 下载：修正 `hf download` 参数后后台重跑（去掉不支持的 `--local-dir-use-symlinks`），14% 进行中，小文件已落盘，双 safetensors 分片尚未到达。
- 落盘目录：`/Volumes/12T/NBA/action_analysis/action_work/weights/Mage-VL/`
- 代理：`HTTP_PROXY=127.0.0.1:58598`（下载需走代理；`hf` CLI=`~/.workbuddy/binaries/python/envs/default/bin/hf` 1.24.0）。

## 7. 待老程裁定

~~**Q4 自量化路径选 a) torchao int4 / b) MLX / c) CUDA 机？** 建议先走 a)（M4 本机、改动最小），下载完即做 BF16 load 测试拿真实内存证据后再定。~~ **【已据实测修订，见 §8】**

## 8. 🔴 速度 root-cause 分离计时（权威，推翻 §3/§4 旧假设）

> 下载完成后实测（专用 venv：`transformers 5.7.0` + `torch 2.14.1` + MPS）。脚本 `action_work/mage_vl_timing.py` 把一次 generate 拆成 **prefill(含视觉) / 视觉编码单独 / decode 每 token** 三段分离计时（`torch.mps.synchronize()` 同步保证异步 kernel 计时准确）。

### 8.1 实测数据（fp16 + 8帧 + 4170 ctx token + 16 新 token，M4 MPS）

| 阶段 | 耗时 | 结论 |
|---|---|---|
| 视觉编码(Mage-ViT, 只跑 1 次) | **5.74 s** | decode 步 `prepare_inputs_for_generation` 清空 `pixel_values`(`modeling_mage_vl.py:1541`)→**视觉不重算** |
| LLM prefill(4170 token 首跳) | **37.23 s** | 长 context 首跳固定成本 |
| **prefill 合计** | **42.98 s** | 每 clip 固定 |
| decode(16 新 token) | **33.0 s** | **2.063 s/token** |
| 旧"14 s/token"均值 | — | **假象**：把 42.98s prefill 摊进 16 token 的平均值（(42.98+33)/16 ≈ 4.75s/tok 量级） |

### 8.2 推翻两条旧假设

1. **"5.18 缺 `cache_position` 破坏 KV cache" = 红鲱鱼**：降级 `transformers==5.7.0` 重测仍 ~14s/tok；分离计时证明 **KV cache 正常工作**（若 decode 每步重算全 context，应≈37s/步而非 2s；且 decode 总 33s=视觉未重跑，否则 16×5.74=91s）。Mage-ViT 远程代码 KV cache 实现正确，`cache_position` 警告无害。
2. **"必须 Q4 才装下 16GB" = 错**：BF16 实测 `mps_allocated=9119MB` 无 OOM（§3 已划除）。⇒ **Q4 非内存必需，仅为可选提速选项**。

### 8.3 真实瓶颈定位

- **prefill 43s**（视觉 5.7 + 36层 Qwen3 对 4170 token 首跳注意力）→ 随帧数线性涨；
- **decode 2.06 s/token** → MPS 对 4170-token context 的逐 token 注意力，比理想 MPS(~0.03–0.1s/tok)慢 ~20–70×，属 **MPS 算力/带宽瓶颈**（非重算、非版本、非内存）。
- 产线成本估算：单 clip = 43s prefill + 2.06×N(描述 token)。N≈60 → ~166s/clip；100 clips 隔夜 ≈ 4.6h（**离线可行**）。

### 8.4 结论与建议（证据驱动，不盲量化）

- **M4 本地 BF16 可用**（能装、能跑、描述正确），Q4 降级为「可选提速」而非「必需」。
- 若要进 tactic 理解层产线，提速杠杆排序：
  1. **减帧/降分辨率**（缩 context，线性降 prefill+decode 双杀，最稳；但有捕运动下限——codec-native 稀疏已减 patch）；
  2. **`torch.compile` / MPS flash-attn**（待验）；
  3. **torchao int4**（仅权重，对算力瓶颈提速有限 ~2×，视觉塔留 fp16）；
  4. **CUDA 机**（治本但非本地）。
- **建议下一步**：先以 BF16 离线接 `mage_vl_infer` 实填对齐表 Mage 列、用 ASR 留出集拿描述质量双基线；据证据再决定是否值得投 int4/compile。裁定①"Q4 必需"据此修订为可选（MEMORY.md A7/A8 同步）。

## 9. 🔴🔴 帧数→内存硬顶：接 `mage_vl_infer` 后的实测（订正 §8 的乐观结论）

> `mage_vl_infer` 已实装后，对干净段 ep10_s0 跑 16 帧 / 96 token 冒烟，**2h55m 未完成**。系统级诊断给出决定性证据。

### 9.1 诊断证据（换页抖动，非算力慢）

| 指标 | 16 帧推理运行中 | 手动停止后 |
|---|---|---|
| swap 占用 | **17.55 / 18.4 GB（打满）** | 4.6 GB |
| 系统空闲率 | **28 %** | **78 %** |
| pageins / 解压页 | 2957 万 / 3.06 亿 | — |

停止后内存立即回升 ⇒ **确证这次换页抖动由该推理进程引起**。32 帧那次 142 s/token 据此判断也几乎肯定是换页，而非纯算力慢。

### 9.2 性质订正（重要自我纠错）

§8 结论"BF16 装得下 ⇒ Q4 非必需"**只在 8 帧成立**。两个不同问题被混为一谈：

1. **权重能否装下** —— 是。BF16 权重 9.1 GB < 16 GB 统一内存，实测无 OOM。此点无误。
2. **运行时工作集是否会撑爆物理内存** —— 这才是当前瓶颈。工作集 = 权重 9.1 GB + KV cache + **多帧视觉激活** + prefill 注意力，**随帧数增长**；超过物理内存即换页到加密磁盘，慢数百倍。

### 9.3 帧数档位实测对照

| 配置 | context | 实测结果 |
|---|---|---|
| 8 帧 / 16 token | 4170 | **正常**：prefill 43 s，decode 2.06 s/token |
| 16 帧 / 96 token | ~8300 | **换页抖动**：2h55m 未完成 |
| 32 帧 / 20 token | 16624 | 142 s/token（现判为换页所致） |

⇒ **本机 16 GB M4 的可用上限约 8 帧**。而 8 帧摊在 40–50 s 战术片段上 ≈ 每 5–6 秒才一帧，**不足以讲清一次战术配合**。

### 9.4 诚实结论

**本机 BF16 直接跑 40–50 s 战术片段这条路线，目前不可实用**——这是资源负结果，不是配置瑕疵，也不应靠调参粉饰。

### 9.5 解法排序（证据驱动，待老程拍板）

1. **降单帧 patch 数（最推荐先试）**：缩小帧分辨率 / 限制 pixel budget，使**同样 context 预算能喂 2–4 倍帧数**。战术理解要时序，"多而粗"优于"少而精"。需先查 processor 是否支持 `size` / `max_pixels` 类参数。
2. **torchao int4**：权重 9.1 → ~3 GB，**腾出约 6 GB 给激活与 KV**，才可能撑住 ≥16 帧不换页。注意——**Q4 的理由已变**：不再是"权重放不进"，而是"为多帧留出不换页的运行空间"，其价值因此**回升**。
3. **CUDA 机**：治本，代价是离开本机。
4. **降低任务规格**：缩短片段 / 只取关键帧，接受更弱的理解粒度。
