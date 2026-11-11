# 打包成本地 App — 构建与运行说明

> 落地日期：2026-11-11 · 构建工具 PyInstaller 6.22.3 / Python 3.12.13
> 相关评估见 `docs/app-packaging-assessment.md`。

## 形态与边界（先读这一段）

产物是**本地 Web app**：一个单文件可执行程序，启动后在本机跑 uvicorn（FastAPI），
自动打开默认浏览器访问 `http://127.0.0.1:5577/app/`。

- **随包携带**：`backend/` 全部子模块、`common` 的 3 个纯标准库模块、`viz.theme`、
  `frontend/`（原生 JS + 本地 ECharts/Plotly）、`NBAlogo/`、`viz/theme_tokens.json`、
  `.env.example`（配置模板）、`db/schema.sql`（结构 DDL）。
- **不随包携带**：PostgreSQL 实例与任何数据行、真实 `.env`/`DB_PASSWORD`、
  24G 级 `raw_archive` 归档、6TB 录像素材、Chrome/Playwright 爬虫链。
- 因此它**不是离线自包含的桌面软件**：需要一台可达的 PostgreSQL 18（默认 `127.0.0.1:5433` / 库 `nba`）。
  没有数据库也能启动，`/health` 会明确显示 `database_connected=false`（`lifespan` 的 degraded mode），
  但数据类功能不可用。

## 构建

```bash
cd /path/to/nba_desktop_omega_mac_migrate_2026-07-13
bash scripts/build_app.sh
```

脚本会：

1. `source common/paths.sh` 拿到 `PROJ_ROOT` / `VENV_PYTHON`（**零硬编码绝对路径**，受质量门禁约束）；
2. 检测 `.venv` 里有没有 PyInstaller，没有就按 `pyproject.toml` 的 `build` extras 安装；
3. 校验 spec 声明的资源文件都在（避免打出缺资源的空壳）；
4. 执行 `.venv/bin/python -m PyInstaller --noconfirm nbacore.spec`；
5. 打印产物路径与体积。

等价的手工命令：

```bash
.venv/bin/pip install -e '.[build]'      # 或直接 pip install "pyinstaller>=6.11,<7"
.venv/bin/python -m PyInstaller --noconfirm nbacore.spec
```

产物：`dist/NBACore`（macOS/Linux 无扩展名，Windows 为 `NBACore.exe`），约 **43 MiB**
（one-file 每次构建字节数略有浮动）。`dist/`、`build/` 已在 `.gitignore` 中，不会入库。

> 🔴 **不要给构建命令加 `--clean`**：它会递归删除 PyInstaller 全局缓存
> （`~/Library/Application Support/pyinstaller/bincache*`，>50 文件），在本机受限环境下
> 触发批量删除保护而中断构建；缓存是否新鲜不影响产物正确性，`--noconfirm` 已足够覆盖旧产物。
> 增量构建会正确检测源码变更（实测日志 `Building because backend/core/runtime_guard.py changed`）。

## 运行前准备

1. **PostgreSQL**：确保目标机有 PG 在 `5433` 端口、存在 `nba` 库。
   只有结构时可用随包的 `db/schema.sql` 初始化（`psql -f db/schema.sql`）——**它不含任何数据行**。
2. **连接配置**（二选一，推荐 A）：
   - **A · 环境变量**（口令不落盘，适合开发与冒烟）：`DB_PASSWORD=<口令> ./NBACore`。
     `config.py` 的 `.env` loader 用 `os.environ.setdefault`，显式环境变量优先级更高。
   - **B · `.env` 文件**：复制 `.env.example` 为 `.env` 并填 `DB_PASSWORD`，放到 **exe 同目录**。
     frozen 下 `BASE_DIR = Path(sys.executable).resolve().parent`，依次找
     `BASE_DIR/.env` → `sys._MEIPASS/.env`。
   - 🔴 **仓库根的 `.env` 不会被冻结产物读取**。2026-11-11 首轮冒烟只启动了
     `dist/NBACore` 未注入凭据 → 日志 `fe_sendauth: no password supplied`，
     `/health` 为 `degraded` + `database_connected=false`、数据端点 500。
     这不是打包缺陷，而是运行前准备缺失；注入凭据后全部转绿。
3. 双击 / 命令行运行 `NBACore`，浏览器会自动打开；Ctrl+C 退出。
4. 自检：`curl -s --noproxy '*' http://127.0.0.1:5577/health`，应返回 `status=ok`、
   `database_connected=true`、3 个 runtime guard 全 `ok`。
   one-file 首次解压启动约 **30s**（设 `PYTHONUNBUFFERED=1` 才能实时看到日志；
   启动初期 `http=000` / 空日志不等于崩溃）。

## 启动自检

### 运行时 guard（`/health`）

产物 `dist/NBACore`（macOS arm64，约 43 MiB），带凭据启动后的实测：

| 检查项 | 结果 |
|---|---|
| `/`、`/app/`、`/docs`、`/openapi.json` | 200 / 200 / 200 / 200（139,976 字节 OpenAPI） |
| `/teams` | 200，`{teams:[...], total:30}`，30 支 active 球队（真实 SQL） |
| `/health` | 200，`status=ok`、`database_connected=true` |
| `config_loaded` / `metric_engine_exists` | `ok=true` / `ok=true` |
| `no_forbidden_patterns` | `ok=true`，`detail.skipped = "source not on disk (frozen build); enforced by CI lint/quality gate"` |

🔴 **frozen 下源码在 PYZ 归档里、磁盘上没有 `.py`**：`runtime_guard` 旧实现
`open(db_mod.__file__)` 会抛 `FileNotFoundError`，被 `run_startup_checks` 兜成 `ok=False`，
导致打包版 `/health` **永远显示 degraded**。现改为「frozen 或源码不存在时返回
`ok=True` + 明确 `skipped` 原因」，静态源码约束交由**构建前的 CI ruff + 质量门禁**承担；
非 frozen（源码在磁盘）时扫描照常执行。双向行为都由回归测试锁住。

### 启动横幅自检（`main.py`）

进程一启动就在控制台打印 `Mode`（frozen / source）、`DB port`（轻量 TCP 探测，
1.5s 超时、无需凭据）、`DB secret`（**是否配置口令，不打印值**），并给出三种结论：

```
  Mode:      frozen (bundled)
  DB port:   localhost:5433 (reachable)
  DB secret: NOT SET
  [WARN] 端口可达但未提供口令 —— 请设 DB_PASSWORD，或在 exe 同目录放 .env
```

```
  DB secret: configured
  [OK]   数据库前置条件齐备，连接结果以 /health 为准
```

它**不改任何 router 行为**，也不创建连接池（真实凭据校验仍由 lifespan 的 `/health` 承担），
解决的是「双击后只看到 degraded、却不知道为什么」的可诊断性问题。

🔴 frozen 下 stdout 重定向到文件是**块缓冲**：横幅会一直憋在缓冲区，日志里只剩走
stderr 的 uvicorn / app 日志（实测 2026-11-11）。`main.py` 用
`sys.stdout.reconfigure(line_buffering=True)` 强制行缓冲，回归测试锁住这一点。

> 无凭据（或未配 PG）时 `/health` 的 degraded 与数据端点报错属**预期降级**，
> 不是打包回归；分发前请把第 2 步做实。

## 已知限制（按功能）

| 依赖外部资产的功能 | 缺失时表现 | 建议 |
|---|---|---|
| 数据类全部路由 | `/health` 显示 `database_connected=false`，查询抛 `OperationalError`（HTTP 500） | 配好 PG 与凭据 |
| `video_library` | 读 `_VIDEO_ROOT`，缺目录则列表为空 | 设 env 指向素材盘，或不用该功能 |
| `crawler` | 需 `NBA_PYTHON` / `CRAWLER_SCRIPT` 外部脚本 | 分发包内不提供爬虫，属预期 |
| `coverage` 部分统计 | 读 `NBA_ARCHIVE_ROOT` / `raw_archive/br/**` | 有回退代理，数值口径会变 |

CORS 白名单写死 `http://127.0.0.1:5577` / `http://localhost:5577`，且**无鉴权** ——
仅限本机单用户使用，不要监听 `0.0.0.0` 或暴露到局域网。

## 维护铁律（防止 spec 再次失修）

旧 `nbacore.spec` 手写 `hiddenimports` 只列 7 个 router，而 `backend/app.py` 实际 include 26 个；
`datas` 也漏了 backend 依赖的 `common.nba_paths` / `common.season_type_norm` / `viz.theme`。
这类失修不会让 CI 变红，只会在用户机器上表现为「某些页面打不开」。

现在由 `tests/test_packaging_spec.py`（**11 项**，CI 可跑、不需要装 PyInstaller）守住：

1. spec 必须用 `collect_submodules("backend")` 自动收集，**禁止手写 router 清单**；
2. `backend/app.py` 里每个 `include_router` 的模块都必须可导入；
3. 3 个顶层依赖模块必须显式声明；
4. spec `datas` 点名的资源必须真实存在；
5. `Analysis(...)` 不得再传 PyInstaller 6 已移除的 `cipher` / `win_*` 参数（**AST 检查**，
   不能用字面行判据 —— spec docstring 里记录了这些名字，会被误判）；
6. `config.py` / `app.py` 的 `sys._MEIPASS` 适配不许被删；
7. 构建脚本必须 source `common/paths.sh` 且无硬编码绝对路径；
8. `pyproject.toml` 必须声明 `build` extras；
9. **frozen 下 `runtime_guard` 源码扫描必须跳过并标明 skipped**，不得把 `/health` 拖成 degraded；
10. **非 frozen 时源码扫描必须照常执行**（`detail.scanned == "backend.core.db"`）；
11. **启动横幅自检必须存在**（轻量 TCP 探测 + 口令配置提示 + 行缓冲），且启动前不创建连接池。

新增 router 时**不需要改 spec**（自动收集），但建议跑一次
`pytest tests/test_packaging_spec.py` 确认可导入。
CI 只跑上述静态契约测试；**产物构建由本地/发布流程执行**，避免在不带数据盘的 runner 上
构建出一个无法验证的二进制。

## 与既有文件的关系

- `main.py`：EXE 入口；`_MEIPASS` 资源定位 + 启动横幅自检（DB 前置条件、行缓冲）。
- `backend/app.py` / `backend/core/config.py`：已内建 frozen 适配，无需为打包改造。
- `backend/core/runtime_guard.py`：本轮为 frozen 模式加了源码扫描跳过分支。
- `build.ps1` / `start.bat` / `start.ps1`：**Windows 旧构建脚本**，仍可用但不会自动同步 spec；
  跨平台优先用 `scripts/build_app.sh`。
- `Dockerfile` / `docker-compose.yml`：**不是本 app 的构建文件**，是 node-media-server
  （RTMP 流媒体）实验残留，勿据此构建 NBACore。
- `OFFLINE_README.md`：描述的是「内置 .venv 的离线整包」方案，与 PyInstaller one-file 是两条路线。
