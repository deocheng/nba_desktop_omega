# Ternary-Bonsai-2-27B-VLM 死球/活球 判定 PoC（路径 A）

> 目标：用 PrismML 的 **Ternary-Bonsai-2-27B-VLM**（5.9GB，三值量化，Mac Metal 可跑）替代人工目测，
> 判别 NBA 广播帧是 **LIVE（活球进攻）** 还是 **DEAD（吹停/暂停/罚球/转场）**。
> 它**不是** VLX-Seek，是与 Om AI Lab 无关的独立模型；它的三值压缩不可移植到 VLX-Seek。

---

## 0. 为什么选它（与 VLX-Seek 对比）

| 项 | VLX-Seek-1.5-10B | Ternary-Bonsai-2-27B-VLM（本方案） |
|---|---|---|
| 体积 | ~20GB bf16（16GB Mac 装不下，须 4-bit） | **5.9GB (PTQ1_0)** / 7.2GB (PQ2_0) |
| Mac M4/16GB | 须 torchao int4，内核完整性未验证 | **原生可跑 Metal，全格式 ✅** |
| 架构 | region-reference VLM（Om AI Lab） | 通用 VLM（PrismML，Qwen3.8-27B 三值化） |
| 运行依赖 | transformers + 4-bit 补丁 | **PrismML llama.cpp fork** + mmproj |

---

## 1. 本仓库已准备（沙箱内完成，无需老程重做）

- `bonsai/` — `git clone` 自 `PrismML-Eng/Bonsai-demo`（官方 demo，含 fork 构建/启动脚本）
- `bonsai/poc_frames/` — 三张代表帧（1920×1080，已从权威 mp4 切片抽取）：
  - `cand_1244_DEAD.jpg` — 裁判吹停转场（ground-truth: DEAD）
  - `cand_932_LIVE.jpg` — 活球进攻（ground-truth: LIVE）
  - `possA_full_LIVE.jpg` — 活球进攻（ground-truth: LIVE）
- `bonsai/bonsai_poc.py` — OpenAI 视觉客户端（**仅标准库**，无 pip 依赖），发图+prompt，解析 LIVE/DEAD，对 ground-truth 算证伪准确率
- `bonsai/run_bonsai_poc.sh` — 一键 runner（健康检查 → 发三帧 → 写 `poc_verdict.json`）

---

## 2. 老程本机执行（需 VPN，一次性环境搭建）

```bash
cd /Volumes/12T/NBA/action_analysis/bonsai

# (a) 构建 PrismML llama.cpp fork(Metal) + 下载 27B GGUF + mmproj 视觉投影器
#     demo 默认下载 PQ2_0(7.2GB)；若想最省内存改用 PTQ1_0(5.9GB)，见下方注
./setup.sh

# (b) 起 OpenAI 兼容服务 :8080（自动挂 mmproj，支持 image_url）
./scripts/start_llama_server.sh
#   浏览器开 http://localhost:8080 可肉眼确认已加载；或 curl http://localhost:8080/health

# (c) 跑 PoC（发三张代表帧，对照 DEAD/LIVE/LIVE 输出证伪准确率）
./run_bonsai_poc.sh
```

### 注：改用最小 5.9GB 权重（PTQ1_0）
`setup.sh` 默认拉 **PQ2_0（7.2GB）**。若想最省内存，可手动下载 PTQ1_0 并用 `BONSAI_GGUF` 指过去：
```bash
# 用 huggingface-cli（需 VPN）拉 PTQ1_0 + mmproj 到 models/ 下，再：
BONSAI_GGUF=models/bonsai2-gguf/27B/Ternary-Bonsai-2-27B-PTQ1_0.gguf \
BONSAI_MMPROJ=models/bonsai2-gguf/27B/*mmproj*.gguf \
  ./scripts/start_llama_server.sh
```
（PQ2_0 与 PTQ1_0 在 Mac Metal 均有内核；PQ2_0 提示处理更快，PTQ1_0 最小。二者都**必须** PrismML fork，mainline 会拒载或乱码。）

### 若下载 401（仓库曾短暂 gated）
`BONSAI_TOKEN=hf_你的只读token ./setup.sh`（只读 token 即可）。

---

## 3. 判定结果如何解读

- `run_bonsai_poc.sh` 末尾打印 `证伪准确率: n/3 (xx%)` —— **仅 3 张代表帧，非统计结论**。
- **3/3 全中** → 可靠信号，扩到 `clips/tactics_notes_pick/nbacup/` 全部候选帧批量证伪，再决定是否接进 23:10 管线做死球门控。
- **有错判** → Bonsai 2 视觉在三值化后确有掉分（OCRBench v2 60.99→56.88 / MMMU-Pro 81.73→75.49），粗分类也可能不可靠；回报具体错哪张，我们再定是否换 prompt / 关 `--image-max-tokens`（`BONSAI_IMAGE_MAX_TOKENS=0` 保留全细节）或退回 yolov8n+目测原流程。

---

## 4. 当前状态

- ✅ 代码/脚本/代表帧/权重文件名 全部就位（磁盘真源已核实）
- ⏳ **未实测**：权重下载 + fork 构建 + 推理需在老程 Mac（VPN）执行；沙箱到 HF 文件 CDN 双通道阻断，无法在此环境跑
- 等老程回报 `poc_verdict.json` 里的准确率，再裁定是否接进剪辑管线
