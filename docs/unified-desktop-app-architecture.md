# 整仓大一统桌面 app — 架构设计与边界

> 日期：2026-11-12 · 分支 `chore/path-governance-2026-11-10` · 基线 `c5caf39`
> 触发：主理人明确「想开发成独立的程序，而不是现在这样需要依赖 ai 的代码包或者说给技能提供支持的代码包」，
> 并在三种范围里选定 **「整仓大一统桌面 app」**。
> 本文是**架构与边界定义**，同时给出阶段 0 的可验证落地清单。所有现状数字均为本机实跑 / `git ls-files` 取得，
> 不含推断；未来能力一律标注 `planned`，不把设想写成既成事实。

---

## 0. 结论先行

1. **缺的不是框架，是编排层。** 主仓已经有可运行的 FastAPI app、零构建前端、PyInstaller 外壳；
   `tactics/` 里 279 个脚本本身就是标准 CLI。现在之所以「要 AI 才能用」，是因为
   **脚本顺序、参数、中间产物路径、下一步判断**全靠人/AI 在对话里记住并手工拼命令。
   把这套隐性知识固化成 **Manifest + Pipeline DAG + Runner + 产物浏览器**，AI 就退为可选增强。
2. **一个进程、一个端口、一个入口。** 不新起第二个服务、不再出现 `python3 -m http.server 8792`
   这类独立端口。所有能力挂在 `backend.app:create_app()` 下，沿用 `main.py` → uvicorn → `/app/`。
3. **整仓大一统 = 三域共用一个外壳，不是把三域代码揉成一团。**
   现有 137 路由、战术板 PBP 回放、战术视频流水线各自保持边界，只在导航层与编排层汇合。
4. **桌面形态沿用已验证的「本地 Web app」**：单文件 exe 启动 uvicorn + 自动开浏览器。
   不内嵌 PostgreSQL、43G 战术产物、6TB 录像素材、模型权重 —— 那些是外部资产，
   由 capabilities 探测并明确降级，而不是假装不需要。
5. **红线**：禁止 `import` 任何 `tactics/` 脚本（78 个无 `__main__` 守卫，import 即执行）；
   一律以子进程 CLI 调用。这是 `tactics/README.md` 的探测禁令在架构层的延伸。

---

## 1. 现状盘点（实跑证据）

### 1.1 已有外壳（不用重做）

| 部件 | 事实 | 证据 |
|---|---|---|
| App 工厂 | `create_app()` 挂 **26 个 router**，`/health` 与 `/app/` 均 200 | `backend/app.py:80`；`docs/app-packaging-assessment.md` 实跑 137 路由 |
| 启动入口 | `main.py` 打印自检横幅 → 后台线程开浏览器 → `uvicorn.run(factory=True)` | `main.py:54`、`main.py:93` |
| 打包 | `nbacore.spec` one-file，`collect_submodules("backend")` 自动收路由；`datas` 带 5 项 | `nbacore.spec:36`、`:48` |
| frozen 适配 | `config.py` 与 `app.py` 均判断 `sys.frozen` / `sys._MEIPASS` | `backend/core/config.py:14`、`backend/app.py:181` |
| 降级启动 | lifespan 里 `init_pool()` 失败只记日志，app 以 degraded mode 继续 | `backend/app.py:71` |
| 构建链 | `scripts/build_app.sh` 走 `common/paths.sh`，含资源预检与产物检查 | `scripts/build_app.sh` |
| 前端 | 原生 JS + IIFE + 本地 vendor，**无 npm / 无框架 / 无 build** | `frontend/index.html:1273-1297` |

### 1.2 前端导航机制

`frontend/index.html` 是单页 + 手写侧栏：每个入口是 `<div class="nav-item" data-page="X" onclick="nav('X')">`，
对应一个 `<div id="page-X" class="page">`；`frontend/js/app.js:92` 的 `nav(page)` 负责切页并按页调用
`loadXxxPage()`，后者多数是 `window.Xxx.render('xxxRoot')` 的 IIFE 组件挂载。
**新增一个能力域 = 侧栏一项 + 一个 page 容器 + 一个组件脚本 + `nav()` 一行分发**，无需引入路由框架。

### 1.3 三块能力域（同名陷阱）

| 域 | 现状落点 | 数据依赖 | 说明 |
|---|---|---|---|
| A · NBA 数据/分析 | `backend/api/routers/*.py`（26 个），前端 20+ 页面 | PostgreSQL @5433 | 已完整，137 路由 |
| B · 战术板 / PBP 回放 | `backend/api/routers/tactics.py` + `frontend/js/components/tactics.js` | PostgreSQL（br_crawler xy） | **与 `tactics/` 目录同名但不同子系统** |
| C · 战术视频分析流水线 | `tactics/` 458 个 `.py` + 数据盘 `action_analysis/`（43G） | cv2/torch/模型权重/录像片段 | **目前无任何 HTTP 入口、无编排层** |

🔴 命名空间必须显式分开：`/tactics/*` 继续代表 **B（战术板）**；新增 `/studio/*` 代表 **C 的编排层**。
不得把 C 塞进 `/tactics`，否则语义与既有测试一并被污染。

### 1.4 `tactics/` 脚本形态（AST 静态统计，2026-11-12 实跑）

| 口径 | 数量 |
|---|---:|
| `.py` 可 `ast.parse` | **458 / 458** |
| 有 `__main__` 守卫 | 380 |
| 定义 `main()` | 341 |
| 使用 `argparse` | 303 |
| **守卫 + `main()` + `argparse`（CLI-ready）** | **279** |
| 使用 `common/nba_paths.py` 的 helper | 326 |
| **无守卫（import 即执行）** | **78** |
| 顶层仅依赖标准库、可安全 `--help` 探测 | 55 |

含义：**CLI 调用是天然适配的**，不需要把 458 个脚本改成函数库；
但 78 个无守卫脚本决定了「只能 subprocess、绝不能 import」。

### 1.5 为什么现在「依赖 AI」

一次真实分析需要人/AI 依次完成：
① 记住该跑哪个目录的哪个脚本 → ② 拼对 `--clips/--season/--out` 等参数 →
③ 找到上一步写在数据盘的中间 JSON → ④ 判断产物是否存在、能否跳过 →
⑤ 失败时决定重跑哪一步 → ⑥ 把结果 HTML/视频找出来给人看。
这 6 步**全部没有代码承载**，只存在于对话上下文与技能说明里。这就是「代码包 / 技能支持包」的实质。

---

## 2. 目标形态

### 2.1 一句话

> 双击 `NBACore` → 一个窗口里选「分析任务」→ 填参数 → 点运行 →
> 程序自己按顺序调脚本、显示日志与进度、列出产物；全程不需要 AI、不需要记命令、不需要开终端。

### 2.2 分层

```
┌──────────────────────────────────────────────────────────────┐
│ 桌面外壳  main.py → uvicorn(127.0.0.1:5577) → /app/            │
│ （PyInstaller one-file；可选 WebView 包装，见 §2.4）             │
├──────────────────────────────────────────────────────────────┤
│ 统一前端  frontend/index.html 侧栏                             │
│   A 数据分析 │ B 战术板 │ C 工作台 Studio │ System             │
├──────────────────────────────────────────────────────────────┤
│ 路由层  backend/app.py:create_app()                            │
│   现有 26 router（不动）  +  新增 studio.router                 │
├──────────────────────────────────────────────────────────────┤
│ 编排层  backend/services/studio_engine/   ← 本次要补的核心       │
│   Manifest │ Capabilities │ Runner │ JobStore │ Artifacts      │
├──────────────────────────────────────────────────────────────┤
│ 执行层  subprocess([python, tactics/<step>.py, ...args])       │
│   🔴 绝不 import；cwd 固定；env 注入路径根；日志落盘             │
├──────────────────────────────────────────────────────────────┤
│ 外部资产（不随包分发）                                          │
│   PG@5433 │ <TACTICS_DATA_ROOT> 43G │ 录像库 6TB │ 模型权重    │
└──────────────────────────────────────────────────────────────┘
```

### 2.3 命名空间契约

| 前缀 | 归属 | 变更策略 |
|---|---|---|
| `/`, `/health`, `/docs` | app 元信息 | 不动 |
| 现有 `/players`…`/analytics-builder` 等 26 组 | 域 A | **一行都不改**（保护 805 用例） |
| `/tactics/*` | 域 B 战术板 | **不动**，语义锁定 |
| `/video-library/*` | 录像库 | 不动；`/media` 的白名单防御是 `/studio/media` 的参照实现 |
| `/studio/*` | **新增：域 C 编排层** | 本设计新增，见 §3 |

### 2.4 桌面窗口形态（两档，先做 v1）

| 档 | 形态 | 判断 |
|---|---|---|
| **v1（采用）** | 现有 `NBACore` one-file + 自动开默认浏览器 | 已实测可构建、可启动；双击即用，是独立程序 |
| v2（可选，P4 再评估） | `pywebview` 包一层 WebView 窗口，隐藏控制台 | 只换外壳，不动后端；收益是「像个 app」，代价是新依赖与签名复杂度 |

**不做**：Electron/Tauri 重写前端、内嵌 PostgreSQL、把 6TB 素材塞进 exe。
理由见 `docs/app-packaging-assessment.md` §3.3：属重构级改造，且违背「数据盘只读」既有约定。

---

## 3. 编排层契约（核心设计）

### 3.1 Manifest — 能力目录（唯一顺序来源）

位置 `studio/manifest.json`，声明式、随包分发、纳入 git 与回归测试。一个 step 的字段：

| 字段 | 含义 | 约束 |
|---|---|---|
| `id` | 稳定标识 | 全表唯一 |
| `kind` | `probe` / `pipeline` | P0 只允许 `probe` 真执行 |
| `title` / `description` | UI 文案 | — |
| `script` | 相对 `TACTICS_CODE_ROOT` 的路径 | **禁止 `..`、禁止绝对路径** |
| `args` | 固定参数模板 | 字符串数组，支持 `{param}` 占位 |
| `params` | 参数 schema | `name / type / default / required` |
| `inputs` / `outputs` | 产物 glob（相对 `TACTICS_DATA_ROOT`） | 供 DAG 连线与断点续跑 |
| `requires` | 依赖的 capability key | 缺失即置灰 |
| `writes_data` | 是否写数据盘 | `true` 的步骤必须显式确认 |
| `timeout_sec` | 超时 | 默认 300 |
| `status` | `active` / `planned` | `planned` 只展示顺序，不可运行 |

🔴 **顺序与参数一旦写进 Manifest，就不再是 AI 的记忆**。
但「哪些真实步骤该按什么顺序连成 C→B→A 语料标注链路」属于**主理人视觉签核前置**的内容，
未经签核一律标 `planned`、不得编造为 `active`。

### 3.2 Pipeline DAG

`pipelines[]` 每项由 `steps: [id…]` 组成，前置 step 的 `outputs` 若已存在且校验通过则跳过（断点续跑），
失败即停并保留已完成的产物。DAG 必须无环、每个 `id` 必须在 `steps` 中存在 —— 由加载器校验。

### 3.3 Runner — 唯一执行通道

```
plan(step_id, params)
  → 查 manifest → 校验参数类型 → 校验 script 落在 TACTICS_CODE_ROOT 内
  → 拼 argv = [interpreter, script_abs, ...rendered_args]
  → 返回 {cmd, cwd, env_delta, blocked_reason}      # 不执行

submit(step_id, params, execute)
  → kind/requires/写盘权限校验 → 不通过则 job.status = "blocked"（不报错、不写盘）
  → 通过则起子线程：subprocess.run(..., timeout, capture_output, text=True)
  → stdout/stderr 合并写入 job.logs，并落 <TACTICS_DATA_ROOT>/studio/jobs/<id>.log
  → rc=0 → "ok"；非 0 / 超时 → "failed"
```

强制不变量：

- **只 `subprocess`，不 `import` / `importlib` / `runpy`**（78 个无守卫脚本的探测禁令）。
- `cwd` 固定 `REPO_ROOT`；`env` 注入 `NBA_REPO_ROOT` / `NBA_DATA_ROOT`，
  并**清空继承的 `PYTHONPATH`**（避免 WorkBuddy sitecustomize broker 在子进程里拦截 `open()`）。
- 脚本路径用 `tactics_code_file()` 解析，产物路径用 `tactics_data_file()`；
  **源码里不得出现任何绝对路径字面量**（门禁 11a 全文扫描）。
- 参数渲染只做白名单字符串替换，不拼 shell、`shell=False`（防命令注入）。
- P0 默认 `execute=false`；只有 `kind=probe && writes_data=false` 的 step 允许真跑。

### 3.4 Capabilities — 降级矩阵

`GET /studio/capabilities` 返回布尔 + 原因，前端据此置灰，而不是让按钮点了报 500：

| key | 探测方式 | 缺失时表现 |
|---|---|---|
| `tactics_code` | `tactics_code_file().is_dir()` | 全部步骤置灰 |
| `tactics_data` | `tactics_data_file().is_dir()` | 产物浏览器与写盘步骤置灰 |
| `python` | 解释器可执行且非 frozen | 全部步骤置灰（见 §5.2） |
| `database` | 轻量 TCP 连通（不建连接池） | 域 A 页面由 `/health` 自行降级 |
| `video_root` | 录像库目录存在 | 录像相关步骤置灰 |
| `frozen` | `getattr(sys, "frozen", False)` | 提示走外部路径配置 |

### 3.5 Job 状态机与产物浏览器

`pending → running → ok | failed | blocked`。JobStore 内存态 + 日志落盘；
`GET /studio/jobs`、`GET /studio/jobs/{id}` 供前端轮询（P0 用轮询，P1 再上 SSE / WebSocket）。
`GET /studio/artifacts` 只列 `TACTICS_DATA_ROOT` 白名单内的文件，**复用
`backend/api/routers/video_library.py:get_media` 的 `Path.relative_to(root)` 目录穿越防御**，
绝不根据请求参数拼接任意路径。

---

## 4. 打包契约（frozen 两个真实陷阱）

### 4.1 路径根在 frozen 下会漂移

`common/nba_paths.py:30` 用 `REPO_ROOT_DEFAULT = Path(__file__).resolve().parent.parent` 推断仓库根。
frozen 时该文件被解包到 `sys._MEIPASS/common/`，于是 `REPO_ROOT` 会指向**解包临时目录**，
`DATA_ROOT` 会去它的父目录找 `nba_pg / raw_archive / headshots` 特征标记，必然找不到。

**结论**：打包版必须在 exe 同目录 `.env`（`config._load_dotenv()` 已支持读 `BASE_DIR/.env`）
或环境变量里显式给出 `NBA_REPO_ROOT` 与 `NBA_DATA_ROOT`。
`capabilities` 要检查两者解析结果是否真的含 `tactics/` 与 `action_analysis/`，
否则明确报「路径根未配置」，而不是把任务跑到一个临时目录里。

### 4.2 `sys.executable` 在 frozen 下不是 Python 解释器

one-file 打包后 `sys.executable` 指向 `NBACore` 可执行程序本身，用它跑 `.py` 必然失败。
Runner 的解释器解析顺序：

1. 环境变量 / `.env` 的 `STUDIO_PYTHON`（显式指定外部 `.venv/bin/python` 或 `python3`）；
2. 非 frozen 时用 `sys.executable`；
3. frozen 且未配置 → `capabilities.python = false`，执行类步骤全部 `blocked`。

### 4.3 `datas` 清单增量

| 资产 | 是否随包 | 理由 |
|---|---|---|
| `studio/manifest.json` | ✅ 是 | 能力目录是契约，必须随包 |
| `frontend/`、`NBAlogo/`、`viz/theme_tokens.json`、`.env.example`、`db/schema.sql` | ✅ 是（现状） | 不变 |
| `tactics/` 458 个 `.py`（约 4.36 MiB） | ⚠️ P4 再定 | 源码能带，但 cv2/torch/模型权重带不了；带了也可能跑不起来，需配合 §4.2 外部解释器 |
| `action_analysis/` 43G、录像库 6TB、PostgreSQL | ❌ 否 | 外部资产，只读引用 |

---

## 5. 工程红线与不变量

1. **不改现有 26 个 router 任何一行**；只在 `app.py` 增加 `studio.router` 的 import 与 include。
2. **新增 `.py` 零绝对路径字面量**（门禁 11a 扫描全文，含注释与 docstring）。
3. **ruff Tier-1 干净**；新路由必须可被 `test_packaging_spec.py::test_every_router_is_importable` 导入，
   且不引入新的第三方依赖。
4. **`collect_submodules("backend")` 自动覆盖新 router**，禁止回退到手写 hiddenimports。
5. **禁止 import `tactics/`**（含冒烟测试）；`tactics/` 侧只允许 AST 静态解析。
6. **禁止第二个端口 / 第二个服务**；`label_ball_app.py`、`track_judge_app.py` 等手搓
   `http.server` 半成品保持原位，后续能力统一收编到 `/studio`。
7. **不把 LLM/AI 放进主执行链**；AI 只能作为可选的结果解读增强，去掉它程序照常跑完全流程。
8. **不把未签核的流水线顺序写成事实**，`planned` 与 `active` 严格区分。
9. 提交前 / 提交后各复验一次门禁（文件从 ignore 区进入受检区是独立验证事件）。

---

## 6. 阶段拆分

| 阶段 | 内容 | 完成判据 |
|---|---|---|
| **P0 · 契约与骨架** | Manifest schema + Capabilities + Plan/Job API + `/studio` 前端工作台 + 回归测试；只放行 `probe` 步骤 | 门禁 42/42、ruff 0、全量 pytest 全绿；UI 能列出能力、生成计划、实跑一个只读 `--help` 并看到日志 |
| **P1 · Runner 实跑** | 3 个安全脚本垂直切片、日志落盘、超时/取消、参数校验、失败原因归因 | 无需 AI 即可在 UI 跑完一条 3 步链路 |
| **P2 · Pipeline DAG** | 多步编排、产物校验、断点续跑、失败重跑、SSE 实时日志 | 主理人签核后的 C→B→A 链路可从 UI 一键运行 |
| **P3 · 产物浏览器** | 按 job/step 分组产物、预览/下载、与录像库 / 战术板联动 | 产物可直接在同一窗口查看 |
| **P4 · 打包与外壳** | spec datas 契约、frozen 路径引导、构建冒烟、可选 WebView 窗口 | 打包版双击可用且明确提示外部依赖状态 |

### 验证门禁（每个阶段都要跑）

```
python tools/verify_quality_gate.py        # PASS=42 FAIL=0
ruff check .                               # All checks passed
pytest -q                                  # 基线 805 passed / 1 skipped
node --test frontend/tests/*.test.js       # 前端契约
bash scripts/build_app.sh                  # P4 起，构建 + /health + /app/ 冒烟
```

---

## 7. 诚实边界 / 明确不做

- 本文**不代表已经实现**上述全部能力；P0 只交付契约、只读探测与工作台骨架。
- 「独立程序」在本设计里指**双击即用、不依赖 AI/终端、自含编排知识**；
  不等于**离线自包含**：PG、43G 产物、6TB 素材、模型权重仍是外部资产。
- 真实战术步骤的顺序、参数与产物口径需要主理人视觉签核后才会转成 `active`；
  本文不代替签核，也不猜测 C→B→A 的具体脚本链。
- 78 个无 `__main__` 守卫脚本的语义保持不变，本设计不补守卫、不改写它们。
- 12/13 个 `tactics/*.sh` 硬编码路径、`scripts_registry.py --check` 缺口、
  旧复评分未按新基线重评，仍是各自独立未结项，不并入本阶段。

---

## 8. 阶段 0 落地清单（本轮同步交付）

| 文件 | 作用 |
|---|---|
| `docs/unified-desktop-app-architecture.md` | 本文 |
| `studio/manifest.json` | 能力目录：1 个 `active` 只读 probe + `planned` 步骤/流水线示例 |
| `backend/services/studio_engine/` | `manifest.py` / `capabilities.py` / `runner.py` |
| `backend/api/routers/studio.py` | `/studio/*` 薄路由 |
| `backend/app.py` | 仅新增 2 行（import + include_router） |
| `frontend/js/components/studio.js` + `index.html` + `app.js` | 工作台页面与导航 |
| `nbacore.spec` | `datas` 增加 `studio/manifest.json` |
| `tests/test_studio_contract.py` | 契约回归测试（禁止 import tactics、计划不执行、blocked 不写盘） |
