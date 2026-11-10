# NBA 本地视频语音识别 → 中文字幕 / 文稿工具

纯本地、离线运行的流水线：把篮球视频里的英文（含夹杂法语）解说识别出来，
用本地大模型 + 篮球专业术语表翻译成中文，输出 **SRT 字幕** 与 **Markdown 中文文稿**。
全部在本机完成，语音与文本不出本机。

## 能力
- 🎙️ **本地语音识别**：默认基于 **faster-whisper**（Apple Silicon 高效、有预编译 wheel），
  可选 **whisper.cpp**（Metal 极致速度，需本机编译）。自动语言检测，
  能处理英语视频里**夹杂的法语片段**（逐段判断英/法）。
- 🌐 **中文字幕 + 文稿**：SRT 字幕（按字数/时长自动断行）+ 带时间戳的 Markdown 文稿。
- 🀄 **中文源视频免翻译**：若识别出的内容为中文（如中文篮球教学视频），自动跳过翻译步骤
  直接出中文字幕/文稿，并把繁体统一转为简体（繁→简）、ASCII 标点规范为中文标点。
  判定基于「识别出的实际文本内容」而非 Whisper 的语言标签，可正确处理
  「中文视频被误判为英文」或「视频内夹英文」的情况。
- 🏀 **专业篮球翻译**：英文/法文源视频用本地大模型（默认 Qwen2.5）翻译，注入 ~190 条
  英/法→中篮球术语表（位置、战术、数据、犯规、俚语等），译文更专业统一。
- ⏱️ **长视频支持**：按 10 分钟一块切分（块间重叠避免断句），支持 5 小时级视频，
  块级与翻译级均**断点续跑**（中断后重跑自动跳过已完成部分）。
- 🔒 **离线 / 隐私**：识别与翻译均在本地模型完成，无需联网 API。

## 环境要求（Apple Silicon Mac）
- macOS on Apple Silicon（M1/M2/M3/M4）
- Python ≥ 3.10（已用 3.13 验证）
- [ffmpeg](https://ffmpeg.org/)（抽音频/分块）：`brew install ffmpeg`
- [Ollama](https://ollama.com/)（跑本地翻译大模型）：`brew install ollama`
- 识别模型（faster-whisper）首次运行自动下载；翻译模型用 Ollama 拉取。
  （若要用 whisper.cpp 极致速度后端，须先 `pip install whisper-cpp-python`，需要本机
  有 C++ 编译环境；Python 3.13 暂无预编译 wheel，会现场编译。）

## 安装
```bash
cd nba_subtitle_tool
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 拉取翻译模型（推荐 14b 质量更好；7b 更快）
ollama pull qwen2.5:14b
# 识别模型在首次运行时由 faster-whisper 自动下载（medium 约 1.5GB）
```

## 使用
```bash
# 基础用法（读取 config.yaml）
python run.py --video /path/to/game.mp4

# 指定模型（如快速验证用 small 识别 + 7b 翻译）
python run.py --video game.mp4 --whisper small --translator qwen2.5:7b

# 强制识别语言（已知是中文视频时强制 zh：识别更准；但仍按内容决定是否翻译）
python run.py --video game.mp4 --language zh

# 指定输出目录（不指定则写到 config 的 output_dir）
python run.py --video game.mp4 --output /path/to/out

# 输出：<视频名>.srt / .md / .json
```

### 批量给整个目录配字幕
`batch_subtitle.py` 会遍历目录内所有视频，逐个跑流水线，已存在 `.srt` 的跳过（断点续跑），
输出与视频**同目录同名**（播放器如 VLC/Infuse 可自动加载字幕）。
默认目录为 `/Volumes/12T/NBA/篮球训练`，可自行改 `BASE` 常量：
```bash
python batch_subtitle.py
```

## 网页界面（推荐，免上传）
不想用命令行时，内置一个本地 Flask 网页 UI：直接在浏览器里选视频、设参数、看实时进度、预览/下载字幕与文稿。
**走本地磁盘读取，不上传大文件**，适合你这种动辄几 GB 的比赛录像。

```bash
# 1) 确保依赖已装（含 flask），且在 venv 内
pip install flask            # 已装可跳过
# 2) 启动（默认 127.0.0.1:7860）
python web.py
# 3) 浏览器打开 http://localhost:7860
```

界面功能：
- **提交视频（三种方式）**：
  1. **拖拽**：把视频文件拖到页面的虚线框（自动上传到本机临时目录再处理）；
  2. **选择文件**：点「选择文件」用系统文件选择器（自动上传）；
  3. **填路径**：直接粘贴本机绝对路径（免上传，适合 12T 上已存在的 5 小时大视频）。
- **参数**：识别模型（本地模型目录 + tiny/small/medium/large-v3 尺寸）、翻译模型（读取 Ollama 已装列表）、识别后端。
- **运行**：点「开始识别」后实时滚动日志；完成后直接预览 SRT + Markdown，并提供下载链接。
  输出与源视频同目录（VLC/Infuse 可自动加载），上传的文件输出在 `work/uploads/`。
- 后端就是调用上面的 `run.py`，参数与 CLI 完全一致。

> 端口可用环境变量改：`PORT=9000 python web.py`。仅监听本机回环地址，安全。

## 配置（config.yaml）
| 项 | 说明 | 默认 |
|---|---|---|
| `models.backend` | 识别后端：`fasterwhisper`(默认) / `whispercpp`(需编译) | `fasterwhisper` |
| `models.whisper` | 识别模型：`tiny`(快)→`large-v3`(最佳) | `medium` |
| `models.translator` | Ollama 翻译模型 | `qwen2.5:14b` |
| `audio.chunk_seconds` | 长视频分块大小 | `600` |
| `audio.chunk_overlap_seconds` | 块间重叠秒数 | `20` |
| `translation.workers` | 并发翻译线程数 | `4` |
| `translation.temperature` | 翻译温度（越低越稳） | `0.1` |
| `subtitle.max_chars_per_line` | 每行中文字数上限 | `22` |
| `pipeline.auto_language` | 逐段自动语言检测（处理法英夹杂） | `true` |
| `pipeline.resume` | 断点续跑 | `true` |

## 工作原理
```
视频 ──ffmpeg──▶ 单声道16k wav ──分块──▶ 每块 .wav
   │                                              │
   │                                    faster-whisper (自动语言)
   │                                    识别英/法原文 + 词级时间戳
   │                                              │
   └──────────────────────────▶ 合并分段(绝对时间)
            │
            ▼ 原文分段 ──并发──▶ 本地大模型(Qwen2.5)+术语表 ──▶ 中文
            │
            ▼
   SRT 字幕 (原始时间戳)  +  Markdown 文稿 (带时间戳)
```

### 英法夹杂怎么处理？
开启 `auto_language` 后，Whisper 对每块/每段独立判断语言，法语片段会被识别为法语文本；
随后翻译大模型把英文和法文统一译为中文。无需手动切分语言。

### 中文源视频怎么处理（免翻译、直接出中文）？
流水线按「识别出的**实际文本内容**」判断是否中文（CJK 字符占比超阈值即视为中文），
而不是依赖 Whisper 易错的语言标签。因此：
- 中文视频 → 直接把识别文本作为中文字幕/文稿（跳过翻译大模型，更快），并做繁→简统一、
  ASCII 标点→中文标点规范。
- 视频内夹英文、或被误判为英文的中文片段 → 仍走英文→中文翻译，保证正确。
这条规则对中文篮球教学视频尤其有用：识别即字幕，无需翻译模型参与。

### 长视频（≤5h）怎么处理？
音频按 `chunk_seconds` 切成 10 分钟块（块尾重叠 20 秒保留上下文），逐块识别后再按块偏移
还原绝对时间轴。每段识别与每段翻译都落盘为 json 缓存，中断后重跑自动续接。

## 目录结构
```
nba_subtitle_tool/
├── config.yaml            # 配置
├── glossary.json          # 篮球术语表（英/法→中，~190 条）
├── requirements.txt
├── run.py                 # CLI 入口
├── batch_subtitle.py      # 批量给目录下所有视频配字幕（同目录同名输出）
├── web.py                 # 网页 UI（Flask，本地浏览器使用）
├── webui/index.html       # 前端单页
├── src/
│   ├── audio_utils.py     # 抽音频 + 分块
│   ├── transcriber.py     # faster-whisper / whisper.cpp 双后端封装（自动语言）
│   ├── translator.py      # Ollama 本地大模型翻译 + 术语表
│   ├── subtitle.py        # SRT 生成（自动断行/拆分）
│   ├── transcript.py      # Markdown 文稿生成
│   └── pipeline.py        # 编排 + 断点续跑
├── models/                # 放手动下载的 faster-whisper 模型（见 models/README.md）
├── tests/test_logic.py    # 纯逻辑单测（时间戳/SRT/文稿/术语/归一化）
├── tests/test_web.py      # 网页 run→status→download 流程测试
├── work/                  # 中间产物（音频块、识别/翻译缓存、任务日志）
└── output/                # 最终：.srt / .md / .json
```

## 运行测试
```bash
python tests/test_logic.py   # 不依赖模型：时间戳/SRT/文稿/术语/时间归一化
python tests/test_web.py     # 网页流程（用假模型验证 run→status→download 生命周期）
```

## 质量与速度取舍
- **追求质量**：`--whisper large-v3 --translator qwen2.5:14b`（最慢，最佳）。
- **平衡（默认）**：`medium` + `qwen2.5:14b`。
- **最快**：`small` + `qwen2.5:7b`（适合先验证流程）。
- 法语识别弱于英语，夹杂法语较多的视频建议用 `large-v3`。

## 局限与提示
- 识别质量依赖音频清晰度和模型大小；现场解说、掌声、音乐会降低准确率。
- 翻译为本地模型结果，专有名词（球员/球队）建议事后人工过一遍，或扩充 `glossary.json`。
- 5 小时视频在 Apple Silicon 上整体处理可能需数十分钟到数小时，取决于模型大小；
  断点续跑可避免重复计算。
