# NBACore Studio v8 — 代码质量评估 & 打包成 App 可行性

> 评估日期：2026-11-11 · 分支 `chore/path-governance-2026-11-10` · HEAD `48a057b`
> 范围：**只评估、只报告**，未实际打包、未改动任何生产代码。
> 数据来源：本机实跑 + `git ls-files` / `git grep`（只读版本库清单，不递归扫描外置盘大目录）。

---

## 0. 结论先行

**能打包，而且基础已经打好 —— 但产物形态是「本地 Web app」，不是「自包含、双击即用、无需外部数据库」的桌面软件。**

- 仓库里**已经有一套 PyInstaller 打包链路**：`nbacore.spec` + `main.py`（启动 uvicorn → 自动开浏览器 → `/app/`），
  且 `backend/core/config.py`、`backend/app.py` 都已做 `sys.frozen` / `sys._MEIPASS` 适配。
- **app 本体实测完全可运行**：`create_app()` 成功、137 条路由、`/health` 200 且 DB 已连、`/app/` 200。
- 工程质量在同类项目里属**上游**：42 项持续门禁、ruff 零违规、787 用例全绿、CI 四 job 全绿、schema-only postgres 三档门控。
- 但**打包链路本身失修**：spec 的 hiddenimports 只声明 7 个 router，实际 26 个（缺 19）；
  PyInstaller 当前环境未安装；`Dockerfile`/`docker-compose.yml` 其实是**另一个项目**（node-media-server 流媒体），与 app 无关。
- 最大硬约束不是代码，是**数据**：app 依赖外部 PostgreSQL 18 @ 5433（199 张 public 表）与盘上大体积归档/素材。
  打包 exe 可以不含数据，但**不能假装不需要**。

| 形态 | 可行性 | 判断 |
|------|--------|------|
| 本地 Web app（单文件 exe + 自动开浏览器，连本机 PG） | **高** | 已有 80% 基础，补齐 spec + 构建链即可 |
| 纯桌面 GUI（Tauri/Electron/Qt） | 中 | 前端是原生 JS，可直接塞进 WebView；但等于重写外壳，收益低 |
| 完全自包含（含数据库 + 全部数据，离线开箱即用） | **低** | 需内嵌 PG 或换 SQLite + 数据迁移，属重构级改造 |
| 云端多用户 SaaS | 低（当前） | 单机 CORS（127.0.0.1:5577）、无鉴权、DB 直连本机，需补认证与多租户 |

---

## 1. 实测数据（证据）

### 规模（`git ls-files`，2026-11-11）

| 口径 | 数值 |
|------|------|
| 已跟踪文件 | 1150 |
| `.py` / `.sh` / `.html` / `.sql` | 651 / 54 / 77 / 69 |
| `tests/` / `tools/` | 76 / 12 |
| 顶层最大目录 | `external_crawler` 234、`backend` 194、`scripts` 80、`tests` 76、`NBAlogo` 76、`docs` 75 |
| backend 分层 | `core` 6、`api` 32、`services` 134、`data_layer` 18 |
| 可打包静态资产 | `frontend/` 6.4M、`NBAlogo/` 2.5M、`headshots/` 29M |
| DDL | `db/schema.sql` 526 个 CREATE 对象 |

### 质量基础设施

| 口径 | 结果 |
|------|------|
| 质量门禁 `tools/verify_quality_gate.py` | **PASS=42 / FAIL=0 / SKIP=0** |
| ruff 全仓 | **0 违规**（`pyproject.toml` 分层豁免，Tier-1 严格零豁免） |
| 全量回归（本地真库） | **787 passed / 1 skipped / 0 failed** |
| CI run 42884844594 | success；test job 691 passed / 97 skipped / 0 failed |
| CI 结构 | `secret-scan` / `lint` / `test`（postgres 18 service + 仅还原 schema）/ `frontend-test`；`quality-gate`、`docker-build` 仅主干 |
| 测试文件 | 56 个 `tests/test_*.py`，三档门控 `needs_db` / `needs_data` / `db_has_schema` |

### 运行时冒烟（本机实跑，非推断）

```
create_app() OK, routes = 137
/health  status = 200  status=ok  db_connected=True  guards=3
/app/    status = 200  bytes = 64559
```

`backend/app.py:80` 的 `create_app()` 是标准 FastAPI 工厂，挂载了 **26 个 router**；
`lifespan` 里 DB pool 初始化失败会进入 **degraded mode** 而非崩溃 —— 这点对打包很友好
（没装 PG 的机器也能启动，只是数据类功能不可用）。

---

## 2. 代码质量评估

### 强项

1. **分层清晰**：`backend/core`（config/db/logging/runtime_guard）→ `services`（134 个，指标/上下文/导出/交易引擎）
   → `api/routers`（32 个）→ `data_layer`（18 个）；`app.py` 只做编排，不含业务逻辑。
2. **工程化完备**：ruff 门禁 + 42 项质量门禁 + CI 四 job + schema-only postgres，且门禁把
   「路径治理」「色板单一来源」「语义等价还原比对」等历史教训都固化成了可执行断言。
3. **配置外置做得对**：`DB_PASSWORD` 不硬编码（缺失即空、fail-safe），`.env` 手工解析无额外依赖；
   `common/nba_paths.py` / `common/paths.sh` 是跨语言路径唯一来源，门禁保证已跟踪源码零硬编码绝对路径。
4. **前端零构建**：原生 JS + IIFE + 本地 vendor（`frontend/vendor/echarts.min.js`、`plotly.min.js`），
   无 npm build、无框架 —— 打包时直接 `datas` 塞进去即可，没有 toolchain 风险。
5. **测试有真实覆盖**：真库 787 用例，CI 用 schema-only 还原在 0.3s 内拿到完整结构。

### 技术债与风险（按影响排序）

| # | 问题 | 证据 | 影响 |
|---|------|------|------|
| 1 | **打包链路失修** | `nbacore.spec` hiddenimports 7 个 router，`backend/app.py` 实际 26 个；缺 `analytics_builder`、`career`、`clutch`、`crawler`、`trade`、`tactics`、`video_library` 等 19 个 | spec 是 v8.0.0 早期快照，后续新增路由未同步；`datas` 也只带 `frontend` + `NBAlogo`，漏了 `common/`、`viz/`、`db/schema.sql` |
| 2 | **构建工具未纳入依赖** | `pyproject.toml [project]` 无 PyInstaller；`.venv` 实测 `ModuleNotFoundError: No module named 'PyInstaller'` | 换台机器无法复现构建 |
| 3 | **Dockerfile 是别的项目** | `FROM node:18-alpine` + `node-media-server`（RTMP 1935/8000/8443） | 误导性残留；CI 的 `docker-build` job 与此镜像无直接关系 |
| 4 | **外部数据强绑定** | `backend/data_layer/coverage_loader.py` 读 `NBA_ARCHIVE_ROOT`/`raw_archive/br/**`；`backend/api/routers/video_library.py:42` 读 `_VIDEO_ROOT`；`crawler.py` 依赖 `NBA_PYTHON`/`CRAWLER_SCRIPT` 外部脚本 | 打包版在缺这些资产的机器上，相关路由会空/报错，需明确降级提示 |
| 5 | **单机假设** | `backend/app.py:91` CORS 写死 `http://127.0.0.1:5577`；`config.py` DB 默认 `127.0.0.1:5433` | 适合本地 app，不适合云部署；打包无碍，但要意识到边界 |
| 6 | **无鉴权** | 全仓未见认证中间件 | 本地单用户可接受；一旦监听 0.0.0.0 或多用户即有风险 |
| 7 | **根目录/仓库体积混杂** | 651 个 `.py`，其中大量一次性分析脚本；`external_crawler` 234 文件属独立子系统 | 增大 PyInstaller 分析范围与误收风险（spec 已用 `excludes` 排除部分，但手写清单易漏） |
| 8 | **requirements 含爬虫重依赖** | `playwright`、`undetected-chromedriver`、`curl_cffi` 与 backend 运行无关，却在生产依赖里 | 打包体积与冷启动被拖累，应拆 `[project.optional-dependencies]` |

> 注：`workspace/README.md` 有「不移动、不重命名、不删除既有文件」与「孤儿产物只登记不删除」约定，
> 其约束对象是 `reports/` 产物与逻辑收敛，不是打包链路；本轮清理已由主理人明确授权。

---

## 3. 打包可行性详评

### 3.1 已有基础（这部分不用重做）

- `nbacore.spec`：PyInstaller 单文件 `EXE(name="NBACore", console=True)`，
  `datas` 带 `frontend` + `NBAlogo`，`excludes` 排掉 tkinter/matplotlib/scipy/jupyter/pytest。
- `main.py`：打印启动信息 → 后台线程 `webbrowser.open("http://127.0.0.1:{PORT}/app/")`
  → `uvicorn.run("backend.app:create_app", factory=True)` → Ctrl+C 退出。
- `backend/core/config.py:10`：已判断 `sys.frozen`，`BUNDLE_DIR = Path(sys._MEIPASS)`，
  并从 `BASE_DIR/.env` 与 `BUNDLE_DIR/.env` 两处找配置。
- `backend/app.py:175`：同样用 `sys._MEIPASS` 定位静态目录，两个 mount（`/app`、`/assets/logos`）。
- `pyproject.toml [project]` 已有 `name/version/requires-python>=3.10/dependencies`，
  只差 `[project.scripts]` 或构建脚本入口声明。

### 3.2 障碍清单：必须改造 vs 可保留

**必须改造**

1. **修 `nbacore.spec`**：把 26 个手写 `hiddenimports` 换成
   `from PyInstaller.utils.hooks import collect_submodules; hiddenimports = collect_submodules("backend")`
   —— 手写字单已被证明会随新增路由过时，用自动收集根除。
2. **补 `datas`**：至少加 `common/`、`viz/`（若页面用到）、`db/schema.sql`（可选，用于引导初始化）；
   确认 `NBAlogo` / `frontend` 在 frozen 下路径正确。
3. **构建工具进仓**：`[project.optional-dependencies] build = ["pyinstaller==…"]`，
   并加 `scripts/build_app.sh`（或 `python -m PyInstaller nbacore.spec`），让构建可复现。
4. **DB 连接可配置化**：打包版首次启动需要填 host/port/db/user/password。
   `config.py` 已支持 env 覆盖，缺的是**一个 UI 或引导步骤**；最低成本是「读 exe 同目录 `.env`，
   没有就 `/health` 明确显示 `database_connected=false` + 提示」。
5. **外部资产路由降级**：`video_library`、`crawler`、`coverage` 等依赖盘上素材/外部脚本的路由，
   在打包版应可开关并给出明确提示，而不是静默返回空或 500。
6. **清掉误导性 Dockerfile**：换成真正的 app 镜像（python:3.12-slim + uvicorn），
   或直接删除并在文档注明「本仓库 Dockerfile 属流媒体实验，非 app 构建」。
7. **CI 加 build 冒烟**：仅 `main`/tag 触发，构建 exe 后用 `TestClient` 验 `/health` + `/app/`，
   防止 spec 再次失修而无人发现。

**可保留（不必动）**

- 前端零构建、`config.py` 的 frozen-aware、静态目录双路径处理、`lifespan` 的 degraded mode。
- 本机 PG 作为数据源 —— 对「本机 app」形态是合理的，不必内嵌。
- `requirements.txt` 的固定版本（可复现性好），只需把爬虫重依赖拆到 optional。

### 3.3 建议路线（按投入递增）

| 阶段 | 动作 | 产出 |
|------|------|------|
| A · 最小可行（推荐先做） | 修 spec + 加 build extras + 构建脚本 + 本地跑一次 `pyinstaller nbacore.spec`，用 TestClient 冒烟 | 一个能双击运行的 `NBACore` exe，连本机 PG 即可用全部 137 路由 |
| B · 体验补齐 | 首次启动连接向导（或 exe 同目录 `.env` 模板）、外部资产路由降级提示、图标/版本信息 | 给非技术用户也能用 |
| C · 工程化 | CI build job + artifact、自动体积门禁、把爬虫依赖拆 optional | 打包链路不再失修 |
| D · 形态升级（可选） | Tauri/Electron 包一层 WebView，或用真正 Dockerfile 做服务端部署 | 更像「app」/ 可分发；但收益主要是外壳 |

**不建议**：内嵌 PostgreSQL + 全量数据做「离线自包含」。199 张表 + 24G 级归档 + 6TB 素材，
体积与初始化成本都不可控，且违背项目「数据盘只读」的既有约定。

---

## 4. 诚实边界

- 本轮**未实际执行 PyInstaller 构建**：当前 `.venv` 未安装该包，且用户指令为「评估/看看能不能」，
  属报告范围；「可行性高」的结论建立在「已有 spec + app 实跑 200 + 前端零构建」三项实测之上，
  不等于「构建一定一次成功」。
- 外置盘大目录（`raw_archive` 24G、`work/models` 等 11G、6TB 素材）**未递归实测** ——
  `workspace/README.md` 明确警告全盘遍历会卡死 / OOM（本轮排查时已实测 `grep -r` 触发 exit 137）；
  相关体量按项目记忆与一级 `du -sh` 给出。
- 后台调研代理本轮运行 15 分钟未返回任何内容（同样疑似卡在大目录遍历），
  本报告全部数据由主会话本地实跑取得，**未采用代理输出**。
- 打包版的功能完整性取决于目标机器是否有可达的 PostgreSQL 与相应数据表；
  `db/schema.sql` 只能建结构，不含数据。

---

## 5. 附：本轮同时完成的清理

按主理人授权删除全仓唯一「跟项目无关」的脚本群 `nba_subtitle_tool/` 源码层
（19 个已入库文件 + `srt2ass.py` + `.DS_Store`，共 21 个），11G 素材原封保留，
源码同卷备份在 `.trash/nba_subtitle_tool_src_20261111/`（已 gitignore，可恢复）。
83 个 NBA 相关一次性脚本经盘点确认均操作本项目数据，全部保留。
详见 `docs/change-log.md` 2026-11-11 段与 commit `48a057b`。
