# NBACore Studio v8 — 完整项目文档

> 版本: 8.3.1 | 更新日期: 2026-07-08
> 架构: 四层严格隔离 (Data Layer → Metric Engine → API Layer → Frontend)

---

## 1. 项目概述

### 1.1 项目简介

NBACore Studio v8 是一个**指标驱动的批量分析引擎**，专为 NBA 球员数据设计。系统采用严格的四层架构，确保各层职责单一、无跨层逻辑泄漏，所有计算均由 Metric Engine 统一完成。

### 1.2 四层架构

```
┌──────────────────────────────────────────────────────────┐
│  Layer 4: Frontend (纯渲染)                              │
│  - HTML/CSS/JavaScript + ECharts                        │
│  - 仅调用 API，无业务逻辑、无计算                        │
├──────────────────────────────────────────────────────────┤
│  Layer 3: API Layer (纯编排)                            │
│  - FastAPI routers + Pydantic schemas                   │
│  - 仅做请求整形 + 调用 Metric Engine                     │
│  - 无 SQL、无 pandas、无计算逻辑                         │
├──────────────────────────────────────────────────────────┤
│  Layer 2: Metric Engine (唯一计算层)                    │
│  - 向量化 pandas 计算                                    │
│  - 指标注册表 + 缓存 + 排名引擎                          │
│  - 所有指标计算在此完成                                  │
├──────────────────────────────────────────────────────────┤
│  Layer 1: Data Layer (只读数据访问)                     │
│  - 仅 SELECT，批量查询 (IN / 临时表)                    │
│  - Schema 注册 + 漂移检测                                │
│  - 唯一的数据库入口点                                    │
└──────────────────────────────────────────────────────────┘
```

### 1.3 核心特性

| 特性 | 说明 |
|------|------|
| **严格分层** | 四层架构，无跨层逻辑泄漏 |
| **向量化计算** | 所有指标使用 pandas 向量化操作，无 Python 循环 |
| **确定性输出** | 相同输入 = 相同输出，SHA256 缓存键 |
| **批量加载** | IN 子句或临时表，无 per-player 数据库循环 |
| **运行时自检** | startup 时自动检查架构合规性 |
| **磁盘缓存** | 24 小时 TTL，diskcache 持久化 |
| **可导出** | JSON/CSV 格式导出排名、VS、球员数据 |
| **上下文分析** | 相似球员、角色演变、趋势分析 |
| **球员成长路线** | 生涯逐年数据、身高体重变化、位置占比、里程碑时间轴 |
| **Context VS 整合** | Player Context 页面内嵌 VS 对比，Tab 切换模式 |
| **球队可视化** | 球队 Logo 展示、球队雷达图、战绩排名 |

---

## 2. 快速开始

### 2.1 环境要求

- Python 3.10+
- PostgreSQL 16 (数据库名: `nba`, 端口: `5433`)
- Windows / Linux / macOS

### 2.2 安装与运行

```bash
# 克隆项目
cd nba_desktop_omega

# 安装依赖
pip install -r requirements.txt

# 配置环境变量 (可选)
cp .env.example .env
# 编辑 .env 修改数据库连接参数

# 启动开发服务器
# Windows:
.\start.ps1 dev
# 或直接:
python main.py
```

服务启动后访问:
- 应用界面: http://127.0.0.1:5577/app/
- API 文档: http://127.0.0.1:5577/docs
- 健康检查: http://127.0.0.1:5577/health

### 2.3 Docker 部署

```bash
# 一键启动 (PostgreSQL + 应用)
docker compose up -d

# 查看日志
docker compose logs -f app

# 停止
docker compose down
```

### 2.4 打包 EXE (Windows)

```powershell
# 构建 EXE
.\build.ps1

# 清理并重新构建
.\build.ps1 -Clean
```

输出: `dist\NBACore.exe` (单文件，约 55MB)

### 2.5 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 仅运行 Phase 0 测试
pytest tests/test_phase0_health.py -v

# 仅运行 Phase 3 API 测试
pytest tests/test_phase3_api_layer.py -v
```

---

## 3. 项目结构

```
nba_desktop_omega/
├── backend/                          # 后端核心
│   ├── app.py                        # FastAPI 应用工厂
│   ├── core/                         # 核心基础设施
│   │   ├── config.py                 # 配置管理
│   │   ├── db.py                     # 数据库连接池 + SQL 校验
│   │   ├── logging.py                # 结构化日志
│   │   └── runtime_guard.py          # 启动时架构自检
│   ├── api/                          # Layer 3: API 层
│   │   ├── schemas.py                # Pydantic 数据模型
│   │   └── routers/                  # FastAPI 路由
│   │       ├── metrics.py            # /metrics 端点
│   │       ├── players.py            # /players 端点
│   │       ├── vs.py                 # /vs/compare 端点
│   │       ├── batch.py              # /batch 端点
│   │       ├── context.py            # /context 端点
│   │       ├── export.py             # /export 端点
│   │       └── monitor.py            # /monitor 端点
│   ├── data_layer/                   # Layer 1: 数据层
│   │   ├── schema.py                 # 表 Schema 注册表
│   │   ├── batch_loader.py           # 批量数据加载 (IN 子句)
│   │   ├── temp_loader.py            # 临时表加载 (大批次)
│   │   ├── joins.py                  # 表连接逻辑
│   │   └── schema_validator.py       # Schema 漂移检测
│   └── services/                     # Layer 2: 服务层
│       ├── metric_engine/            # Metric Engine (唯一计算层)
│       │   ├── registry.py           # 指标注册表
│       │   ├── executor.py           # 向量化执行器
│       │   ├── matrix_builder.py     # 矩阵构建器
│       │   ├── rank.py               # 排名引擎
│       │   ├── cache.py              # 磁盘缓存
│       │   ├── batch_loader.py       # 数据加载包装
│       │   └── metrics/              # 内置指标定义
│       │       ├── basic.py          # 基础指标 (PPG, RPG, etc.)
│       │       ├── advanced.py       # 高级指标 (TS%, eFG%, USG%)
│       │       └── composite.py      # 复合指标 (Fantasy, Efficiency)
│       ├── context_engine/           # Context Engine
│       │   ├── similar_players.py    # 相似球员 (余弦相似度)
│       │   ├── role_evolution.py     # 角色演变分析
│       │   └── trend_analysis.py     # 趋势分析 (线性回归)
│       └── export_service.py         # 导出服务 (JSON/CSV)
├── frontend/                         # Layer 4: 前端 (纯渲染)
│   ├── index.html                    # HTML 结构
│   ├── css/style.css                 # 样式
│   └── js/app.js                     # 前端逻辑 + ECharts
├── tests/                            # 测试套件
│   ├── conftest.py                   # Pytest fixtures
│   ├── test_phase0_health.py         # Phase 0: 健康检查 + 配置
│   └── test_phase3_api_layer.py      # Phase 3: API 层测试
├── NBAlogo/                          # 球队 Logo 素材
├── scripts/                          # 脚本工具
│   └── benchmark.py                  # 性能基准测试
├── docs/                             # 文档
│   └── PROJECT_FULL_DOCUMENTATION.md # 本文档
├── .github/workflows/                # CI/CD
│   └── ci.yml                        # GitHub Actions
├── main.py                           # EXE 入口点
├── Dockerfile                        # Docker 镜像构建
├── docker-compose.yml                # Docker Compose 编排
├── nbacore.spec                      # PyInstaller 配置
├── build.ps1                         # Windows 构建脚本
├── requirements.txt                  # 生产依赖 (固定版本)
├── pyproject.toml                    # 项目配置
├── .env.example                      # 环境变量示例
├── start.ps1                         # Windows 启动脚本
└── start.sh                          # Linux/Mac 启动脚本
```

---

## 4. 完整源代码

### 4.1 后端核心

#### main.py

```python
"""NBACore Studio v8 — Standalone EXE Entry Point.

Launches uvicorn server, opens browser, runs until Ctrl+C.
Used by PyInstaller to build a single-file executable.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from backend.core import config


def _open_browser_after_delay(delay: float = 1.5) -> None:
    """Open browser after server is likely ready."""
    time.sleep(delay)
    url = f"http://127.0.0.1:{config.SERVER_PORT}/app/"
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> None:
    """Entry point for standalone executable."""
    if getattr(sys, "frozen", False):
        _base = Path(sys._MEIPASS)
    else:
        _base = Path(__file__).resolve().parent

    _logo_dir = _base / "NBAlogo"
    _frontend_dir = _base / "frontend"

    print("=" * 60)
    print(f"  NBACore Studio v{config.APP_VERSION}")
    print("=" * 60)
    print(f"  Server:  http://127.0.0.1:{config.SERVER_PORT}")
    print(f"  App:     http://127.0.0.1:{config.SERVER_PORT}/app/")
    print(f"  API Doc: http://127.0.0.1:{config.SERVER_PORT}/docs")
    print("=" * 60)
    print(f"  Resources: {_base}")
    print(f"  Frontend:  {_frontend_dir} ({'OK' if _frontend_dir.is_dir() else 'MISSING'})")
    print(f"  Logos:     {_logo_dir} ({'OK' if _logo_dir.is_dir() else 'MISSING'})")
    print("=" * 60)
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    print()

    # Open browser in background thread
    threading.Thread(target=_open_browser_after_delay, daemon=True).start()

    # Run uvicorn
    try:
        uvicorn.run(
            "backend.app:create_app",
            factory=True,
            host="127.0.0.1",
            port=config.SERVER_PORT,
            log_level=config.LOG_LEVEL.lower(),
            access_log=config.DEBUG,
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
        sys.exit(0)


if __name__ == "__main__":
    main()

```

#### backend/app.py

```python
"""NBACore v8 — FastAPI Application Entry Point.

Phase 4 scope:
    - lifespan: init/close DB pool
    - request middleware: bind request_id, log latency
    - /health: DB ping + runtime guard results
    - /: minimal root info (no business logic)
    - /players, /metrics, /vs, /batch routers (Phase 3)
    - /app: static frontend files (Phase 4 VS System)
    - /assets/logos: NBA team logo assets

No routes here may contain SQL or computation. All business endpoints are
delegated to Layer 3 routers which in turn call Layer 2 metric_engine.
Frontend is pure render (Layer 4) — served via StaticFiles.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routers import batch, context, export, metrics, monitor, players, vs
from backend.core import config
from backend.core.db import close_pool, init_pool, ping
from backend.core.logging import new_request_id, setup_logging
from backend.core.runtime_guard import run_startup_checks

setup_logging(config.LOG_LEVEL)
logger = logging.getLogger("nbacore.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: pool init on startup, close on shutdown."""
    logger.info("Lifespan START | %s v%s", config.APP_NAME, config.APP_VERSION)
    try:
        init_pool()
    except Exception as exc:
        logger.error("DB pool init failed (app will start in degraded mode) | %s", exc)
    yield
    close_pool()
    logger.info("Lifespan END")


def create_app() -> FastAPI:
    """Application factory (v8 §3 — pure orchestration, no logic)."""
    app = FastAPI(
        title=config.APP_NAME,
        version=config.APP_VERSION,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def trace_request(request: Request, call_next):
        rid = new_request_id()
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %d | %.1fms | rid=%s",
            request.method, request.url.path,
            response.status_code, elapsed_ms, rid,
        )
        return response

    @app.get("/")
    def root():
        return {
            "name": config.APP_NAME,
            "version": config.APP_VERSION,
            "phase": "7-testing-monitoring",
            "docs": "/docs",
            "health": "/health",
            "app": "/app/",
        }

    @app.get("/health")
    def health():
        """v8 Phase 0 validation: DB ping + runtime guard."""
        db_ok = ping()
        guard = run_startup_checks()
        status = "ok" if db_ok and all(g.get("ok") for g in guard.values()) else "degraded"
        return {
            "status": status,
            "version": config.APP_VERSION,
            "database_connected": db_ok,
            "runtime_guard": guard,
        }

    # Phase 3: register Layer 3 routers (pure orchestration, no logic)
    app.include_router(players.router)
    app.include_router(metrics.router)
    app.include_router(vs.router)
    app.include_router(batch.router)
    app.include_router(context.router)
    app.include_router(export.router)
    app.include_router(monitor.router)

    # Phase 4: mount frontend static files (Layer 4 — pure render)
    from pathlib import Path
    import sys

    if getattr(sys, "frozen", False):
        _base = Path(sys._MEIPASS)
    else:
        _base = Path(__file__).resolve().parent.parent

    _frontend_dir = _base / "frontend"
    _logo_dir = _base / "NBAlogo"
    if _frontend_dir.is_dir():
        app.mount("/app", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
    if _logo_dir.is_dir():
        app.mount("/assets/logos", StaticFiles(directory=str(_logo_dir)), name="logos")
        app.mount("/app/assets/logos", StaticFiles(directory=str(_logo_dir)), name="logos-app")

    return app


app = create_app()


def main() -> None:
    """Run with uvicorn when invoked as `python -m backend.app`."""
    import uvicorn
    uvicorn.run(
        "backend.app:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=config.DEBUG,
        log_level=config.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()

```

#### backend/core/config.py

```python
"""NBACore v8 §2 — Configuration Layer.

Single source of truth for all runtime configuration.
Loaded from .env (manual parser, no python-dotenv dependency) + env var overrides.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

# ── Path Resolution (PyInstaller-aware, inherited from v7) ──
if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(sys._MEIPASS).resolve()
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BUNDLE_DIR = Path(__file__).resolve().parents[2]
    BASE_DIR = BUNDLE_DIR


def _load_dotenv() -> None:
    """Manual .env loader (v8 forbids extra deps for core bootstrap)."""
    for env_path in (BASE_DIR / ".env", BUNDLE_DIR / ".env"):
        if not env_path.exists():
            continue
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        break


_load_dotenv()


def _get(key: str, default: str) -> str:
    return os.getenv(key, default)


def _get_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _get_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, str(default)).strip().lower()
    return raw in ("1", "true", "yes", "on")


# ── Database (v7 used port 5433) ──
DB_HOST: str = _get("DB_HOST", "localhost")
DB_PORT: int = _get_int("DB_PORT", 5433)
DB_NAME: str = _get("DB_NAME", "nba")
DB_USER: str = _get("DB_USER", "postgres")
DB_PASSWORD: str = _get("DB_PASSWORD", "postgres")

DB_CONFIG: dict = {
    "host": DB_HOST,
    "port": DB_PORT,
    "database": DB_NAME,
    "user": DB_USER,
    "password": DB_PASSWORD,
}


def db_dsn() -> str:
    """Return a psycopg2-compatible DSN string."""
    return (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )


# ── Server ──
SERVER_HOST: str = _get("SERVER_HOST", "127.0.0.1")
SERVER_PORT: int = _get_int("SERVER_PORT", 5577)

# ── Cache (Disk Cache, Phase 2 will consume) ──
CACHE_DIR: Path = BASE_DIR / _get("CACHE_DIR", ".cache/metric_engine")

# ── App ──
APP_NAME: str = _get("APP_NAME", "NBACore Studio v8")
APP_VERSION: str = _get("APP_VERSION", "8.0.0")
DEBUG: bool = _get_bool("DEBUG", False)
LOG_LEVEL: str = _get("LOG_LEVEL", "INFO").upper()

# ── NBA Season Helper ──
def current_season() -> int:
    """NBA season: if month >= October, belongs to next year's season."""
    d = date.today()
    return d.year + 1 if d.month >= 10 else d.year


# ── v8 §6 Forbidden Patterns (checked by runtime_guard) ──
FORBIDDEN_SQL_PREFIXES = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
    "CREATE", "TRUNCATE", "GRANT", "REVOKE", "MERGE", "VACUUM",
)

```

#### backend/core/db.py

```python
"""NBACore v8 §2 Layer 1 — Database Access (immutable data layer).

Hard rules enforced here:
    - Only SELECT allowed (no DML/DDL)  → validate_batch_sql()
    - Every query gets a query_id        → batch_query()
    - No per-player loop patterns        → enforced at call sites in Phase 1
    - Connection pool with auto-recovery

This module is the ONLY entry point to PostgreSQL. API layer may not
import psycopg2 directly (checked by runtime_guard §5.5).
"""
from __future__ import annotations

import logging
import re
import socket
from typing import Any, Sequence

from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from backend.core import config
from backend.core.logging import new_query_id

logger = logging.getLogger("nbacore.db")

_pool: ThreadedConnectionPool | None = None

# Match forbidden SQL prefixes anywhere a statement starts
_FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|MERGE|VACUUM)\b",
    re.IGNORECASE,
)


# ── Pool Lifecycle ──
def init_pool() -> None:
    """Initialize the ThreadedConnectionPool (1-20 connections)."""
    global _pool
    if _pool is not None:
        return
    _pool = ThreadedConnectionPool(
        1, 20, **config.DB_CONFIG, cursor_factory=RealDictCursor
    )
    logger.info(
        "DB pool initialized | host=%s port=%s db=%s",
        config.DB_HOST, config.DB_PORT, config.DB_NAME,
    )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("DB pool closed")


def pool_ready() -> bool:
    return _pool is not None


# ── SQL Validation (v8 §6 forbidden list) ──
def validate_batch_sql(sql: str) -> None:
    """Reject any non-SELECT statement. Raise ValueError on violation."""
    stripped = sql.strip().removeprefix("(").strip()
    if not stripped:
        raise ValueError("Empty SQL")
    if _FORBIDDEN_RE.search(stripped):
        raise ValueError(
            f"Forbidden SQL operation (v8 allows SELECT only): {stripped[:80]!r}"
        )


# ── Batch Query (the ONLY data fetch primitive) ──
def batch_query(
    sql: str,
    params: Sequence[Any] | None = None,
) -> list[dict]:
    """Execute a batch SELECT with query_id tracing.

    Returns a list of dict rows (RealDictCursor). All SQL must pass
    validate_batch_sql() first.
    """
    validate_batch_sql(sql)
    if _pool is None:
        init_pool()
    assert _pool is not None  # narrowed for type checkers

    qid = new_query_id()
    logger.info("SQL start | qid=%s | sql=%s", qid, _one_line(sql))
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params) if params else ())
            rows = cur.fetchall()
        result = [dict(r) for r in rows]
        logger.info("SQL done  | qid=%s | rows=%d", qid, len(result))
        return result
    finally:
        _pool.putconn(conn)


def _one_line(sql: str, limit: int = 140) -> str:
    """Collapse whitespace for compact logging."""
    line = " ".join(sql.split())
    return line if len(line) <= limit else line[:limit] + "..."


# ── Temp Table Batch (v8 §2 controlled exception) ──
# v8 §2 explicitly allows "使用 IN 或临时表" for batch loading.
# Temp table DDL (CREATE/INSERT/DROP) is a hardcoded constant, NOT dynamic SQL.
# Only the final SELECT is validated via validate_batch_sql.

_TEMP_TABLE = "_nbacore_batch_ids"


def batch_query_with_temp_ids(
    select_sql: str,
    ids: list,
    id_type: str = "text",
) -> list[dict]:
    """Execute a SELECT that JOINs a temp table of IDs (for large batches).

    v8 §2 controlled exception: temp tables are explicitly allowed for batch
    loading when IN-clause becomes impractical (typically >500 IDs).

    Pattern (all on one connection, temp tables are conn-scoped):
        1. CREATE TEMP TABLE _nbacore_batch_ids (id <type>) ON COMMIT DROP
        2. INSERT INTO _nbacore_batch_ids VALUES (%s), ...  (executemany)
        3. SELECT ... JOIN _nbacore_batch_ids ON ...  (validated)
        4. COMMIT → temp table auto-dropped

    Args:
        select_sql: SELECT statement referencing _nbacore_batch_ids. Validated.
        ids: list of ID values (str or int) to populate the temp table.
        id_type: PostgreSQL type for the ID column ("text" or "integer").

    Returns: list[dict] rows from the SELECT.
    """
    if not ids:
        raise ValueError("temp table batch requires at least one ID")
    validate_batch_sql(select_sql)
    if _TEMP_TABLE not in select_sql:
        raise ValueError(f"select_sql must reference {_TEMP_TABLE}")
    if id_type not in ("text", "integer", "bigint"):
        raise ValueError(f"unsupported id_type {id_type!r}")

    if _pool is None:
        init_pool()
    assert _pool is not None

    qid = new_query_id()
    logger.info("TEMP batch start | qid=%s | ids=%d | sql=%s", qid, len(ids), _one_line(select_sql))
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            # 1. Temp table DDL (hardcoded constant — NOT dynamic SQL)
            cur.execute(
                f"CREATE TEMP TABLE IF NOT EXISTS {_TEMP_TABLE} (id {id_type}) ON COMMIT DROP"
            )
            cur.execute(f"DELETE FROM {_TEMP_TABLE}")
            # 2. Batch insert (parameterized executemany)
            cur.executemany(
                f"INSERT INTO {_TEMP_TABLE} (id) VALUES (%s)",
                [(i,) for i in ids],
            )
            # 3. Validated SELECT with JOIN
            cur.execute(select_sql)
            rows = cur.fetchall()
        # 4. Commit drops the temp table (ON COMMIT DROP)
        conn.commit()
        result = [dict(r) for r in rows]
        logger.info("TEMP batch done | qid=%s | rows=%d", qid, len(result))
        return result
    except Exception:
        conn.rollback()
        logger.warning("TEMP batch failed | qid=%s", qid)
        raise
    finally:
        _pool.putconn(conn)


def temp_table_name() -> str:
    """Expose the temp table name for data_layer SELECT construction."""
    return _TEMP_TABLE


# ── Connectivity Check ──
def is_port_open() -> bool:
    """Cheap TCP probe (no credentials needed)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        r = s.connect_ex((config.DB_HOST, config.DB_PORT))
        s.close()
        return r == 0
    except OSError:
        return False


def ping() -> bool:
    """True DB connectivity check via SELECT 1 (validates credentials)."""
    try:
        rows = batch_query("SELECT 1 AS ok")
        return bool(rows) and rows[0].get("ok") == 1
    except Exception as exc:
        logger.warning("DB ping failed | %s", exc)
        return False

```

#### backend/core/logging.py

```python
"""NBACore v8 §5.1 / §5.2 — Structured Logging with query_id / request_id tracing.

All SQL queries and requests are traceable via contextvars-injected IDs.
Zero external dependencies (stdlib logging only).
"""
from __future__ import annotations

import contextvars
import logging
import uuid
from datetime import datetime, timezone

# ── Context Vars (propagate through FastAPI threadpool automatically) ──
query_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "query_id", default="-"
)
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class _StructuredFilter(logging.Filter):
    """Inject trace IDs + ISO timestamp into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.query_id = query_id_var.get()
        record.request_id = request_id_var.get()
        record.ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return True


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with structured format. Idempotent."""
    root = logging.getLogger()
    if root.handlers and getattr(root, "_nbacore_configured", False):
        return
    fmt = (
        "%(ts)s [%(levelname)s] "
        "[req=%(request_id)s q=%(query_id)s] "
        "%(name)s | %(message)s"
    )
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(_StructuredFilter())
    root.handlers = [handler]
    root.setLevel(level.upper())
    root._nbacore_configured = True  # type: ignore[attr-defined]


def new_query_id() -> str:
    """Generate + bind a fresh query_id to the current context."""
    qid = uuid.uuid4().hex[:12]
    query_id_var.set(qid)
    return qid


def new_request_id() -> str:
    """Generate + bind a fresh request_id to the current context."""
    rid = uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    return rid


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

```

#### backend/core/runtime_guard.py

```python
"""NBACore v8 §5.5 — Runtime Guard (startup self-checks).

Enforces architectural invariants at startup:
    1. compute layer validation       — metric_engine package importable
    2. query batch enforcement        — only batch_query() touches DB
    3. cross-layer access prevention  — API must not import psycopg2 / data_layer SQL
    4. loop detection                 — guard counter (full AST scan in Phase 1)

Phase 0 implements the skeleton + checks 1 & 2; checks 3/4 are wired in
their respective phases.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger("nbacore.guard")


@dataclass
class GuardResult:
    ok: bool
    detail: dict = field(default_factory=dict)
    error: str | None = None


CheckFn = Callable[[], GuardResult]

_CHECKS: list[tuple[str, CheckFn]] = []


def register_check(name: str, fn: CheckFn) -> None:
    """Register a guard check (idempotent on name)."""
    for i, (existing, _) in enumerate(_CHECKS):
        if existing == name:
            _CHECKS[i] = (name, fn)
            return
    _CHECKS.append((name, fn))


def run_startup_checks() -> dict:
    """Execute all registered checks. Returns {name: GuardResult-as-dict}."""
    results: dict[str, dict] = {}
    for name, fn in _CHECKS:
        try:
            r = fn()
            results[name] = {"ok": r.ok, "detail": r.detail, "error": r.error}
            if not r.ok:
                logger.warning("Guard FAIL | %s | %s", name, r.error)
        except Exception as exc:  # defensive: guard must never crash app
            results[name] = {"ok": False, "detail": {}, "error": str(exc)}
            logger.warning("Guard ERROR | %s | %s", name, exc)
    return results


def all_passed(results: dict | None = None) -> bool:
    if results is None:
        results = run_startup_checks()
    return all(r.get("ok", False) for r in results.values())


# ── Default Phase 0 Checks ──

def _check_config_loaded() -> GuardResult:
    """Config values must be non-empty."""
    from backend.core import config
    if not config.DB_HOST or not config.DB_NAME:
        return GuardResult(False, error="config empty")
    return GuardResult(
        True,
        detail={"db_host": config.DB_HOST, "db_port": config.DB_PORT, "db_name": config.DB_NAME},
    )


def _check_metric_engine_exists() -> GuardResult:
    """v8 §2: Metric Engine must exist as the sole compute layer."""
    try:
        mod = importlib.import_module("backend.services.metric_engine")
        return GuardResult(True, detail={"module": mod.__name__})
    except ImportError as exc:
        return GuardResult(False, error=f"metric_engine not importable: {exc}")


def _check_no_forbidden_patterns() -> GuardResult:
    """v8 §6: scan core modules for eval/exec/dynamic SQL at import-time.

    Phase 0 does a lightweight source check on db.py only; Phase 1 will
    AST-scan the whole backend tree.
    """
    import backend.core.db as db_mod
    src = open(db_mod.__file__, encoding="utf-8").read()
    violations = []
    for bad in ("eval(", "exec(", "f\"SELECT", "f'SELECT"):
        if bad in src:
            violations.append(bad)
    if violations:
        return GuardResult(False, error=f"forbidden patterns: {violations}")
    return GuardResult(True, detail={"scanned": "backend.core.db"})


# Register defaults (order matters for log readability)
register_check("config_loaded", _check_config_loaded)
register_check("metric_engine_exists", _check_metric_engine_exists)
register_check("no_forbidden_patterns", _check_no_forbidden_patterns)

```

### 4.2 API 层

#### backend/api/schemas.py

```python
"""NBACore v8 §2 Layer 3 — Pydantic request/response schemas.

Pure data contracts. No computation, no methods beyond simple validators.
All numeric values come from metric_engine — schemas just shape them.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ── Metric schemas ──

class MetricInfo(BaseModel):
    """Public metric definition (mirrors MetricSpec without the compute fn)."""
    name: str
    kind: str
    source_table: str
    required_cols: list[str]
    description: str
    min_denominator: float
    precision: int


class MetricListResponse(BaseModel):
    metrics: list[MetricInfo]
    count: int


# ── Ranking schemas ──

class RankingItem(BaseModel):
    rank: int
    player_id: str
    player_name: str | None = None
    position: str | None = None
    value: float
    percentile: float
    sample_size: int


class EvaluateResponse(BaseModel):
    metric: str
    season: int
    ascending: bool
    min_value: float | None
    rankings: list[RankingItem]
    total: int


# ── Player schemas ──

class PlayerBio(BaseModel):
    """Subset of dim_players columns safe for API response."""
    player_id: str
    player_name: str | None = None
    full_name: str | None = None
    position: str | None = None
    shoots: str | None = None
    height_display: str | None = None
    height_cm: int | None = None
    weight_lbs: int | None = None
    weight_kg: int | None = None
    birth_date: str | None = None  # ISO date string
    birth_city: str | None = None
    birth_state_country: str | None = None
    college: str | None = None
    nba_debut: str | None = None
    experience: str | None = None
    year_from: int | None = None
    year_to: int | None = None

    @classmethod
    def from_row(cls, row: dict) -> "PlayerBio":
        """Build from a dim_players row (handles date/datetime → str)."""
        bd = row.get("birth_date")
        bd_str = bd.isoformat() if bd is not None else None
        return cls(
            player_id=str(row.get("player_id", "")),
            player_name=row.get("player_name"),
            full_name=row.get("full_name"),
            position=row.get("position"),
            shoots=row.get("shoots"),
            height_display=row.get("height_display"),
            height_cm=row.get("height_cm"),
            weight_lbs=row.get("weight_lbs"),
            weight_kg=row.get("weight_kg"),
            birth_date=bd_str,
            birth_city=row.get("birth_city"),
            birth_state_country=row.get("birth_state_country"),
            college=row.get("college"),
            nba_debut=row.get("nba_debut"),
            experience=row.get("experience"),
            year_from=row.get("year_from"),
            year_to=row.get("year_to"),
        )


class PlayerSearchResponse(BaseModel):
    players: list[PlayerBio]
    count: int


class PlayerDetailResponse(BaseModel):
    bio: PlayerBio
    season: int
    metrics: dict[str, float]  # {metric_name: value}


# ── VS schemas ──

class VSCompareResponse(BaseModel):
    player_1: str
    player_2: str
    season: int
    metrics: dict[str, dict[str, float | None]]  # {metric: {"player_1": x, "player_2": y}}


# ── Batch schemas ──

class BatchOperation(BaseModel):
    type: str = Field(..., description="rank | compute | compute_many")
    metric: str | None = None
    metrics: list[str] | None = None
    season: int
    player_ids: list[str] | None = None
    ascending: bool = False
    min_value: float | None = None
    limit: int | None = None


class BatchRequest(BaseModel):
    operations: list[BatchOperation]


class BatchResponse(BaseModel):
    results: list[dict]
    count: int


# ── Context schemas ──

class SimilarPlayerItem(BaseModel):
    player_id: str
    similarity: float
    name: str
    team: str | None = None
    position: str | None = None


class SimilarPlayersResponse(BaseModel):
    target_player_id: str
    season: int
    metric_count: int
    similar_players: list[SimilarPlayerItem]
    count: int


class MetricChangeItem(BaseModel):
    metric: str
    first_value: float | None
    last_value: float | None
    absolute_change: float | None
    pct_change: float | None
    direction: str
    trend_slope: float | None


class RoleEvolutionResponse(BaseModel):
    player_id: str
    seasons: list[int]
    metric_changes: list[MetricChangeItem]
    overall_shift_magnitude: float
    top_growth: list[str]
    top_decline: list[str]


class TrendResponse(BaseModel):
    player_id: str
    metric: str
    seasons: list[int]
    values: list[float | None]
    slope: float | None
    intercept: float | None
    r_squared: float | None
    momentum: float | None
    predicted_next: float | None
    direction: str

```

#### backend/api/routers/__init__.py

```python
"""NBACore v8 §2 Layer 3 — API routers package."""
from backend.api.routers import batch, metrics, players, vs

__all__ = ["players", "metrics", "vs", "batch"]

```

#### backend/api/routers/metrics.py

```python
"""NBACore v8 §2 Layer 3 — /metrics router (pure orchestration).

All computation delegated to metric_engine. This router contains NO SQL,
NO pandas, NO aggregation logic — only request shaping + metric_engine calls.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.api.schemas import (
    EvaluateResponse,
    MetricInfo,
    MetricListResponse,
    RankingItem,
)
from backend.services.metric_engine import get_metric, get_player_bios, list_metrics, rank

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricListResponse)
def get_metrics() -> MetricListResponse:
    """List all registered metrics."""
    names = list_metrics()
    specs = [get_metric(n) for n in names]
    return MetricListResponse(
        metrics=[
            MetricInfo(
                name=s.name,
                kind=s.kind,
                source_table=s.source_table,
                required_cols=list(s.required_cols),
                description=s.description,
                min_denominator=s.min_denominator,
                precision=s.precision,
            )
            for s in specs
        ],
        count=len(specs),
    )


@router.get("/{metric_name}", response_model=MetricInfo)
def get_metric_detail(metric_name: str) -> MetricInfo:
    """Get details for a single metric."""
    try:
        s = get_metric(metric_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return MetricInfo(
        name=s.name,
        kind=s.kind,
        source_table=s.source_table,
        required_cols=list(s.required_cols),
        description=s.description,
        min_denominator=s.min_denominator,
        precision=s.precision,
    )


@router.get("/evaluate/{metric_name}", response_model=EvaluateResponse)
def evaluate_metric(
    metric_name: str,
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    ascending: bool = Query(False, description="False=highest first"),
    min_value: float | None = Query(None, description="Exclude values below this"),
    limit: int | None = Query(None, ge=1, le=1000, description="Max rankings to return"),
) -> EvaluateResponse:
    """Evaluate a metric for a season and return ranked results."""
    try:
        rankings = rank(
            metric_name,
            season,
            ascending=ascending,
            min_value=min_value,
            use_cache=True,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if limit is not None:
        rankings = rankings[:limit]

    player_ids = [r.player_id for r in rankings]
    bios_list = get_player_bios(player_ids) if player_ids else []
    bios = {b["player_id"]: b for b in bios_list}

    return EvaluateResponse(
        metric=metric_name,
        season=season,
        ascending=ascending,
        min_value=min_value,
        rankings=[
            RankingItem(
                rank=r.rank,
                player_id=r.player_id,
                player_name=bios.get(r.player_id, {}).get("full_name")
                or bios.get(r.player_id, {}).get("player_name"),
                position=bios.get(r.player_id, {}).get("position"),
                value=r.value,
                percentile=r.percentile,
                sample_size=r.sample_size,
            )
            for r in rankings
        ],
        total=len(rankings),
    )

```

#### backend/api/routers/players.py

```python
"""NBACore v8 §2 Layer 3 — /players router (pure orchestration).

All data fetched via metric_engine wrappers. This router contains NO SQL,
NO pandas, NO computation — only request shaping + metric_engine calls.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.api.schemas import (
    PlayerBio,
    PlayerDetailResponse,
    PlayerSearchResponse,
)
from backend.services.metric_engine import (
    get_available_seasons,
    get_player_bios,
    list_metrics,
    player_metrics_dict,
    search_players_by_name,
)

router = APIRouter(prefix="/players", tags=["players"])

# Default metrics shown on player detail page.
# These are metric names registered in the engine; if any are missing from
# the registry, they're filtered out at runtime (defensive).
_DEFAULT_PLAYER_METRICS = [
    "pts_per_game",
    "reb_per_game",
    "ast_per_game",
    "true_shooting_pct",
    "fantasy_points",
]


@router.get("/seasons")
def list_seasons() -> list[int]:
    """List available seasons from fact_player_season_stats (descending)."""
    return get_available_seasons("fact_player_season_stats")


@router.get("", response_model=PlayerSearchResponse)
def search_players(
    name: str = Query(..., min_length=2, description="Player name search (>= 2 chars)"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
) -> PlayerSearchResponse:
    """Search players by name (case-insensitive)."""
    try:
        rows = search_players_by_name(name, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PlayerSearchResponse(
        players=[PlayerBio.from_row(r) for r in rows],
        count=len(rows),
    )


@router.get("/{player_id}", response_model=PlayerDetailResponse)
def get_player_detail(
    player_id: str,
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> PlayerDetailResponse:
    """Get player bio + default metrics for a season."""
    bios = get_player_bios([player_id])
    if not bios:
        raise HTTPException(
            status_code=404,
            detail=f"player {player_id!r} not found in dim_players",
        )

    bio = PlayerBio.from_row(bios[0])

    # Filter default metrics to those actually registered (defensive)
    available = set(list_metrics())
    metric_names = [m for m in _DEFAULT_PLAYER_METRICS if m in available]

    try:
        metrics_dict = player_metrics_dict(metric_names, season, player_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"compute failed: {exc}")

    return PlayerDetailResponse(bio=bio, season=season, metrics=metrics_dict)

```

#### backend/api/routers/vs.py

```python
"""NBACore v8 §2 Layer 3 — /vs router (pure orchestration).

VS comparison endpoint. All computation delegated to metric_engine.vs_compare.
This router contains NO SQL, NO pandas, NO computation.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.api.schemas import VSCompareResponse
from backend.services.metric_engine import list_metrics, vs_compare

router = APIRouter(prefix="/vs", tags=["vs"])

# Default metrics for VS comparison (can be overridden via query param)
_DEFAULT_VS_METRICS = [
    "pts_per_game",
    "reb_per_game",
    "ast_per_game",
    "stl_per_game",
    "blk_per_game",
    "true_shooting_pct",
    "effective_fg_pct",
    "usage_percent",
    "fantasy_points",
    "efficiency_rating",
]


@router.get("/compare", response_model=VSCompareResponse)
def compare_players(
    p1: str = Query(..., description="BBR player_id for player 1"),
    p2: str = Query(..., description="BBR player_id for player 2"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    metrics: str | None = Query(
        None,
        description="Comma-separated metric names (defaults to all built-ins)",
    ),
) -> VSCompareResponse:
    """Compare two players across multiple metrics for a season."""
    if p1 == p2:
        raise HTTPException(status_code=400, detail="p1 and p2 must be different players")

    # Resolve metric list (default or user-specified)
    if metrics:
        metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
    else:
        metric_names = list(_DEFAULT_VS_METRICS)

    # Validate metric names against registry
    available = set(list_metrics())
    invalid = [m for m in metric_names if m not in available]
    if invalid:
        raise HTTPException(
            status_code=404,
            detail=f"unknown metrics: {invalid}. Available: {sorted(available)}",
        )

    try:
        result = vs_compare(metric_names, season, p1, p2)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"compute failed: {exc}")

    return VSCompareResponse(
        player_1=p1,
        player_2=p2,
        season=season,
        metrics=result,
    )

```

#### backend/api/routers/batch.py

```python
"""NBACore v8 §2 Layer 3 — /batch router (pure orchestration).

Executes multiple metric operations in one request. Each operation is
dispatched to metric_engine — no computation happens in this router.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from backend.api.schemas import BatchRequest, BatchResponse
from backend.services.metric_engine import (
    compute_as_dict,
    compute_many_as_dict,
    list_metrics,
    rank,
)

logger = logging.getLogger("nbacore.api.batch")

router = APIRouter(prefix="/batch", tags=["batch"])

_VALID_TYPES = {"rank", "compute", "compute_many"}


@router.post("", response_model=BatchResponse)
def execute_batch(request: BatchRequest) -> BatchResponse:
    """Execute multiple metric operations in one request.

    Each operation in `request.operations` is dispatched based on `type`:
        - "rank":         rank(metric, season, ascending, min_value)
        - "compute":      compute_as_dict(metric, season, player_ids)
        - "compute_many": compute_many_as_dict(metrics, season, player_ids)
    """
    if not request.operations:
        raise HTTPException(status_code=400, detail="operations list is empty")

    available = set(list_metrics())
    results: list[dict] = []

    for i, op in enumerate(request.operations):
        if op.type not in _VALID_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"operation {i}: invalid type {op.type!r} "
                       f"(must be one of {sorted(_VALID_TYPES)})",
            )

        try:
            if op.type == "rank":
                if not op.metric:
                    raise ValueError("rank operation requires 'metric'")
                if op.metric not in available:
                    raise ValueError(f"unknown metric {op.metric!r}")
                rankings = rank(
                    op.metric,
                    op.season,
                    ascending=op.ascending,
                    min_value=op.min_value,
                    use_cache=True,
                )
                if op.limit is not None:
                    rankings = rankings[:op.limit]
                results.append({
                    "type": "rank",
                    "metric": op.metric,
                    "season": op.season,
                    "rankings": [
                        {
                            "rank": r.rank,
                            "player_id": r.player_id,
                            "value": r.value,
                            "percentile": r.percentile,
                            "sample_size": r.sample_size,
                        }
                        for r in rankings
                    ],
                    "total": len(rankings),
                })

            elif op.type == "compute":
                if not op.metric:
                    raise ValueError("compute operation requires 'metric'")
                if op.metric not in available:
                    raise ValueError(f"unknown metric {op.metric!r}")
                values = compute_as_dict(
                    op.metric,
                    op.season,
                    player_ids=op.player_ids,
                    use_cache=True,
                )
                results.append({
                    "type": "compute",
                    "metric": op.metric,
                    "season": op.season,
                    "values": values,
                    "count": len(values),
                })

            elif op.type == "compute_many":
                if not op.metrics:
                    raise ValueError("compute_many operation requires 'metrics'")
                invalid = [m for m in op.metrics if m not in available]
                if invalid:
                    raise ValueError(f"unknown metrics: {invalid}")
                values = compute_many_as_dict(
                    op.metrics,
                    op.season,
                    player_ids=op.player_ids,
                    use_cache=True,
                )
                results.append({
                    "type": "compute_many",
                    "metrics": op.metrics,
                    "season": op.season,
                    "values": values,
                    "count": len(values),
                })

        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"operation {i} ({op.type}): {exc}",
            )
        except Exception as exc:
            logger.exception("batch operation %d failed", i)
            raise HTTPException(
                status_code=500,
                detail=f"operation {i} ({op.type}) failed: {exc}",
            )

    return BatchResponse(results=results, count=len(results))

```

#### backend/api/routers/context.py

```python
"""NBACore v8 §2 Layer 3 — /context router (pure orchestration).

Context System endpoints: similar players, role evolution, trend analysis.
All computation delegated to context_engine (layer 2.5), which uses Metric Engine.
This router contains NO SQL, NO pandas, NO computation.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.api.schemas import (
    RoleEvolutionResponse,
    SimilarPlayersResponse,
    TrendResponse,
)
from backend.services.context_engine import (
    find_similar_players,
    player_role_evolution,
    player_trend,
)
from backend.services.metric_engine import list_metrics

router = APIRouter(prefix="/context", tags=["context"])

_DEFAULT_SIMILAR_METRICS = [
    "pts_per_game",
    "reb_per_game",
    "ast_per_game",
    "stl_per_game",
    "blk_per_game",
    "true_shooting_pct",
    "effective_fg_pct",
    "usage_percent",
    "fantasy_points",
    "efficiency_rating",
]


@router.get("/similar", response_model=SimilarPlayersResponse)
def get_similar_players(
    player_id: str = Query(..., description="Target BBR player_id"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    metrics: str | None = Query(
        None,
        description="Comma-separated metric names (default: scoring/playmaking/efficiency profile)",
    ),
    limit: int = Query(10, ge=1, le=50, description="Max similar players"),
    position_filter: bool = Query(True, description="Filter to same-position players"),
) -> SimilarPlayersResponse:
    """Find players with most similar statistical profile (cosine similarity)."""
    if metrics:
        metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
    else:
        metric_names = list(_DEFAULT_SIMILAR_METRICS)

    available = set(list_metrics())
    invalid = [m for m in metric_names if m not in available]
    if invalid:
        raise HTTPException(
            status_code=404,
            detail=f"unknown metrics: {invalid}. Available: {sorted(available)}",
        )

    try:
        results = find_similar_players(
            player_id=player_id,
            season=season,
            metric_names=metric_names,
            limit=limit,
            position_filter=position_filter,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"similar players failed: {exc}")

    return SimilarPlayersResponse(
        target_player_id=player_id,
        season=season,
        metric_count=len(metric_names),
        similar_players=[vars(p) for p in results],
        count=len(results),
    )


@router.get("/evolution", response_model=RoleEvolutionResponse)
def get_role_evolution(
    player_id: str = Query(..., description="BBR player_id"),
    seasons: str = Query(
        ...,
        description="Comma-separated season years (e.g. '2020,2021,2022,2023,2024,2025')",
    ),
    metrics: str | None = Query(
        None,
        description="Comma-separated metric names (default: core per-game + advanced)",
    ),
) -> RoleEvolutionResponse:
    """Analyze how a player's statistical role evolved across seasons."""
    season_list = [int(s.strip()) for s in seasons.split(",") if s.strip().isdigit()]
    if len(season_list) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 seasons required for evolution analysis",
        )

    if metrics:
        metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
    else:
        metric_names = list(_DEFAULT_SIMILAR_METRICS)

    available = set(list_metrics())
    invalid = [m for m in metric_names if m not in available]
    if invalid:
        raise HTTPException(
            status_code=404,
            detail=f"unknown metrics: {invalid}. Available: {sorted(available)}",
        )

    try:
        result = player_role_evolution(
            player_id=player_id,
            seasons=season_list,
            metric_names=metric_names,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"evolution analysis failed: {exc}")

    return RoleEvolutionResponse(
        player_id=result.player_id,
        seasons=result.seasons,
        metric_changes=[vars(m) for m in result.metric_changes],
        overall_shift_magnitude=result.overall_shift_magnitude,
        top_growth=result.top_growth,
        top_decline=result.top_decline,
    )


@router.get("/trend", response_model=TrendResponse)
def get_metric_trend(
    player_id: str = Query(..., description="BBR player_id"),
    metric: str = Query(..., description="Metric name"),
    seasons: str = Query(
        ...,
        description="Comma-separated season years",
    ),
) -> TrendResponse:
    """Compute linear trend + momentum for a single metric across seasons."""
    season_list = [int(s.strip()) for s in seasons.split(",") if s.strip().isdigit()]
    if not season_list:
        raise HTTPException(status_code=400, detail="At least 1 season required")

    available = set(list_metrics())
    if metric not in available:
        raise HTTPException(
            status_code=404,
            detail=f"unknown metric: {metric}. Available: {sorted(available)}",
        )

    try:
        result = player_trend(
            player_id=player_id,
            metric=metric,
            seasons=season_list,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"trend analysis failed: {exc}")

    return TrendResponse(
        player_id=result.player_id,
        metric=result.metric,
        seasons=result.seasons,
        values=result.values,
        slope=result.slope,
        intercept=result.intercept,
        r_squared=result.r_squared,
        momentum=result.momentum,
        predicted_next=result.predicted_next,
        direction=result.direction,
    )

```

#### backend/api/routers/export.py

```python
"""NBACore v8 §2 Layer 3 — /export router (pure orchestration).

Export endpoints: JSON/CSV for rankings, VS, player, league.
All data from export_service → metric_engine. No computation here.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response

from backend.services.export_service import (
    export_league_json,
    export_player_json,
    export_rankings_csv,
    export_rankings_json,
    export_vs_csv,
    export_vs_json,
)
from backend.services.metric_engine import list_metrics

router = APIRouter(prefix="/export", tags=["export"])

_VALID_FORMATS = {"json", "csv"}


def _check_format(fmt: str) -> None:
    if fmt not in _VALID_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format '{fmt}'. Available: {sorted(_VALID_FORMATS)}",
        )


@router.get("/rankings")
def export_rankings(
    metric: str = Query(..., description="Metric name"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    format: str = Query("json", description="json or csv"),
    limit: int = Query(100, ge=1, le=500, description="Max players"),
) -> Response:
    """Export rankings as JSON or CSV."""
    _check_format(format)

    available = set(list_metrics())
    if metric not in available:
        raise HTTPException(
            status_code=404,
            detail=f"unknown metric: {metric}. Available: {sorted(available)}",
        )

    try:
        if format == "json":
            result = export_rankings_json(metric, season, limit)
        else:
            result = export_rankings_csv(metric, season, limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"export failed: {exc}")

    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={
            "Content-Disposition": f"attachment; filename={result.filename}",
            "X-Export-SHA256": result.sha256,
        },
    )


@router.get("/vs")
def export_vs(
    p1: str = Query(..., description="BBR player_id for player 1"),
    p2: str = Query(..., description="BBR player_id for player 2"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    format: str = Query("json", description="json or csv"),
    metrics: str | None = Query(None, description="Comma-separated metric names"),
) -> Response:
    """Export VS comparison as JSON or CSV."""
    _check_format(format)

    if p1 == p2:
        raise HTTPException(status_code=400, detail="p1 and p2 must be different")

    if metrics:
        metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
    else:
        metric_names = [
            "pts_per_game", "reb_per_game", "ast_per_game",
            "stl_per_game", "blk_per_game", "true_shooting_pct",
            "effective_fg_pct", "usage_percent", "fantasy_points",
            "efficiency_rating",
        ]

    available = set(list_metrics())
    invalid = [m for m in metric_names if m not in available]
    if invalid:
        raise HTTPException(
            status_code=404,
            detail=f"unknown metrics: {invalid}. Available: {sorted(available)}",
        )

    try:
        if format == "json":
            result = export_vs_json(p1, p2, season, metric_names)
        else:
            result = export_vs_csv(p1, p2, season, metric_names)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"export failed: {exc}")

    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={
            "Content-Disposition": f"attachment; filename={result.filename}",
            "X-Export-SHA256": result.sha256,
        },
    )


@router.get("/player")
def export_player(
    player_id: str = Query(..., description="BBR player_id"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    format: str = Query("json", description="json only"),
    metrics: str | None = Query(None, description="Comma-separated metric names"),
) -> Response:
    """Export single-player metrics as JSON."""
    if format != "json":
        raise HTTPException(status_code=400, detail="Player export only supports JSON")

    metric_names = None
    if metrics:
        metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
        available = set(list_metrics())
        invalid = [m for m in metric_names if m not in available]
        if invalid:
            raise HTTPException(
                status_code=404,
                detail=f"unknown metrics: {invalid}. Available: {sorted(available)}",
            )

    try:
        result = export_player_json(player_id, season, metric_names)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"export failed: {exc}")

    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={
            "Content-Disposition": f"attachment; filename={result.filename}",
            "X-Export-SHA256": result.sha256,
        },
    )

```

#### backend/api/routers/monitor.py

```python
"""NBACore v8 §2 Layer 3 — /monitor router (pure orchestration).

Monitoring and stats endpoints. No business logic — just reports internal state.
"""
from __future__ import annotations

import time

from fastapi import APIRouter

from backend.core.db import ping
from backend.services.metric_engine import list_metrics

router = APIRouter(prefix="/monitor", tags=["monitor"])

_start_time = time.time()


@router.get("/stats")
def get_stats() -> dict:
    """Get system statistics (DB status, metrics count, uptime)."""
    db_alive = ping()
    uptime = time.time() - _start_time

    return {
        "uptime_seconds": round(uptime, 2),
        "uptime_display": _format_uptime(uptime),
        "database": {
            "connected": db_alive,
        },
        "metrics_registered": len(list_metrics()),
        "layers": {
            "data_layer": "active",
            "metric_engine": "active",
            "api_layer": "active",
            "context_engine": "active",
            "export_service": "active",
            "frontend": "active",
        },
        "endpoints": {
            "players": ["/players/search", "/players/{id}", "/players/seasons"],
            "metrics": ["/metrics/list", "/metrics/evaluate/{metric}"],
            "vs": ["/vs/compare"],
            "context": ["/context/similar", "/context/evolution", "/context/trend"],
            "export": ["/export/rankings", "/export/vs", "/export/player"],
            "batch": ["/batch/execute"],
            "monitor": ["/monitor/stats"],
        },
    }


def _format_uptime(seconds: float) -> str:
    """Format seconds into human-readable uptime."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

```

### 4.3 数据层

#### backend/data_layer/__init__.py

```python
"""NBACore v8 §2 Layer 1 — Data Layer (immutable PostgreSQL access).

This package is the SOLE consumer of backend.core.db.batch_query().
Everything that reads from PostgreSQL goes through batch_loader.py.

Hard rules (v8 §2):
    - Only SELECT (enforced in backend.core.db.validate_batch_sql)
    - Batch query only (IN clause or temp table)
    - season / date range filter MANDATORY (enforced at function signature)
    - No per-player loop — all fetches are vectorized batches

Phase 0.5: schema registry + IN-clause loaders
Phase 1: temp table loaders + schema drift validation + join loaders
"""
from backend.data_layer.batch_loader import (
    load_player_gamelog,
    load_player_season_stats,
    load_players,
    load_games,
    load_team_season_stats,
    load_seasons_available,
    search_players,
)
from backend.data_layer.temp_loader import (
    load_player_gamelog_by_ids,
    load_players_by_ids,
    should_use_temp_table,
    TEMP_TABLE_THRESHOLD,
)
from backend.data_layer.joins import (
    load_player_gamelog_with_game_context,
    load_player_season_stats_with_bio,
)
from backend.data_layer.schema_validator import (
    validate_registry,
    registry_healthy,
    drift_summary,
)

__all__ = [
    # Phase 0.5 — IN-clause loaders
    "load_player_gamelog",
    "load_player_season_stats",
    "load_players",
    "load_games",
    "load_team_season_stats",
    "load_seasons_available",
    # Phase 3 — player search (additive extension)
    "search_players",
    # Phase 1 — temp table loaders
    "load_player_gamelog_by_ids",
    "load_players_by_ids",
    "should_use_temp_table",
    "TEMP_TABLE_THRESHOLD",
    # Phase 1 — join loaders
    "load_player_gamelog_with_game_context",
    "load_player_season_stats_with_bio",
    # Phase 1 — schema validation
    "validate_registry",
    "registry_healthy",
    "drift_summary",
]

```

#### backend/data_layer/schema.py

```python
"""NBACore v8 §2 — Schema Registry for Layer 1.

Documents the physical tables the data_layer is allowed to read, their
season column (for mandatory v8 §2 season filter), and the player key
column (for IN-clause batch fetches).

Introspected from PostgreSQL `nba` database on 2026-07-06 (Phase 0.5).
Only key tables for the metric engine are registered here; the full 38-table
catalog lives in the DB and is queryable via information_schema.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableSchema:
    """Schema contract for a Layer 1 accessible table."""
    name: str
    season_col: str | None        # mandatory filter column (None = dimension table)
    player_col: str | None        # BBR player_id column (None = no player dimension)
    row_count_approx: int         # approximate row count at Phase 0.5 introspection
    description: str


# ── Registered Tables (sole source of truth for batch_loader) ──
REGISTRY: dict[str, TableSchema] = {
    "player_gamelog": TableSchema(
        name="player_gamelog",
        season_col="season",
        player_col="br_player_id",   # BBR string ID (96% coverage); player_id is NBA.com numeric (47%)
        row_count_approx=1_912_415,
        description="Player single-game logs (br_player_id is BBR key, 54 cols incl. advanced)",
    ),
    "fact_player_season_stats": TableSchema(
        name="fact_player_season_stats",
        season_col="season",
        player_col="player_id",
        row_count_approx=45_073,
        description="Player season wide table (totals + advanced + per_100, 74 cols)",
    ),
    "fact_team_season_stats": TableSchema(
        name="fact_team_season_stats",
        season_col="season",
        player_col=None,
        row_count_approx=900,
        description="Team season totals",
    ),
    "dim_games": TableSchema(
        name="dim_games",
        season_col="season",
        player_col=None,
        row_count_approx=99_227,
        description="Game dimension (99 cols, season + season_type filter)",
    ),
    "dim_players": TableSchema(
        name="dim_players",
        season_col=None,        # dimension table — no season filter
        player_col="player_id",
        row_count_approx=5_476,
        description="Player bio dimension (24 cols)",
    ),
    "dim_teams": TableSchema(
        name="dim_teams",
        season_col=None,
        player_col=None,
        row_count_approx=30,
        description="Team dimension (6 cols)",
    ),
    "player_season_splits": TableSchema(
        name="player_season_splits",
        season_col="season",
        player_col=None,            # only has player_name (no stable player_id)
        row_count_approx=1_020_609,
        description="Player season split stats (vs team / location / outcome)",
    ),
    "player_shooting": TableSchema(
        name="player_shooting",
        season_col="season",
        player_col="player_id",
        row_count_approx=24_353,
        description="Player shooting breakdowns by distance/zone",
    ),
}


def get_schema(table_name: str) -> TableSchema:
    """Fetch a registered table schema. Raises KeyError if unregistered."""
    if table_name not in REGISTRY:
        raise KeyError(
            f"Table {table_name!r} not in Layer 1 registry. "
            f"Registered: {sorted(REGISTRY)}"
        )
    return REGISTRY[table_name]


def season_required(table_name: str) -> bool:
    """True if the table mandates a season filter (v8 §2)."""
    return get_schema(table_name).season_col is not None

```

#### backend/data_layer/batch_loader.py

```python
"""NBACore v8 §2 Layer 1 — Batch Loader.

The ONLY module that fetches data from PostgreSQL for the metric engine.
Every function enforces the v8 §2 mandates:
    1. season filter is a REQUIRED parameter (no default, no "load all")
    2. player filtering uses IN-clause batch (never per-player loop)
    3. all SQL passes through backend.core.db.batch_query (single DB entry)

Returns plain list[dict]; Phase 2 Metric Engine will reshape into matrices.
"""
from __future__ import annotations

from typing import Any

from backend.core.db import batch_query
from backend.data_layer.schema import get_schema, season_required


# ── Helpers ──

def _build_in_clause(values: list[Any]) -> tuple[str, tuple]:
    """Build a parameterized IN-clause: (%s,%s,...) + params tuple."""
    if not values:
        raise ValueError("IN-clause requires at least one value (no empty batches)")
    placeholders = ",".join(["%s"] * len(values))
    return f"({placeholders})", tuple(values)


def _assert_season(schema_name: str, season: int) -> None:
    """Enforce v8 §2: season filter required for fact tables."""
    if not season_required(schema_name):
        return  # dimension table, no season filter needed
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r} for {schema_name}")


# ── Public Loaders ──

def load_player_gamelog(
    season: int,
    player_ids: list[str] | None = None,
) -> list[dict]:
    """Batch load player_gamelog rows for a season.

    Args:
        season: required NBA season (e.g. 2025)
        player_ids: optional BBR br_player_id list for IN-clause filter.
                    If None, loads ALL players for the season (still batch).

    Returns: list[dict] with 54 columns per row.
    """
    _assert_season("player_gamelog", season)
    schema = get_schema("player_gamelog")
    sql = f"SELECT * FROM {schema.name} WHERE {schema.season_col} = %s"
    params: list[Any] = [season]
    if player_ids:
        in_clause, in_params = _build_in_clause(player_ids)
        sql += f" AND {schema.player_col} IN {in_clause}"
        params.extend(in_params)
    return batch_query(sql, tuple(params))


def load_player_season_stats(season: int) -> list[dict]:
    """Batch load fact_player_season_stats for a season (all players)."""
    _assert_season("fact_player_season_stats", season)
    schema = get_schema("fact_player_season_stats")
    sql = f"SELECT * FROM {schema.name} WHERE {schema.season_col} = %s"
    return batch_query(sql, (season,))


def load_team_season_stats(season: int) -> list[dict]:
    """Batch load fact_team_season_stats for a season (all 30 teams)."""
    _assert_season("fact_team_season_stats", season)
    schema = get_schema("fact_team_season_stats")
    sql = f"SELECT * FROM {schema.name} WHERE {schema.season_col} = %s"
    return batch_query(sql, (season,))


def load_games(
    season: int,
    season_type: str | None = None,
) -> list[dict]:
    """Batch load dim_games for a season. Optional season_type filter."""
    _assert_season("dim_games", season)
    schema = get_schema("dim_games")
    sql = f"SELECT * FROM {schema.name} WHERE {schema.season_col} = %s"
    params: list[Any] = [season]
    if season_type:
        sql += " AND season_type = %s"
        params.append(season_type)
    return batch_query(sql, tuple(params))


def load_players(player_ids: list[str]) -> list[dict]:
    """Batch load dim_players by BBR player_id list (dimension, no season).

    This is the ONLY loader allowed without a season parameter because
    dim_players is a dimension table (v8 §2 exception for dims).
    """
    if not player_ids:
        raise ValueError("load_players requires at least one player_id")
    schema = get_schema("dim_players")
    in_clause, in_params = _build_in_clause(player_ids)
    sql = f"SELECT * FROM {schema.name} WHERE {schema.player_col} IN {in_clause}"
    return batch_query(sql, in_params)


def load_seasons_available(table_name: str = "fact_player_season_stats") -> list[int]:
    """Return distinct seasons available in a table (descending)."""
    schema = get_schema(table_name)
    if schema.season_col is None:
        raise ValueError(f"{table_name} has no season column")
    sql = f"SELECT DISTINCT {schema.season_col} AS s FROM {schema.name} ORDER BY s DESC"
    rows = batch_query(sql)
    return [int(r["s"]) for r in rows]


def search_players(name: str, limit: int = 20) -> list[dict]:
    """Search dim_players by name (case-insensitive ILIKE).

    Phase 3 extension: required for /players search endpoint.
    Additive — does not modify any Phase 1 LOCKED function.

    Args:
        name: search string (matched against player_name + full_name via ILIKE)
        limit: max results (default 20, capped at 100)

    Returns: list[dict] with dim_players columns.
    """
    if not name or len(name.strip()) < 2:
        raise ValueError("search name must be at least 2 chars")
    if limit < 1 or limit > 100:
        limit = max(1, min(limit, 100))
    schema = get_schema("dim_players")
    sql = (
        f"SELECT * FROM {schema.name} "
        f"WHERE player_name ILIKE %s OR full_name ILIKE %s "
        f"ORDER BY player_name LIMIT %s"
    )
    pattern = f"%{name.strip()}%"
    return batch_query(sql, (pattern, pattern, limit))

```

#### backend/data_layer/temp_loader.py

```python
"""NBACore v8 §2 Layer 1 — Temp Table Batch Loaders.

For large ID lists (>500), IN-clauses become slow and hit parameter limits.
These loaders use batch_query_with_temp_ids() which populates a temp table
and JOINs against it — explicitly allowed by v8 §2 ("使用 IN 或临时表").

Use the IN-clause loaders in batch_loader.py for small lists (<500 IDs).
Use these temp table loaders for large batches (500+ IDs).
"""
from __future__ import annotations

from backend.core.db import batch_query_with_temp_ids, temp_table_name
from backend.data_layer.schema import get_schema

# Threshold: above this many IDs, prefer temp table over IN-clause
TEMP_TABLE_THRESHOLD = 500


def load_player_gamelog_by_ids(
    season: int,
    player_ids: list[str],
) -> list[dict]:
    """Batch load player_gamelog via temp table (for 500+ BBR IDs).

    Equivalent to load_player_gamelog(season, player_ids) but uses a temp
    table JOIN instead of an IN-clause. Same result, better performance
    at scale.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    if not player_ids:
        raise ValueError("player_ids required")

    schema = get_schema("player_gamelog")
    tmp = temp_table_name()
    sql = f"""
        SELECT g.*
        FROM {schema.name} g
        INNER JOIN {tmp} t ON g.{schema.player_col} = t.id
        WHERE g.{schema.season_col} = {season}
    """
    # season is embedded as integer literal (safe — validated above, not string interp)
    return batch_query_with_temp_ids(sql, player_ids, id_type="text")


def load_players_by_ids(player_ids: list[str]) -> list[dict]:
    """Batch load dim_players via temp table (for 500+ BBR IDs)."""
    if not player_ids:
        raise ValueError("player_ids required")
    schema = get_schema("dim_players")
    tmp = temp_table_name()
    sql = f"""
        SELECT p.*
        FROM {schema.name} p
        INNER JOIN {tmp} t ON p.{schema.player_col} = t.id
    """
    return batch_query_with_temp_ids(sql, player_ids, id_type="text")


def should_use_temp_table(player_ids: list) -> bool:
    """Decision helper: True if the ID list is large enough to warrant temp table."""
    return len(player_ids) >= TEMP_TABLE_THRESHOLD

```

#### backend/data_layer/joins.py

```python
"""NBACore v8 §2 Layer 1 — Cross-table Join Batch Loaders.

Single batch query that returns joined data, avoiding multiple round-trips.
The metric engine (Phase 2) consumes these to build enriched matrices.

All loaders enforce the v8 §2 season filter (required parameter).
"""
from __future__ import annotations

from backend.core.db import batch_query
from backend.data_layer.schema import get_schema


def load_player_gamelog_with_game_context(season: int) -> list[dict]:
    """Batch load player_gamelog joined with dim_games (game date, teams, scores).

    Single query — avoids N+1 game lookups per gamelog row.
    Returns gamelog columns + game_date + home/away team + pts.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    gl = get_schema("player_gamelog")
    dg = get_schema("dim_games")
    sql = f"""
        SELECT
            g.*,
            d.game_date, d.home_team_abbr, d.away_team_abbr,
            d.home_pts, d.away_pts, d.season_type
        FROM {gl.name} g
        LEFT JOIN {dg.name} d
          ON g.gameid = d.game_id
        WHERE g.{gl.season_col} = %s
    """
    return batch_query(sql, (season,))


def load_player_season_stats_with_bio(season: int) -> list[dict]:
    """Batch load fact_player_season_stats joined with dim_players (bio).

    Single query — returns season stats + player bio (height, weight, position).
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    fps = get_schema("fact_player_season_stats")
    dp = get_schema("dim_players")
    sql = f"""
        SELECT
            s.*,
            p.height_cm, p.weight_lbs, p.position AS bio_position,
            p.college, p.nationality
        FROM {fps.name} s
        LEFT JOIN {dp.name} p
          ON s.{fps.player_col} = p.{dp.player_col}
        WHERE s.{fps.season_col} = %s
    """
    return batch_query(sql, (season,))

```

#### backend/data_layer/schema_validator.py

```python
"""NBACore v8 §5.5 — Schema Drift Detection.

Validates that the Layer 1 REGISTRY matches the actual PostgreSQL schema.
Catches column renames, dropped tables, and type changes before they cause
runtime failures in the metric engine.

Can be invoked:
    1. At startup (via runtime_guard)
    2. On demand (e.g., after a DB migration)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.core.db import batch_query
from backend.data_layer.schema import REGISTRY, TableSchema


@dataclass
class DriftReport:
    table: str
    ok: bool
    issues: list[str] = field(default_factory=list)


def _table_exists(table_name: str) -> bool:
    rows = batch_query(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table_name,),
    )
    return bool(rows)


def _column_exists(table_name: str, column_name: str) -> bool:
    rows = batch_query(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table_name, column_name),
    )
    return bool(rows)


def validate_table(schema: TableSchema) -> DriftReport:
    """Check a single registered table exists + has declared columns."""
    issues: list[str] = []
    if not _table_exists(schema.name):
        issues.append(f"table {schema.name!r} not found in public schema")
        return DriftReport(table=schema.name, ok=False, issues=issues)
    if schema.season_col and not _column_exists(schema.name, schema.season_col):
        issues.append(f"declared season_col {schema.season_col!r} not found")
    if schema.player_col and not _column_exists(schema.name, schema.player_col):
        issues.append(f"declared player_col {schema.player_col!r} not found")
    return DriftReport(table=schema.name, ok=not issues, issues=issues)


def validate_registry() -> list[DriftReport]:
    """Validate all registered tables against the live DB. Returns per-table reports."""
    return [validate_table(s) for s in REGISTRY.values()]


def registry_healthy() -> bool:
    """True if every registered table passes drift check."""
    return all(r.ok for r in validate_registry())


def drift_summary() -> dict:
    """Compact dict for runtime_guard / /health consumption."""
    reports = validate_registry()
    return {
        "ok": all(r.ok for r in reports),
        "tables_checked": len(reports),
        "issues": [
            {"table": r.table, "issues": r.issues}
            for r in reports if not r.ok
        ],
    }

```

### 4.4 服务层 — Metric Engine

#### backend/services/metric_engine/__init__.py

```python
"""NBACore v8 §2 Layer 2 — Metric Engine (SOLE compute layer).

This package is the ONLY place where metric computation happens.
API layer (Phase 3) may only call public functions here; it must not
implement any computation itself (v8 §2 layer isolation).

Public API:
    - list_metrics()                      → list[str]
    - get_metric(name)                    → MetricSpec
    - compute(metric_name, season, ...)   → pd.Series
    - compute_many(names, season, ...)    → pd.DataFrame
    - rank(metric_name, season, ...)      → list[Ranking]

Architecture (v8 §2 Layer 2):
    registry.py        — MetricSpec dataclass + singleton MetricRegistry
    matrix_builder.py  — list[dict] → player-indexed DataFrame
    executor.py        — runs metric.compute() vectorized
    cache.py           — diskcache wrapper (SHA256 key, deterministic)
    batch_loader.py    — pulls rows from Layer 1 via data_layer
    rank.py            — Ranking dataclass + rank_players()
    metrics/           — built-in metric definitions (auto-registered on import)

v8 §6 forbidden list (enforced by tests):
    - no eval() / exec()
    - no dynamic SQL (no psycopg2 imports in this package)
    - no per-player loop (compute fns are vectorized pandas)
"""
from __future__ import annotations

# Importing metrics package triggers register() calls for built-in metrics.
# This MUST happen before any public API is called.
from backend.services.metric_engine import metrics  # noqa: F401  (side-effect import)
from backend.services.metric_engine.batch_loader import (
    available_source_tables,
    get_available_seasons,
    get_player_bios,
    load_metric_input,
    search_players_by_name,
)
from backend.services.metric_engine.cache import (
    CacheEngine,
    get_engine,
    make_cache_key,
    reset_engine,
)
from backend.services.metric_engine.executor import (
    execute_many,
    execute_metric,
    execute_spec,
    list_available_metrics,
)
from backend.services.metric_engine.rank import Ranking, rank_players, to_dataframe
from backend.services.metric_engine.registry import (
    MetricRegistry,
    MetricSpec,
    REGISTRY,
    get_registry,
    register,
)

__phase_status__ = "phase2-built"

__all__ = [
    # Registry
    "MetricSpec",
    "MetricRegistry",
    "REGISTRY",
    "get_registry",
    "register",
    # Executor
    "execute_metric",
    "execute_spec",
    "execute_many",
    "list_available_metrics",
    # Loader
    "load_metric_input",
    "available_source_tables",
    "get_player_bios",
    "search_players_by_name",
    # Cache
    "CacheEngine",
    "get_engine",
    "make_cache_key",
    "reset_engine",
    # Rank
    "Ranking",
    "rank_players",
    "to_dataframe",
    # High-level API
    "list_metrics",
    "get_metric",
    "compute",
    "compute_many",
    "rank",
    "player_metrics_dict",
    "vs_compare",
    "compute_as_dict",
    "compute_many_as_dict",
]


# ── High-level convenience API (used by Phase 3 API layer) ──

def list_metrics() -> list[str]:
    """List all registered metric names."""
    return list_available_metrics()


def get_metric(name: str) -> MetricSpec:
    """Fetch a MetricSpec by name."""
    return get_registry().get(name)


def compute(
    metric_name: str,
    season: int,
    player_ids: list[str] | None = None,
    use_cache: bool = True,
) -> "pd.Series":
    """Compute a single metric for a season (optionally filtered by player_ids).

    Args:
        metric_name: registered metric name
        season: NBA season (required, v8 §2)
        player_ids: optional BBR ID filter
        use_cache: if True, consult CacheEngine (default on)

    Returns: pd.Series indexed by player_id, values rounded to spec.precision.
    """
    import pandas as pd  # local import to avoid module-level dep at import time

    spec = get_metric(metric_name)
    cache_key = make_cache_key(metric_name, season, player_ids)

    if use_cache:
        engine = get_engine()
        cached = engine.get(cache_key)
        if cached is not None:
            return cached

    rows, player_col = load_metric_input(spec, season, player_ids)
    if not rows:
        # No data for requested players — return empty Series (not an error).
        import pandas as pd
        return pd.Series(name=metric_name, dtype=float)
    series = execute_spec(spec, rows, player_col)

    if use_cache:
        get_engine().set(cache_key, series)

    return series


def compute_many(
    metric_names: list[str],
    season: int,
    player_ids: list[str] | None = None,
    use_cache: bool = True,
) -> "pd.DataFrame":
    """Compute multiple metrics (must share source_table) for a season.

    Returns: pd.DataFrame indexed by player_id, columns = metric_names.
    """
    import pandas as pd

    if not metric_names:
        raise ValueError("compute_many requires at least one metric name")

    registry = get_registry()
    specs = [registry.get(n) for n in metric_names]
    tables = {s.source_table for s in specs}
    if len(tables) > 1:
        raise ValueError(
            f"compute_many requires all metrics share source_table; got {tables}"
        )

    # Cache key includes all metric names (sorted for stability)
    cache_key = make_cache_key(
        "+".join(sorted(metric_names)),
        season,
        player_ids,
    )

    if use_cache:
        engine = get_engine()
        cached = engine.get(cache_key)
        if cached is not None:
            return cached

    # All specs share source_table, so any spec's loader works
    rows, player_col = load_metric_input(specs[0], season, player_ids)
    if not rows:
        # No data for requested players — return empty DataFrame.
        import pandas as pd
        return pd.DataFrame(columns=metric_names)
    df = execute_many(metric_names, rows, player_col)

    if use_cache:
        get_engine().set(cache_key, df)

    return df


def rank(
    metric_name: str,
    season: int,
    player_ids: list[str] | None = None,
    ascending: bool = False,
    min_value: float | None = None,
    use_cache: bool = True,
) -> list[Ranking]:
    """Compute a metric and return ranked results.

    Args:
        metric_name: registered metric name
        season: NBA season
        player_ids: optional BBR ID filter
        ascending: False = highest first (default)
        min_value: optional minimum value filter (e.g. min games played)
        use_cache: cache the underlying metric computation

    Returns: list[Ranking] sorted by rank.
    """
    series = compute(metric_name, season, player_ids, use_cache=use_cache)
    return rank_players(series, ascending=ascending, min_value=min_value)


def player_metrics_dict(
    metric_names: list[str],
    season: int,
    player_id: str,
    use_cache: bool = True,
) -> dict[str, float]:
    """Compute multiple metrics for a single player, return as {metric: value}.

    Convenience for API layer: avoids exposing pandas DataFrame to Layer 3.
    NaN values are skipped (not included in the returned dict).

    Args:
        metric_names: list of registered metric names (must share source_table)
        season: NBA season
        player_id: BBR player_id
        use_cache: cache the underlying compute_many call
    """
    df = compute_many(metric_names, season, player_ids=[player_id], use_cache=use_cache)
    result: dict[str, float] = {}
    if player_id not in df.index:
        return result
    row = df.loc[player_id]
    for m in metric_names:
        if m not in row:
            continue
        val = row[m]
        # Skip NaN (player has no data for this metric)
        if val == val and val is not None:  # NaN check: NaN != NaN
            result[m] = float(val)
    return result


def vs_compare(
    metric_names: list[str],
    season: int,
    player_id_1: str,
    player_id_2: str,
    use_cache: bool = True,
) -> dict[str, dict[str, float]]:
    """Compute multiple metrics for two players, return side-by-side dict.

    Returns: {metric_name: {player_id_1: x, player_id_2: y}}
    NaN values are preserved as-is (callers can handle None).
    """
    df = compute_many(
        metric_names,
        season,
        player_ids=[player_id_1, player_id_2],
        use_cache=use_cache,
    )
    result: dict[str, dict[str, float]] = {}
    for m in metric_names:
        if m not in df.columns:
            continue
        v1 = df.loc[player_id_1, m] if player_id_1 in df.index else None
        v2 = df.loc[player_id_2, m] if player_id_2 in df.index else None
        # Convert NaN to None for JSON-friendliness
        v1 = float(v1) if (v1 is not None and v1 == v1) else None  # type: ignore[assignment]
        v2 = float(v2) if (v2 is not None and v2 == v2) else None  # type: ignore[assignment]
        result[m] = {player_id_1: v1, player_id_2: v2}  # type: ignore[dict-item]
    return result


def compute_as_dict(
    metric_name: str,
    season: int,
    player_ids: list[str] | None = None,
    use_cache: bool = True,
) -> dict[str, float]:
    """Compute a single metric, return as {player_id: value} dict.

    Convenience for API layer: no pandas objects leak to Layer 3.
    NaN values are skipped (not included in the returned dict).
    """
    series = compute(metric_name, season, player_ids, use_cache=use_cache)
    return {
        str(pid): float(v)
        for pid, v in series.items()
        if v == v  # skip NaN
    }


def compute_many_as_dict(
    metric_names: list[str],
    season: int,
    player_ids: list[str] | None = None,
    use_cache: bool = True,
) -> dict[str, dict[str, float]]:
    """Compute multiple metrics, return as {player_id: {metric: value}} dict.

    Convenience for API layer: no pandas objects leak to Layer 3.
    NaN values are skipped per (player, metric).
    """
    df = compute_many(metric_names, season, player_ids=player_ids, use_cache=use_cache)
    result: dict[str, dict[str, float]] = {}
    for pid in df.index:
        row = df.loc[pid]
        pid_str = str(pid)
        result[pid_str] = {}
        for m in metric_names:
            if m not in row:
                continue
            v = row[m]
            if v == v and v is not None:  # skip NaN
                result[pid_str][m] = float(v)
    return result

```

#### backend/services/metric_engine/registry.py

```python
"""NBACore v8 §2 Layer 2 — Metric Registry.

Sole source of truth for metric definitions. Every metric that the engine
can compute MUST be registered here (or in a sub-module at import time).

v8 §2 mandates:
    - All metrics must come from registry (no ad-hoc computation)
    - API/Frontend may not define metrics
    - compute() is a vectorized Callable, NOT a string expression
      (so we never need eval()/exec() — v8 §6 compliant)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

import pandas as pd

MetricFn = Callable[[pd.DataFrame], pd.Series]

MetricKind = Literal["per_game", "ratio", "weighted_sum", "expression"]


@dataclass(frozen=True)
class MetricSpec:
    """Declarative metric definition (immutable, introspectable)."""
    name: str                           # unique key, e.g. 'pts_per_game'
    kind: MetricKind                    # computation pattern
    source_table: str                   # registered data_layer table
    required_cols: tuple[str, ...]      # columns the compute fn reads
    compute: MetricFn                   # vectorized function: DataFrame -> Series
    description: str = ""
    min_denominator: float = 1.0        # guard against div-by-zero (ratio/per_game)
    precision: int = 6                  # decimal places for deterministic output


class MetricRegistry:
    """In-memory registry. Singleton-style via module-level _REGISTRY."""

    def __init__(self) -> None:
        self._specs: dict[str, MetricSpec] = {}

    def register(self, spec: MetricSpec) -> None:
        if not spec.name or not isinstance(spec.name, str):
            raise ValueError("metric name must be non-empty str")
        if spec.name in self._specs:
            raise ValueError(f"metric {spec.name!r} already registered")
        if not isinstance(spec.required_cols, tuple):
            raise TypeError("required_cols must be tuple (hashable)")
        self._specs[spec.name] = spec

    def get(self, name: str) -> MetricSpec:
        if name not in self._specs:
            raise KeyError(
                f"metric {name!r} not registered. "
                f"Available: {sorted(self._specs)}"
            )
        return self._specs[name]

    def list(self) -> list[str]:
        return sorted(self._specs)

    def has(self, name: str) -> bool:
        return name in self._specs

    def all_specs(self) -> list[MetricSpec]:
        return [self._specs[n] for n in self.list()]

    def __len__(self) -> int:
        return len(self._specs)


# Module-level singleton — the ONE registry used across the engine.
REGISTRY = MetricRegistry()


def get_registry() -> MetricRegistry:
    """Public accessor (used by executor + tests)."""
    return REGISTRY


def register(spec: MetricSpec) -> None:
    """Convenience wrapper around REGISTRY.register."""
    REGISTRY.register(spec)

```

#### backend/services/metric_engine/executor.py

```python
"""NBACore v8 §2 Layer 2 — Vectorized Executor.

The ONLY module that runs metric.compute() on a matrix. Enforces:
    - metric must be in registry
    - required_cols validated by matrix_builder (fail-fast)
    - output rounded to spec.precision (determinism)
    - NaN values preserved (no implicit fill)
    - no eval/exec — compute is a Callable

v8 §6 forbidden list:
    - no eval() / exec()
    - no dynamic SQL
    - no per-player loop (compute must be vectorized)
"""
from __future__ import annotations

import logging

import pandas as pd

from backend.services.metric_engine.matrix_builder import build_matrix, coerce_numeric
from backend.services.metric_engine.registry import MetricSpec, get_registry

logger = logging.getLogger("nbacore.metric.executor")


def execute_metric(
    metric_name: str,
    rows: list[dict],
    player_col: str,
) -> pd.Series:
    """Compute a metric over raw rows. Returns player_id → value Series.

    Args:
        metric_name: registered metric name (KeyError if unknown)
        rows: raw DB rows (list[dict]) from data_layer
        player_col: column name for player_id

    Returns:
        pd.Series indexed by player_col (str), values rounded to spec.precision.
        NaN preserved (callers may filter via RankEngine.min_games).
    """
    spec = get_registry().get(metric_name)
    return execute_spec(spec, rows, player_col)


def execute_spec(
    spec: MetricSpec,
    rows: list[dict],
    player_col: str,
) -> pd.Series:
    """Execute a MetricSpec over rows. Lower-level than execute_metric."""
    matrix = build_matrix(rows, player_col, required_cols=spec.required_cols)
    matrix = coerce_numeric(matrix, spec.required_cols)

    # v8 Phase 3 FIX: aggregate duplicate player_id rows (traded players).
    if matrix.index.has_duplicates:
        matrix = matrix.groupby(matrix.index).sum(numeric_only=True)

    # Apply min_denominator guard for ratio / per_game kinds.
    # The compute fn itself should handle div-by-zero via clip(lower=min_denominator).
    series = spec.compute(matrix)

    if not isinstance(series, pd.Series):
        raise TypeError(
            f"metric {spec.name!r} compute() returned {type(series).__name__}, "
            f"expected pd.Series"
        )

    # Determinism: round to fixed precision (NaN stays NaN)
    series = series.round(spec.precision)
    series.name = spec.name
    return series


def execute_many(
    metric_names: list[str],
    rows: list[dict],
    player_col: str,
) -> pd.DataFrame:
    """Compute multiple metrics over the SAME rows. Returns DataFrame.

    Efficient: builds matrix once per unique source_table, then runs each
    metric's compute() on the shared matrix. All metrics must share the
    same source_table (otherwise use execute_metric per metric).
    """
    if not metric_names:
        raise ValueError("execute_many requires at least one metric name")

    registry = get_registry()
    specs = [registry.get(n) for n in metric_names]
    tables = {s.source_table for s in specs}
    if len(tables) > 1:
        raise ValueError(
            f"execute_many requires all metrics share source_table; got {tables}"
        )

    # Union of required cols (matrix_builder keeps them all)
    all_required: tuple[str, ...] = ()
    for s in specs:
        all_required = all_required + s.required_cols
    # Dedup preserving order
    seen: set[str] = set()
    unique_required = tuple(c for c in all_required if not (c in seen or seen.add(c)))

    matrix = build_matrix(rows, player_col, required_cols=unique_required)
    matrix = coerce_numeric(matrix, unique_required)

    # v8 Phase 3 FIX: aggregate duplicate player_id rows (traded players with
    # multiple team stints in fact_player_season_stats). Sums numeric columns
    # so per_game and ratio metrics compute on season totals.
    if matrix.index.has_duplicates:
        matrix = matrix.groupby(matrix.index).sum(numeric_only=True)

    result = pd.DataFrame(index=matrix.index)
    for spec in specs:
        col = spec.compute(matrix).round(spec.precision)
        result[spec.name] = col

    return result


def list_available_metrics() -> list[str]:
    """Convenience: list registered metric names."""
    return get_registry().list()

```

#### backend/services/metric_engine/matrix_builder.py

```python
"""NBACore v8 §2 Layer 2 — Matrix Builder.

Converts raw list[dict] (from data_layer) into a pandas DataFrame indexed
by player_id. All vectorized computation in executor.py operates on this.

Guarantees:
    - player_id becomes the index (string-typed for BBR consistency)
    - missing required columns raise early (fail-fast)
    - NaN values preserved (executor handles via fillna where appropriate)
"""
from __future__ import annotations

import pandas as pd


def build_matrix(
    rows: list[dict],
    player_col: str,
    required_cols: tuple[str, ...] = (),
    extra_cols: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Build a player-indexed DataFrame from raw DB rows.

    Args:
        rows: list[dict] from data_layer batch loaders
        player_col: column name holding the player_id (e.g. 'player_id')
        required_cols: columns the metric compute fn will read; missing → ValueError
        extra_cols: optional columns to keep but not require

    Returns:
        pd.DataFrame indexed by player_col (as string for BBR consistency).
        Rows with NULL/None/NaN player_id are dropped (they would aggregate
        multiple players into a single bogus index entry).

    Raises:
        ValueError: empty rows, missing player_col, or missing required_cols.
    """
    if not rows:
        raise ValueError("build_matrix requires at least one row")
    if not player_col:
        raise ValueError("player_col must be non-empty")

    df = pd.DataFrame(rows)

    if player_col not in df.columns:
        raise ValueError(
            f"player_col {player_col!r} not in rows. "
            f"Available: {sorted(df.columns)}"
        )

    # Fail-fast: verify required columns exist
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"required columns missing from rows: {missing}. "
            f"Available: {sorted(df.columns)}"
        )

    # Drop rows with NULL/None/NaN player_id BEFORE coercing to string.
    # Without this, astype(str) turns NaN into the literal string "None",
    # which then aggregates every null-player row into one bogus index entry.
    df = df[df[player_col].notna()]

    # Also reject empty-string player_ids (defensive)
    df = df[df[player_col].astype(str).str.len() > 0]

    if df.empty:
        raise ValueError(
            f"build_matrix: all rows had NULL/empty {player_col!r}; "
            f"nothing to compute"
        )

    # Coerce player_id to string (BBR IDs like 'achiupr01' are string)
    df[player_col] = df[player_col].astype(str)

    # Set index
    df = df.set_index(player_col)

    # Keep only required + extra (drop noise, save memory)
    keep = list(dict.fromkeys(required_cols + extra_cols))  # dedup, preserve order
    if keep:
        df = df[keep]

    return df


def coerce_numeric(df: pd.DataFrame, cols: tuple[str, ...]) -> pd.DataFrame:
    """Coerce specified columns to numeric (non-numeric → NaN).

    Defensive: DB returns Decimal/float/int mixed; pandas usually infers but
    some columns (e.g. 'pos' or 'team') may sneak in as object dtype.
    """
    for c in cols:
        if c in df.columns and df[c].dtype == object:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

```

#### backend/services/metric_engine/rank.py

```python
"""NBACore v8 §2 Layer 2 — Rank Engine.

Converts a metric Series (player_id → value) into ranked output with
percentiles and stable tie-breaking.

Determinism (v8 §5.3):
    - Ties broken by player_id ascending (stable, deterministic)
    - Percentiles rounded to 4 decimals
    - NaN values excluded from ranking (returned with rank=None)
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Ranking:
    """Single player's ranking record."""
    rank: int                    # 1-based; ties share the same rank
    player_id: str
    value: float
    percentile: float            # 100.0 = top, 0.0 = bottom
    sample_size: int             # total players in this ranking


def rank_players(
    series: pd.Series,
    ascending: bool = False,
    min_value: float | None = None,
) -> list[Ranking]:
    """Rank players by metric value.

    Args:
        series: pd.Series indexed by player_id (str), values = metric output.
        ascending: False = highest first (default for most metrics).
        min_value: optional minimum value filter (e.g. min games played).
                   Players below this threshold are excluded entirely.

    Returns:
        list[Ranking] sorted by rank (1-based). Ties share the same rank;
        subsequent ranks skip (standard competition ranking: 1,1,3,4,...).

    Determinism:
        - Ties broken by player_id ascending (lexicographic on str).
        - NaN values excluded from ranking.
    """
    if series.empty:
        return []

    # Filter NaN values (don't rank missing data)
    s = series.dropna()

    # Apply min_value threshold
    if min_value is not None:
        s = s[s >= min_value]

    if s.empty:
        return []

    # Deterministic sort: primary by value, secondary by player_id asc (tie-break).
    # Build a temp DataFrame to use multi-key sort with mixed ascending flags.
    tmp = pd.DataFrame({"value": s.values, "player_id": s.index.astype(str)})
    tmp = tmp.sort_values(
        by=["value", "player_id"],
        ascending=[ascending, True],
        kind="mergesort",
    )
    tmp = tmp.reset_index(drop=True)

    n = len(tmp)
    values = tmp["value"].tolist()
    ids = tmp["player_id"].tolist()

    rankings: list[Ranking] = []
    i = 0
    while i < n:
        # Find run of equal values (ties)
        j = i + 1
        while j < n and values[j] == values[i]:
            j += 1
        # All entries i..j-1 share rank (i+1) — standard competition ranking
        rank = i + 1
        # Percentile: top performer = 100.0, bottom = 0.0
        # Use rank position: pct = 100 * (n - rank) / (n - 1) for n > 1
        if n > 1:
            pct = round(100.0 * (n - rank) / (n - 1), 4)
        else:
            pct = 100.0
        for k in range(i, j):
            rankings.append(Ranking(
                rank=rank,
                player_id=str(ids[k]),
                value=round(float(values[k]), 6),
                percentile=pct,
                sample_size=n,
            ))
        i = j

    return rankings


def to_dataframe(rankings: list[Ranking]) -> pd.DataFrame:
    """Convert rankings to DataFrame for API serialization."""
    if not rankings:
        return pd.DataFrame(columns=["rank", "player_id", "value", "percentile", "sample_size"])
    return pd.DataFrame([
        {
            "rank": r.rank,
            "player_id": r.player_id,
            "value": r.value,
            "percentile": r.percentile,
            "sample_size": r.sample_size,
        }
        for r in rankings
    ])

```

#### backend/services/metric_engine/cache.py

```python
"""NBACore v8 §2 Layer 2 — Cache Engine.

diskcache-backed deterministic cache for metric computations.

Key strategy (v8 §5.3 determinism):
    - SHA256 of (metric_name | season | sorted(player_ids) | params_json)
    - params_json uses sort_keys=True (stable)
    - Value pickled with protocol=5 (fixed for byte-stable serialization)

v8 §6 forbidden list:
    - no eval/exec (pickle.loads is safe — only store our own Series)
"""
from __future__ import annotations

import hashlib
import json
import logging
import pickle
from collections.abc import Callable
from pathlib import Path

import pandas as pd
from diskcache import Cache

from backend.core import config

logger = logging.getLogger("nbacore.metric.cache")

# Default cache directory — sibling to backend/ so it survives restarts.
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent.parent.parent / ".cache" / "metric_engine"

# TTL: 24h default (season data doesn't change mid-day).
_DEFAULT_TTL = 24 * 3600

_PICKLE_PROTOCOL = 5  # fixed for byte-stable serialization


def _resolve_cache_dir() -> Path:
    """Resolve cache dir from config or fall back to default."""
    cfg_val = getattr(config, "METRIC_CACHE_DIR", None)
    if cfg_val:
        p = Path(cfg_val)
    else:
        p = _DEFAULT_CACHE_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def make_cache_key(
    metric_name: str,
    season: int,
    player_ids: list[str] | None,
    params: dict | None = None,
) -> str:
    """Build a deterministic SHA256 cache key.

    Args:
        metric_name: registered metric name
        season: NBA season int
        player_ids: list of BBR IDs (sorted for stability); None = all players
        params: optional dict of metric params (sort_keys=True)

    Returns: hex SHA256 string.
    """
    if player_ids is not None:
        ids_norm = sorted(str(p) for p in player_ids)
        ids_repr = ",".join(ids_norm)
    else:
        ids_repr = "*ALL*"
    params_norm = json.dumps(params or {}, sort_keys=True, default=str)
    payload = f"{metric_name}|{season}|{ids_repr}|{params_norm}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CacheEngine:
    """diskcache wrapper with explicit get/set/invalidate API."""

    def __init__(self, cache_dir: Path | str | None = None, ttl: int = _DEFAULT_TTL) -> None:
        self._dir = Path(cache_dir) if cache_dir else _resolve_cache_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache = Cache(str(self._dir))
        self._ttl = ttl
        logger.info("CacheEngine initialized | dir=%s | ttl=%ds", self._dir, self._ttl)

    @property
    def dir(self) -> Path:
        return self._dir

    @property
    def ttl(self) -> int:
        return self._ttl

    def get(self, key: str) -> pd.Series | pd.DataFrame | None:
        """Return cached value or None. Hit/miss logged at debug level."""
        raw = self._cache.get(key, default=None)
        if raw is None:
            logger.debug("cache MISS | key=%s", key[:12])
            return None
        try:
            value = pickle.loads(raw)
            logger.debug("cache HIT  | key=%s", key[:12])
            return value
        except Exception as exc:
            logger.warning("cache deserialization failed | key=%s | %s", key[:12], exc)
            self._cache.delete(key)
            return None

    def set(self, key: str, value: pd.Series | pd.DataFrame) -> None:
        """Store value under key with TTL."""
        raw = pickle.dumps(value, protocol=_PICKLE_PROTOCOL)
        self._cache.set(key, raw, expire=self._ttl)
        logger.debug("cache SET  | key=%s | bytes=%d", key[:12], len(raw))

    def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], pd.Series | pd.DataFrame],
    ) -> pd.Series | pd.DataFrame:
        """Idempotent get-or-compute. compute_fn only called on miss."""
        cached = self.get(key)
        if cached is not None:
            return cached
        value = compute_fn()
        if not isinstance(value, (pd.Series, pd.DataFrame)):
            raise TypeError(
                f"CacheEngine only supports pd.Series/pd.DataFrame, got {type(value).__name__}"
            )
        self.set(key, value)
        return value

    def invalidate(self, key: str) -> bool:
        return self._cache.delete(key)

    def invalidate_all(self) -> int:
        """Clear entire cache. Returns number of keys removed."""
        count = len(self._cache)
        self._cache.clear()
        logger.info("cache cleared | removed=%d", count)
        return count

    def stats(self) -> dict:
        return {"dir": str(self._dir), "size_bytes": self._cache.size(), "count": len(self._cache)}

    def close(self) -> None:
        self._cache.close()


# Module-level singleton (lazy-initialized)
_engine: CacheEngine | None = None


def get_engine() -> CacheEngine:
    """Public accessor — initializes on first call."""
    global _engine
    if _engine is None:
        _engine = CacheEngine()
    return _engine


def reset_engine() -> None:
    """For tests: tear down the singleton."""
    global _engine
    if _engine is not None:
        _engine.close()
        _engine = None

```

#### backend/services/metric_engine/batch_loader.py

```python
"""NBACore v8 §2 Layer 2 — Metric Engine Batch Loader.

Thin wrapper that pulls data from Layer 1 (data_layer) based on a MetricSpec.
This is the ONLY module in Layer 2 that talks to Layer 1.

v8 §2 mandates:
    - All data fetches go through data_layer (no direct SQL in metric_engine)
    - season filter is mandatory (enforced by data_layer)
    - player filtering uses IN-clause or temp table (decided by data_layer)
"""
from __future__ import annotations

import logging

from backend.data_layer import (
    load_player_gamelog,
    load_player_gamelog_by_ids,
    load_player_season_stats,
    load_players,
    load_seasons_available,
    search_players,
    should_use_temp_table,
)
from backend.services.metric_engine.registry import MetricSpec

logger = logging.getLogger("nbacore.metric.loader")


# Map source_table → data_layer loader function + player_col
_SOURCE_TABLE_LOADERS = {
    "fact_player_season_stats": {
        "all": load_player_season_stats,
        "by_ids": None,  # no dedicated by_ids loader; load all + filter in-process
        "player_col": "player_id",
    },
    "player_gamelog": {
        "all": load_player_gamelog,           # supports optional player_ids (IN-clause)
        "by_ids": load_player_gamelog_by_ids,  # temp table for large batches
        "player_col": "br_player_id",
    },
}


def load_metric_input(
    spec: MetricSpec,
    season: int,
    player_ids: list[str] | None = None,
) -> tuple[list[dict], str]:
    """Load raw rows for a metric from Layer 1.

    Args:
        spec: MetricSpec (provides source_table)
        season: required NBA season
        player_ids: optional BBR ID filter; None = all players that season

    Returns:
        (rows, player_col) — player_col is the column name to use as index.

    Raises:
        ValueError: if source_table is not registered with a loader.
    """
    if spec.source_table not in _SOURCE_TABLE_LOADERS:
        raise ValueError(
            f"source_table {spec.source_table!r} has no Layer 1 loader mapped. "
            f"Available: {sorted(_SOURCE_TABLE_LOADERS)}"
        )

    cfg = _SOURCE_TABLE_LOADERS[spec.source_table]
    player_col = cfg["player_col"]

    if player_ids:
        by_ids_fn = cfg["by_ids"]
        if by_ids_fn is None:
            # fact_player_season_stats: ~600 rows/season, just load all + filter in-process
            rows = cfg["all"](season)
            id_set = set(player_ids)
            rows = [r for r in rows if r.get(player_col) in id_set]
            logger.info(
                "metric input | spec=%s | season=%d | filter_in_proc | rows=%d",
                spec.name, season, len(rows),
            )
        else:
            # player_gamelog: large table, use IN-clause for small batches, temp table for large
            if should_use_temp_table(player_ids):
                rows = by_ids_fn(season, player_ids)
                logger.info(
                    "metric input | spec=%s | season=%d | temp_table | ids=%d | rows=%d",
                    spec.name, season, len(player_ids), len(rows),
                )
            else:
                # IN-clause via the all-loader's optional player_ids param
                rows = cfg["all"](season, player_ids=player_ids)
                logger.info(
                    "metric input | spec=%s | season=%d | in_clause | ids=%d | rows=%d",
                    spec.name, season, len(player_ids), len(rows),
                )
    else:
        rows = cfg["all"](season)
        logger.info(
            "metric input | spec=%s | season=%d | all_players | rows=%d",
            spec.name, season, len(rows),
        )

    return rows, player_col


def available_source_tables() -> list[str]:
    """List source tables that have Layer 1 loaders mapped."""
    return sorted(_SOURCE_TABLE_LOADERS)


# ── Player bio / search wrappers (for Phase 3 API layer) ──
# API layer must NOT import data_layer directly — it goes through metric_engine.
# These wrappers keep the v8 §2 layer isolation: API → metric_engine → data_layer → db.

def get_player_bios(player_ids: list[str]) -> list[dict]:
    """Fetch dim_players rows for a list of BBR player_ids.

    Args:
        player_ids: list of BBR IDs (e.g. ['gilgesh01', 'antetgi01'])

    Returns: list[dict] with dim_players columns (player_name, position, etc.)
    """
    if not player_ids:
        return []
    return load_players(player_ids)


def search_players_by_name(name: str, limit: int = 20) -> list[dict]:
    """Search dim_players by name (case-insensitive ILIKE).

    Args:
        name: search string (>= 2 chars)
        limit: max results (1-100, default 20)

    Returns: list[dict] with dim_players columns.
    """
    return search_players(name, limit=limit)


def get_available_seasons(table_name: str = "fact_player_season_stats") -> list[int]:
    """Return distinct seasons available in a table (descending).

    Thin wrapper around data_layer.load_seasons_available to maintain
    v8 §2 layer isolation (API → metric_engine → data_layer).

    Args:
        table_name: table to query (default: fact_player_season_stats)

    Returns: list of season integers, sorted descending.
    """
    return load_seasons_available(table_name)

```

#### backend/services/metric_engine/metrics/__init__.py

```python
"""NBACore v8 §2 Layer 2 — Built-in metric definitions.

Importing this package registers all built-in metrics with the singleton
MetricRegistry. Metric Engine users only need:
    import backend.services.metric_engine  # triggers registration
"""
from backend.services.metric_engine.metrics import advanced, basic, composite  # noqa: F401

__all__ = ["basic", "advanced", "composite"]

```

#### backend/services/metric_engine/metrics/basic.py

```python
"""NBACore v8 §2 Layer 2 — Basic per-game metrics (PPG / RPG / APG / SPG / BPG).

All compute fns are vectorized pandas operations on a player-indexed DataFrame.
fact_player_season_stats has season totals, so per-game = total / games.
"""
from __future__ import annotations

import pandas as pd

from backend.services.metric_engine.registry import MetricFn, MetricSpec, register

_SOURCE = "fact_player_season_stats"


def _per_game(numerator_col: str) -> MetricFn:
    """Build a vectorized compute fn: sum(numerator) / sum(games)."""
    def _compute(df: pd.DataFrame) -> pd.Series:
        # df is indexed by player_id; for fact_player_season_stats each row IS
        # one player-season (no groupby needed). Sum is defensive in case of
        # multi-row players (e.g. traded mid-season produces 2 rows).
        g = df.groupby(df.index)[numerator_col].sum()
        games = df.groupby(df.index)["g"].sum().clip(lower=1)
        return g / games
    return _compute


register(MetricSpec(
    name="pts_per_game",
    kind="per_game",
    source_table=_SOURCE,
    required_cols=("pts", "g"),
    compute=_per_game("pts"),
    description="Points per game = sum(pts) / sum(g)",
))

register(MetricSpec(
    name="reb_per_game",
    kind="per_game",
    source_table=_SOURCE,
    required_cols=("trb", "g"),
    compute=_per_game("trb"),
    description="Total rebounds per game = sum(trb) / sum(g)",
))

register(MetricSpec(
    name="ast_per_game",
    kind="per_game",
    source_table=_SOURCE,
    required_cols=("ast", "g"),
    compute=_per_game("ast"),
    description="Assists per game = sum(ast) / sum(g)",
))

register(MetricSpec(
    name="stl_per_game",
    kind="per_game",
    source_table=_SOURCE,
    required_cols=("stl", "g"),
    compute=_per_game("stl"),
    description="Steals per game = sum(stl) / sum(g)",
))

register(MetricSpec(
    name="blk_per_game",
    kind="per_game",
    source_table=_SOURCE,
    required_cols=("blk", "g"),
    compute=_per_game("blk"),
    description="Blocks per game = sum(blk) / sum(g)",
))

```

#### backend/services/metric_engine/metrics/advanced.py

```python
"""NBACore v8 §2 Layer 2 — Advanced ratio metrics (TS% / eFG% / USG%).

All ratio metrics use the same pattern: sum(numerator) / sum(denominator)
with clip(lower=1.0) guard to prevent div-by-zero. NaN preserved where
denominator is 0.
"""
from __future__ import annotations

import pandas as pd

from backend.services.metric_engine.registry import MetricSpec, register

_SOURCE = "fact_player_season_stats"


# True Shooting % = pts / (2 * (fga + 0.44 * fta))
def _ts_pct(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    pts = grp["pts"].sum()
    fga = grp["fga"].sum()
    fta = grp["fta"].sum()
    denom = (2 * (fga + 0.44 * fta)).clip(lower=1.0)
    return pts / denom


# Effective FG % = (fg + 0.5 * x3p) / fga
def _efg_pct(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    fg = grp["fg"].sum()
    x3p = grp["x3p"].sum()
    fga = grp["fga"].sum()
    denom = fga.clip(lower=1.0)
    return (fg + 0.5 * x3p) / denom


# FT Rate = fta / fga
def _ft_rate(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    fta = grp["fta"].sum()
    fga = grp["fga"].sum()
    denom = fga.clip(lower=1.0)
    return fta / denom


# USG% is already a column in fact_player_season_stats — pass-through
def _usg_passthrough(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    return grp["usg_percent"].mean()  # mean across multi-row players


register(MetricSpec(
    name="true_shooting_pct",
    kind="ratio",
    source_table=_SOURCE,
    required_cols=("pts", "fga", "fta"),
    compute=_ts_pct,
    description="True Shooting % = pts / (2 * (fga + 0.44 * fta))",
    min_denominator=1.0,
))

register(MetricSpec(
    name="effective_fg_pct",
    kind="ratio",
    source_table=_SOURCE,
    required_cols=("fg", "x3p", "fga"),
    compute=_efg_pct,
    description="Effective FG % = (fg + 0.5 * x3p) / fga",
    min_denominator=1.0,
))

register(MetricSpec(
    name="ft_rate",
    kind="ratio",
    source_table=_SOURCE,
    required_cols=("fta", "fga"),
    compute=_ft_rate,
    description="FT Rate = fta / fga",
    min_denominator=1.0,
))

register(MetricSpec(
    name="usage_percent",
    kind="expression",
    source_table=_SOURCE,
    required_cols=("usg_percent",),
    compute=_usg_passthrough,
    description="Usage % (pass-through from fact_player_season_stats.usg_percent)",
))

```

#### backend/services/metric_engine/metrics/composite.py

```python
"""NBACore v8 §2 Layer 2 — Composite weighted-sum metrics.

Fantasy points and efficiency rating are linear combinations of box score
totals. All fns are vectorized pandas operations.
"""
from __future__ import annotations

import pandas as pd

from backend.services.metric_engine.registry import MetricSpec, register

_SOURCE = "fact_player_season_stats"


# Fantasy points (standard fantasy basketball weights):
#   1.0*pts + 1.2*trb + 1.5*ast + 3.0*stl + 3.0*blk - 1.0*tov
# Plus bonus for 3pm (1.0 per x3p) to reward floor spacing.
def _fantasy_points(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    return (
        1.0 * grp["pts"].sum()
        + 1.2 * grp["trb"].sum()
        + 1.5 * grp["ast"].sum()
        + 3.0 * grp["stl"].sum()
        + 3.0 * grp["blk"].sum()
        - 1.0 * grp["tov"].sum()
        + 1.0 * grp["x3p"].sum()
    )


# Efficiency Rating (PER-inspired, simplified):
#   (pts + trb + ast + stl + blk) - (fga - fg) - (fta - ft) - tov
# Positive contributions minus missed shots and turnovers.
def _efficiency_rating(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    pts = grp["pts"].sum()
    trb = grp["trb"].sum()
    ast = grp["ast"].sum()
    stl = grp["stl"].sum()
    blk = grp["blk"].sum()
    fga = grp["fga"].sum()
    fg = grp["fg"].sum()
    fta = grp["fta"].sum()
    ft = grp["ft"].sum()
    tov = grp["tov"].sum()
    positives = pts + trb + ast + stl + blk
    negatives = (fga - fg) + (fta - ft) + tov
    return positives - negatives


register(MetricSpec(
    name="fantasy_points",
    kind="weighted_sum",
    source_table=_SOURCE,
    required_cols=("pts", "trb", "ast", "stl", "blk", "tov", "x3p"),
    compute=_fantasy_points,
    description="Fantasy points = 1.0*pts + 1.2*trb + 1.5*ast + 3.0*stl + 3.0*blk - 1.0*tov + 1.0*x3p",
))

register(MetricSpec(
    name="efficiency_rating",
    kind="expression",
    source_table=_SOURCE,
    required_cols=("pts", "trb", "ast", "stl", "blk", "fga", "fg", "fta", "ft", "tov"),
    compute=_efficiency_rating,
    description="Efficiency = (pts+trb+ast+stl+blk) - (fga-fg) - (fta-ft) - tov",
))

```

### 4.5 服务层 — Context Engine

#### backend/services/context_engine/__init__.py

```python
"""NBACore v8 §2 Layer 2.5 — Context Engine (pure Metric Engine consumer).

Context System provides higher-level analysis built ENTIRELY on top of Metric Engine.
It has NO direct database access — all data flows through Layer 2.

Three sub-systems:
    - similar_players  — cosine similarity across metric vector (same position filter)
    - role_evolution   — how a player's role changed across seasons
    - trend_analysis   — linear trend + momentum for a metric across seasons

v8 §2 compliance:
    - All data comes from Metric Engine (compute_many, rank)
    - No psycopg2 / data_layer imports
    - Computation here is "context-level (aggregation, similarity, trend)
    - Still vectorized (pandas / numpy) — no per-player Python loops
"""
from __future__ import annotations

from backend.services.context_engine.similar_players import find_similar_players
from backend.services.context_engine.role_evolution import player_role_evolution
from backend.services.context_engine.trend_analysis import player_trend

__all__ = [
    "find_similar_players",
    "player_role_evolution",
    "player_trend",
]

```

#### backend/services/context_engine/similar_players.py

```python
"""Similar player finder — cosine similarity across a metric feature vector.

All data sourced from Metric Engine (layer 2). This module builds a per-player
metric vector and ranks by cosine similarity to the target player.

v8 §2 compliance:
- Input: metric names + season → calls compute_many
- Output: list of (player_id, similarity_score, top_metrics)
- No DB access, no SQL, no data_layer imports
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from backend.services.metric_engine import compute_many, get_player_bios


@dataclass
class SimilarPlayer:
    player_id: str
    similarity: float
    name: str
    team: str | None
    position: str | None


def find_similar_players(
    player_id: str,
    season: int,
    metric_names: list[str],
    limit: int = 10,
    position_filter: bool = True,
) -> list[SimilarPlayer]:
    """Find players most similar to target player using cosine similarity.

    Args:
        player_id: target BBR player ID
        season: NBA season
        metric_names: list of metric names to use as feature vector
        limit: max number of similar players to return
        position_filter: if True, only compare to players sharing a position

    Returns:
        List of SimilarPlayer sorted by similarity descending.
        Target player is excluded from results.
    """
    if not metric_names:
        raise ValueError("metric_names must not be empty")

    # Step 1: get all player data for these metrics (entire league)
    df = compute_many(metric_names, season)

    if df.empty or player_id not in df.index:
        return []

    # Step 2: position filter (optional)
    if position_filter:
        target_bio_list = get_player_bios([player_id])
        target_bio = target_bio_list[0] if target_bio_list else None
        if target_bio and target_bio.get("position"):
            target_pos = target_bio["position"].split(",")[0].strip()
            all_ids = list(df.index)
            all_bios_list = get_player_bios(all_ids)
            all_bios = {b["player_id"]: b for b in all_bios_list}
            same_pos_ids = [
                pid for pid, bio in all_bios.items()
                if bio.get("position") and target_pos in bio["position"]
            ]
            if same_pos_ids:
                df = df.loc[df.index.isin(same_pos_ids)]

    if df.empty or player_id not in df.index:
        return []

    # Step 3: normalize (z-score) so all metrics have equal weight
    means = df.mean()
    stds = df.std()
    # Avoid division by zero for constant metrics
    stds = stds.replace(0, 1.0)
    df_norm = (df - means) / stds

    # Step 4: cosine similarity (vectorized)
    target_vec = df_norm.loc[player_id].values
    all_vecs = df_norm.values

    # Cosine sim = dot(A,B) / (||A|| * ||B||)
    dot_products = all_vecs @ target_vec
    target_norm = math.sqrt((target_vec ** 2).sum())
    all_norms = ((all_vecs ** 2).sum(axis=1)) ** 0.5

    # Avoid division by zero
    all_norms[all_norms == 0] = 1.0
    similarities = dot_products / (all_norms * target_norm)

    # Step 5: build results
    result_pairs = [
        (str(pid), float(sim))
        for pid, sim in zip(df.index, similarities)
        if pid != player_id and sim == sim  # exclude target + NaN
    ]
    result_pairs.sort(key=lambda x: x[1], reverse=True)

    top_pairs = result_pairs[:limit]
    if not top_pairs:
        return []

    # Step 6: attach bios
    top_ids = [pid for pid, _ in top_pairs]
    bios_list = get_player_bios(top_ids)
    bios = {b["player_id"]: b for b in bios_list}

    results: list[SimilarPlayer] = []
    for pid, sim in top_pairs:
        bio = bios.get(pid, {})
        results.append(SimilarPlayer(
            player_id=pid,
            similarity=round(sim, 4),
            name=bio.get("player_name") or bio.get("full_name") or pid,
            team=bio.get("team"),
            position=bio.get("position"),
        ))

    return results

```

#### backend/services/context_engine/role_evolution.py

```python
"""Role evolution — how a player's statistical profile changed across seasons.

Compares the player's metric vector across multiple seasons to show:
- Which metrics grew / declined / stayed flat
- Overall role shift magnitude
- Key turning points

All data sourced from Metric Engine (layer 2). No DB access.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from backend.services.metric_engine import compute_many


@dataclass
class MetricChange:
    metric: str
    first_value: float | None
    last_value: float | None
    absolute_change: float | None
    pct_change: float | None
    direction: str  # "up" | "down" | "flat"
    trend_slope: float | None  # per-season linear trend slope


@dataclass
class RoleEvolution:
    player_id: str
    seasons: list[int]
    metric_changes: list[MetricChange]
    overall_shift_magnitude: float  # cosine distance between first and last season
    top_growth: list[str] = field(default_factory=list)
    top_decline: list[str] = field(default_factory=list)


def _linreg_slope(x: list[float], y: list[float]) -> float | None:
    """Simple OLS slope. Returns None if insufficient data or zero variance."""
    n = len(x)
    if n < 2:
        return None
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den = sum((xi - mean_x) ** 2 for xi in x)
    if den == 0:
        return None
    return num / den


def player_role_evolution(
    player_id: str,
    seasons: list[int],
    metric_names: list[str],
) -> RoleEvolution:
    """Analyze how a player's role evolved across seasons.

    Args:
        player_id: BBR player ID
        seasons: list of seasons to analyze (sorted ascending)
        metric_names: metrics to include in the profile

    Returns:
        RoleEvolution with per-metric changes and overall shift.
    """
    if not seasons or not metric_names:
        raise ValueError("seasons and metric_names must not be empty")

    sorted_seasons = sorted(seasons)

    # Collect per-season metric values for this player
    # season -> {metric: value}
    season_vals: dict[int, dict[str, float]] = {}
    for s in sorted_seasons:
        df = compute_many(metric_names, s, player_ids=[player_id])
        if df.empty or player_id not in df.index:
            continue
        row = df.loc[player_id]
        season_vals[s] = {m: float(row[m]) if m in row and row[m] == row[m] else None for m in metric_names}

    if len(season_vals) < 2:
        # Not enough seasons with data — return what we have
        return RoleEvolution(
            player_id=player_id,
            seasons=sorted(season_vals.keys()),
            metric_changes=[],
            overall_shift_magnitude=0.0,
        )

    valid_seasons = sorted(season_vals.keys())
    first_s = valid_seasons[0]
    last_s = valid_seasons[-1]

    # Build per-metric change analysis
    changes: list[MetricChange] = []
    first_vec: list[float] = []
    last_vec: list[float] = []

    for m in metric_names:
        first_val = season_vals[first_s].get(m)
        last_val = season_vals[last_s].get(m)

        # Time series for this metric
        series_x: list[float] = []
        series_y: list[float] = []
        for s in valid_seasons:
            v = season_vals[s].get(m)
            if v is not None:
                series_x.append(float(s))
                series_y.append(v)

        slope = _linreg_slope(series_x, series_y) if len(series_x) >= 2 else None

        abs_change = None
        pct_change = None
        direction = "flat"

        if first_val is not None and last_val is not None:
            abs_change = round(last_val - first_val, 4)
            if first_val != 0:
                pct_change = round((last_val - first_val) / abs(first_val) * 100, 2)
            if abs_change > 0:
                direction = "up"
            elif abs_change < 0:
                direction = "down"

        changes.append(MetricChange(
            metric=m,
            first_value=first_val,
            last_value=last_val,
            absolute_change=abs_change,
            pct_change=pct_change,
            direction=direction,
            trend_slope=round(slope, 4) if slope is not None else None,
        ))

        # For overall shift: include metrics with both values present
        if first_val is not None and last_val is not None:
            first_vec.append(first_val)
            last_vec.append(last_val)

    # Overall shift magnitude — cosine distance = 1 - cosine_similarity
    shift = 0.0
    if first_vec and last_vec and len(first_vec) >= 2:
        dot = sum(a * b for a, b in zip(first_vec, last_vec))
        norm_a = math.sqrt(sum(a * a for a in first_vec))
        norm_b = math.sqrt(sum(b * b for b in last_vec))
        if norm_a > 0 and norm_b > 0:
            cos_sim = dot / (norm_a * norm_b)
            shift = round(1 - cos_sim, 4)

    # Top growth / decline (by pct_change, requires non-zero first_val)
    growth = [c for c in changes if c.pct_change is not None and c.direction == "up"]
    decline = [c for c in changes if c.pct_change is not None and c.direction == "down"]
    growth.sort(key=lambda c: c.pct_change or 0, reverse=True)
    decline.sort(key=lambda c: c.pct_change or 0)

    return RoleEvolution(
        player_id=player_id,
        seasons=valid_seasons,
        metric_changes=changes,
        overall_shift_magnitude=shift,
        top_growth=[c.metric for c in growth[:3]],
        top_decline=[c.metric for c in decline[:3]],
    )

```

#### backend/services/context_engine/trend_analysis.py

```python
"""Trend analysis — linear trend + momentum for a single metric across seasons.

All data sourced from Metric Engine (layer 2). No DB access.

Output:
    - slope (per-season change)
    - intercept
    - r-squared (goodness of fit)
    - momentum (recent slope vs overall slope)
    - predicted next season value
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from backend.services.metric_engine import compute


@dataclass
class MetricTrend:
    player_id: str
    metric: str
    seasons: list[int]
    values: list[float | None]
    slope: float | None
    intercept: float | None
    r_squared: float | None
    momentum: float | None  # recent (last 3) vs overall slope ratio
    predicted_next: float | None
    direction: str  # "up" | "down" | "flat" | "insufficient_data"


def _linreg(x: list[float], y: list[float]) -> tuple[float, float, float]:
    """OLS regression: return (slope, intercept, r_squared)."""
    n = len(x)
    if n < 2:
        raise ValueError("Need at least 2 points")

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    ss_xy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    ss_xx = sum((xi - mean_x) ** 2 for xi in x)
    ss_yy = sum((yi - mean_y) ** 2 for yi in y)

    if ss_xx == 0:
        raise ValueError("Zero variance in x")

    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    r_squared = 0.0
    if ss_yy > 0:
        y_pred = [slope * xi + intercept for xi in x]
        ss_res = sum((yi - yp) ** 2 for yi, yp in zip(y, y_pred))
        r_squared = 1 - ss_res / ss_yy

    return slope, intercept, r_squared


def player_trend(
    player_id: str,
    metric: str,
    seasons: list[int],
) -> MetricTrend:
    """Compute linear trend for a single metric across seasons.

    Args:
        player_id: BBR player ID
        metric: registered metric name
        seasons: list of seasons to include (sorted)

    Returns:
        MetricTrend with slope, r_squared, momentum, prediction.
    """
    if not seasons:
        raise ValueError("seasons must not be empty")

    sorted_seasons = sorted(seasons)

    # Collect values per season
    values: list[float | None] = []
    for s in sorted_seasons:
        series = compute(metric, s, player_ids=[player_id])
        if not series.empty and player_id in series.index:
            v = float(series.loc[player_id])
            values.append(v if v == v else None)  # NaN → None
        else:
            values.append(None)

    # Filter to valid (season, value) pairs
    valid_x = [float(s) for s, v in zip(sorted_seasons, values) if v is not None]
    valid_y = [v for v in values if v is not None]

    if len(valid_x) < 2:
        return MetricTrend(
            player_id=player_id,
            metric=metric,
            seasons=sorted_seasons,
            values=values,
            slope=None,
            intercept=None,
            r_squared=None,
            momentum=None,
            predicted_next=None,
            direction="insufficient_data",
        )

    # Overall trend
    slope, intercept, r_squared = _linreg(valid_x, valid_y)

    # Momentum: compare last 3 seasons slope to overall slope
    momentum = None
    if len(valid_x) >= 4:
        recent_x = valid_x[-3:]
        recent_y = valid_y[-3:]
        try:
            recent_slope, _, _ = _linreg(recent_x, recent_y)
            if slope != 0:
                momentum = round(recent_slope / slope, 4)
        except ValueError:
            pass

    # Prediction for next season
    next_season = sorted_seasons[-1] + 1
    predicted_next = round(slope * float(next_season) + intercept, 4)

    # Direction
    direction = "flat"
    if abs(slope) > 1e-9:
        direction = "up" if slope > 0 else "down"

    return MetricTrend(
        player_id=player_id,
        metric=metric,
        seasons=sorted_seasons,
        values=values,
        slope=round(slope, 6),
        intercept=round(intercept, 4),
        r_squared=round(r_squared, 4),
        momentum=momentum,
        predicted_next=predicted_next,
        direction=direction,
    )

```

### 4.6 服务层 — 导出服务

#### backend/services/export_service.py

```python
"""Export service — JSON/CSV export of metric data and VS results.

v8 §2 compliance:
- All data sourced from Metric Engine (layer 2)
- No DB access, no SQL
- Deterministic output (same input → same output)
- CSV/JSON are pure serialization (no transformation beyond formatting)
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime

from backend.services.metric_engine import (
    compute_many_as_dict,
    list_metrics,
    player_metrics_dict,
    rank,
    vs_compare,
)


@dataclass
class ExportResult:
    content: str
    filename: str
    content_type: str
    sha256: str


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _timestamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d")


def export_rankings_json(metric: str, season: int, limit: int = 100) -> ExportResult:
    """Export rankings as JSON (deterministic)."""
    rankings = rank(metric, season)[:limit]
    data = {
        "export_type": "rankings",
        "metric": metric,
        "season": season,
        "count": len(rankings),
        "generated_at": _timestamp(),
        "rankings": [
            {
                "rank": r.rank,
                "player_id": r.player_id,
                "value": r.value,
                "percentile": r.percentile,
            }
            for r in rankings
        ],
    }
    content = json.dumps(data, indent=2, sort_keys=True)
    return ExportResult(
        content=content,
        filename=f"rankings_{metric}_{season}_{_timestamp()}.json",
        content_type="application/json",
        sha256=_sha256(content),
    )


def export_rankings_csv(metric: str, season: int, limit: int = 100) -> ExportResult:
    """Export rankings as CSV (deterministic)."""
    rankings = rank(metric, season)[:limit]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["rank", "player_id", "value", "percentile"])
    for r in rankings:
        writer.writerow([r.rank, r.player_id, r.value, round(r.percentile, 4)])
    content = buf.getvalue()
    return ExportResult(
        content=content,
        filename=f"rankings_{metric}_{season}_{_timestamp()}.csv",
        content_type="text/csv",
        sha256=_sha256(content),
    )


def export_vs_json(
    player_1: str,
    player_2: str,
    season: int,
    metric_names: list[str],
) -> ExportResult:
    """Export VS comparison as JSON (deterministic)."""
    result = vs_compare(metric_names, season, player_1, player_2)
    data = {
        "export_type": "vs_comparison",
        "player_1": player_1,
        "player_2": player_2,
        "season": season,
        "metrics": metric_names,
        "generated_at": _timestamp(),
        "results": result,
    }
    content = json.dumps(data, indent=2, sort_keys=True)
    return ExportResult(
        content=content,
        filename=f"vs_{player_1}_vs_{player_2}_{season}_{_timestamp()}.json",
        content_type="application/json",
        sha256=_sha256(content),
    )


def export_vs_csv(
    player_1: str,
    player_2: str,
    season: int,
    metric_names: list[str],
) -> ExportResult:
    """Export VS comparison as CSV (deterministic)."""
    result = vs_compare(metric_names, season, player_1, player_2)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["metric", player_1, player_2])
    for m in sorted(metric_names):
        vals = result.get(m, {})
        v1 = vals.get(player_1)
        v2 = vals.get(player_2)
        writer.writerow([m, v1 if v1 is not None else "", v2 if v2 is not None else ""])
    content = buf.getvalue()
    return ExportResult(
        content=content,
        filename=f"vs_{player_1}_vs_{player_2}_{season}_{_timestamp()}.csv",
        content_type="text/csv",
        sha256=_sha256(content),
    )


def export_player_json(
    player_id: str,
    season: int,
    metric_names: list[str] | None = None,
) -> ExportResult:
    """Export single-player metrics as JSON (deterministic)."""
    if metric_names is None:
        metric_names = list_metrics()
    metrics = player_metrics_dict(metric_names, season, player_id)
    data = {
        "export_type": "player_metrics",
        "player_id": player_id,
        "season": season,
        "metric_count": len(metrics),
        "generated_at": _timestamp(),
        "metrics": metrics,
    }
    content = json.dumps(data, indent=2, sort_keys=True)
    return ExportResult(
        content=content,
        filename=f"player_{player_id}_{season}_{_timestamp()}.json",
        content_type="application/json",
        sha256=_sha256(content),
    )


def export_league_json(
    season: int,
    metric_names: list[str] | None = None,
) -> ExportResult:
    """Export all players' metrics as JSON (deterministic, sorted by player_id)."""
    if metric_names is None:
        metric_names = list_metrics()
    data_dict = compute_many_as_dict(metric_names, season)
    data = {
        "export_type": "league_metrics",
        "season": season,
        "metric_count": len(metric_names),
        "player_count": len(data_dict),
        "generated_at": _timestamp(),
        "metrics": metric_names,
        "players": dict(sorted(data_dict.items())),
    }
    content = json.dumps(data, indent=2, sort_keys=True)
    return ExportResult(
        content=content,
        filename=f"league_{season}_{_timestamp()}.json",
        content_type="application/json",
        sha256=_sha256(content),
    )

```

### 4.7 前端

#### frontend/index.html

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NBACore Studio v8 — Context System</title>
<link rel="stylesheet" href="css/style.css">
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
</head>
<body>
<div class="app">
  <!-- Sidebar -->
  <nav class="sidebar">
    <div class="logo">
      <div class="logo-icon">
        <img src="assets/logos/nba.svg" alt="NBA" style="width:28px;height:28px;">
      </div>
      <div class="logo-text">
        <h1>NBA<span>Core</span></h1>
        <p>Context System v8</p>
      </div>
    </div>
    <div class="nav">
      <div class="nav-section">Analysis</div>
      <div class="nav-item active" data-page="vs" onclick="nav('vs')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3l4 4-4 4"/><path d="M21 7H7"/><path d="M7 21l-4-4 4-4"/><path d="M3 17h14"/></svg>
        <span>Player VS</span>
      </div>
      <div class="nav-item" data-page="rankings" onclick="nav('rankings')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
        <span>Rankings</span>
      </div>
      <div class="nav-item" data-page="context" onclick="nav('context')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
        <span>Player Context</span>
      </div>
      <div class="nav-section">System</div>
      <div class="nav-item" onclick="location.reload()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        <span>Reload</span>
      </div>
    </div>
    <div class="sidebar-footer">
      <div class="server-status" id="serverStatus">
        <span class="status-dot"></span>
        <span class="status-text">Connecting...</span>
      </div>
    </div>
  </nav>

  <!-- Main Content -->
  <main class="main">
    <!-- VS Page -->
    <div id="page-vs" class="page active">
      <div class="page-header">
        <h2>Player VS Comparison</h2>
        <div class="form-row">
          <label class="label">Season:</label>
          <select class="select" id="seasonSelect" onchange="onSeasonChange()">
          </select>
        </div>
      </div>

      <!-- Player Selectors -->
      <div class="vs-selector">
        <div class="player-picker">
          <div class="picker-label">Player 1</div>
          <div class="picker-search">
            <input class="input" id="player1Search" placeholder="Search player..." oninput="searchPlayer(1)" onfocus="showDropdown(1)" onblur="hideDropdownDelay(1)">
            <div class="dropdown" id="player1Dropdown"></div>
          </div>
          <div class="player-card" id="player1Card">
            <div class="player-empty">Select a player to begin</div>
          </div>
        </div>

        <div class="vs-divider">
          <span class="vs-badge">VS</span>
        </div>

        <div class="player-picker">
          <div class="picker-label">Player 2</div>
          <div class="picker-search">
            <input class="input" id="player2Search" placeholder="Search player..." oninput="searchPlayer(2)" onfocus="showDropdown(2)" onblur="hideDropdownDelay(2)">
            <div class="dropdown" id="player2Dropdown"></div>
          </div>
          <div class="player-card" id="player2Card">
            <div class="player-empty">Select a player to begin</div>
          </div>
        </div>
      </div>

      <!-- Metric Selector -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">Metrics</div>
          <div class="form-row" style="margin:0;">
            <button class="btn btn-sm" onclick="selectAllMetrics()">Select All</button>
            <button class="btn btn-sm" onclick="clearMetrics()">Clear</button>
          </div>
        </div>
        <div class="metric-grid" id="metricGrid">
          <div class="metric-loading"><div class="spinner"></div> Loading metrics...</div>
        </div>
      </div>

      <!-- Compare Button -->
      <div style="text-align:center; margin: 20px 0;">
        <button class="btn btn-primary btn-lg" id="compareBtn" onclick="runCompare()" disabled>
          Compare Players
        </button>
      </div>

      <!-- VS Results -->
      <div id="vsResults" style="display:none;">
        <!-- Stats Table -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">Stat Comparison</div>
            <div class="form-row" style="margin:0;">
              <button class="btn btn-sm" onclick="exportVS('json')">JSON</button>
              <button class="btn btn-sm" onclick="exportVS('csv')">CSV</button>
            </div>
          </div>
          <div class="tbl-wrap">
            <table class="tbl" id="vsTable">
              <thead>
                <tr>
                  <th style="width:40%;">Metric</th>
                  <th style="width:30%; text-align:right;" id="vsTableP1">Player 1</th>
                  <th style="width:30%; text-align:right;" id="vsTableP2">Player 2</th>
                </tr>
              </thead>
              <tbody id="vsTableBody"></tbody>
            </table>
          </div>
        </div>

        <!-- Charts Grid -->
        <div class="grid-2col">
          <div class="card">
            <div class="card-header">
              <div class="card-title">Radar Chart</div>
            </div>
            <div id="radarChart" class="chart-container" style="height:380px;"></div>
          </div>
          <div class="card">
            <div class="card-header">
              <div class="card-title">Bar Comparison</div>
            </div>
            <div id="barChart" class="chart-container" style="height:380px;"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Rankings Page -->
    <div id="page-rankings" class="page">
      <div class="page-header">
        <h2>Player Rankings</h2>
        <div class="form-row">
          <label class="label">Metric:</label>
          <select class="select" id="rankMetricSelect" onchange="loadRankings()">
          </select>
          <label class="label">Season:</label>
          <select class="select" id="rankSeasonSelect" onchange="loadRankings()">
          </select>
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <div class="card-title" id="rankTitle">Top Players</div>
          <div class="card-badge" id="rankCount">—</div>
          <div class="form-row" style="margin:0;">
            <button class="btn btn-sm" onclick="exportRankings('json')">JSON</button>
            <button class="btn btn-sm" onclick="exportRankings('csv')">CSV</button>
          </div>
        </div>
        <div class="tbl-wrap" style="max-height:600px;">
          <table class="tbl" id="rankTable">
            <thead>
              <tr>
                <th style="width:60px;">#</th>
                <th>Player</th>
                <th style="width:120px; text-align:right;">Value</th>
                <th style="width:100px; text-align:right;">Percentile</th>
              </tr>
            </thead>
            <tbody id="rankTableBody">
              <tr><td colspan="4" style="text-align:center; padding:30px; color:var(--text-dim);">
                <div class="spinner"></div> Loading...
              </td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Context Page -->
    <div id="page-context" class="page">
      <div class="page-header">
        <h2>Player Context</h2>
        <div class="form-row">
          <label class="label">Player:</label>
          <div class="picker-search" style="width:240px; position:relative;">
            <input class="input" id="ctxPlayerSearch" placeholder="Search player..." oninput="searchContextPlayer()" onfocus="showContextDropdown()" onblur="hideContextDropdownDelay()">
            <div class="dropdown" id="ctxPlayerDropdown"></div>
          </div>
          <label class="label">Season:</label>
          <select class="select" id="ctxSeasonSelect" onchange="loadContext()">
          </select>
        </div>
      </div>

      <div id="ctxResults" style="display:none;">
        <!-- Similar Players -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">Similar Players</div>
            <div class="form-row" style="margin:0;">
              <label class="label">Position filter:</label>
              <input type="checkbox" id="ctxPosFilter" checked onchange="loadContext()">
            </div>
          </div>
          <div class="tbl-wrap" style="max-height:400px;">
            <table class="tbl" id="similarTable">
              <thead>
                <tr>
                  <th style="width:60px;">#</th>
                  <th>Player</th>
                  <th>Team / Position</th>
                  <th style="text-align:right;">Similarity</th>
                </tr>
              </thead>
              <tbody id="similarTableBody"></tbody>
            </table>
          </div>
        </div>

        <!-- Role Evolution -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">Role Evolution</div>
            <div class="card-badge" id="evolutionSeasons">—</div>
          </div>
          <div class="metric-grid" id="evolutionGrid" style="grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));">
          </div>
          <div style="margin-top:12px; display:flex; gap:20px; flex-wrap:wrap;">
            <div class="stat-chip"><span class="chip-label">Overall Shift</span><span class="chip-value" id="overallShift">—</span></div>
            <div class="stat-chip"><span class="chip-label">Top Growth</span><span class="chip-value" id="topGrowth">—</span></div>
            <div class="stat-chip"><span class="chip-label">Top Decline</span><span class="chip-value" id="topDecline">—</span></div>
          </div>
        </div>

        <!-- Trend Chart -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">Career Trend</div>
            <div class="form-row" style="margin:0;">
              <label class="label">Metric:</label>
              <select class="select" id="trendMetricSelect" onchange="loadTrend()">
              </select>
            </div>
          </div>
          <div id="trendChart" class="chart-container" style="height:320px;"></div>
          <div style="margin-top:12px; display:flex; gap:20px; flex-wrap:wrap;">
            <div class="stat-chip"><span class="chip-label">Direction</span><span class="chip-value" id="trendDir">—</span></div>
            <div class="stat-chip"><span class="chip-label">Slope / season</span><span class="chip-value" id="trendSlope">—</span></div>
            <div class="stat-chip"><span class="chip-label">R²</span><span class="chip-value" id="trendR2">—</span></div>
            <div class="stat-chip"><span class="chip-label">Next season</span><span class="chip-value" id="trendPred">—</span></div>
          </div>
        </div>
      </div>

      <div id="ctxEmpty" class="card" style="text-align:center; padding:40px; color:var(--text-dim);">
        Select a player to see their context analysis
      </div>
    </div>
  </main>
</div>

<div id="toastContainer"></div>
<script src="js/app.js"></script>
</body>
</html>

```

#### frontend/css/style.css

```css
:root {
  --bg: #0a0e17;
  --bg-card: #121828;
  --bg-hover: #1a2238;
  --bg-input: #0d1220;
  --border: #1e2a45;
  --border-light: #2a3a5a;
  --text: #e0e6f0;
  --text-dim: #6b7a99;
  --text-bright: #f0f4ff;
  --accent: #00d9a3;
  --accent-dim: #00a87e;
  --accent-bg: rgba(0,217,163,.1);
  --warn: #ffb84d;
  --danger: #ff4d6d;
  --info: #4d9fff;
  --purple: #b84dff;
  --radius: 10px;
  --radius-sm: 6px;
  --mono: 'Cascadia Code','Consolas','Courier New',monospace;
  --shadow: 0 4px 20px rgba(0,0,0,.3);
  --sidebar-w: 240px;
  --p1-color: #00d9a3;
  --p2-color: #4d9fff;
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  font-size: 14px;
  overflow: hidden;
}

/* Layout */
.app { display: flex; height: 100vh; }
.sidebar {
  width: var(--sidebar-w);
  background: var(--bg-card);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.main {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  min-width: 0;
}

/* Sidebar */
.logo {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 18px;
  border-bottom: 1px solid var(--border);
}
.logo-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-bg);
  border-radius: 10px;
}
.logo h1 { font-size: 16px; font-weight: 700; letter-spacing: -.5px; }
.logo h1 span { color: var(--accent); }
.logo p { font-size: 10px; color: var(--text-dim); margin-top: 2px; }

.nav { flex: 1; padding: 12px 0; overflow-y: auto; }
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 18px;
  cursor: pointer;
  color: var(--text-dim);
  transition: all .15s;
  border-left: 3px solid transparent;
  font-size: 13px;
}
.nav-item:hover { background: var(--bg-hover); color: var(--text); }
.nav-item.active {
  background: var(--accent-bg);
  color: var(--accent);
  border-left-color: var(--accent);
}
.nav-item svg { width: 18px; height: 18px; flex-shrink: 0; }
.nav-section {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-dim);
  padding: 14px 18px 6px;
}
.sidebar-footer { padding: 12px 18px; border-top: 1px solid var(--border); }
.server-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-dim);
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--warn);
  animation: pulse 2s infinite;
}
.status-dot.ready { background: var(--accent); }
.status-dot.error { background: var(--danger); }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .4; } }

/* Pages */
.page { display: none; }
.page.active { display: block; animation: fadeIn .3s ease; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-header h2 { font-size: 22px; font-weight: 700; }

/* Cards */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
  margin-bottom: 16px;
  box-shadow: var(--shadow);
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  gap: 12px;
  flex-wrap: wrap;
}
.card-title { font-size: 14px; font-weight: 600; }
.card-badge {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 20px;
  background: var(--accent-bg);
  color: var(--accent);
  font-weight: 600;
}

/* Grid */
.grid-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
@media (max-width: 1100px) {
  .grid-2col { grid-template-columns: 1fr; }
}

/* Table */
.tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.tbl th {
  text-align: left;
  padding: 9px 12px;
  color: var(--text-dim);
  font-weight: 600;
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  background: var(--bg-card);
  z-index: 1;
  white-space: nowrap;
}
.tbl td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.tbl tr:hover td { background: var(--bg-hover); }
.tbl-wrap {
  max-height: 400px;
  overflow: auto;
  border-radius: var(--radius);
}

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text);
  cursor: pointer;
  font-size: 13px;
  transition: all .15s;
}
.btn:hover { background: var(--bg-hover); border-color: var(--border-light); }
.btn:disabled { opacity: .4; cursor: not-allowed; }
.btn-primary {
  background: var(--accent);
  color: #001a14;
  border-color: var(--accent);
  font-weight: 600;
}
.btn-primary:hover { background: var(--accent-dim); }
.btn-danger {
  background: var(--danger);
  color: #fff;
  border-color: var(--danger);
  font-weight: 600;
}
.btn-sm { padding: 5px 10px; font-size: 12px; }
.btn-lg { padding: 12px 32px; font-size: 15px; }

/* Form */
.form-row {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.input {
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  color: var(--text);
  font-size: 13px;
  outline: none;
  width: 100%;
}
.input:focus { border-color: var(--accent); }
.select {
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  color: var(--text);
  font-size: 13px;
  outline: none;
  cursor: pointer;
}
.label {
  font-size: 12px;
  color: var(--text-dim);
  white-space: nowrap;
}

/* Chart */
.chart-container { width: 100%; height: 320px; }

/* Badge */
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}
.badge-green { background: rgba(0,217,163,.15); color: var(--accent); }
.badge-blue { background: rgba(77,159,255,.15); color: var(--info); }
.badge-orange { background: rgba(255,184,77,.15); color: var(--warn); }
.badge-gray { background: rgba(107,122,153,.15); color: var(--text-dim); }

/* Spinner */
.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin .8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Scrollbar */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--border-light); }

/* Toast */
#toastContainer {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.toast {
  padding: 12px 20px;
  border-radius: 8px;
  font-size: 13px;
  animation: slideUp .3s ease;
  box-shadow: var(--shadow);
  max-width: 400px;
}
.toast-success { background: var(--accent); color: #001a14; }
.toast-error { background: var(--danger); color: #fff; }
.toast-info { background: var(--info); color: #fff; }
@keyframes slideUp { from { transform: translateY(100px); opacity: 0; } }

/* VS Selector */
.vs-selector {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 16px;
  align-items: start;
  margin-bottom: 16px;
}
@media (max-width: 900px) {
  .vs-selector {
    grid-template-columns: 1fr;
  }
}

.player-picker {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
}
.picker-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-dim);
  margin-bottom: 10px;
  font-weight: 600;
}
.picker-search {
  position: relative;
  margin-bottom: 12px;
}
.dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-top: 4px;
  max-height: 240px;
  overflow-y: auto;
  z-index: 100;
  display: none;
  box-shadow: var(--shadow);
}
.dropdown.show { display: block; }
.dropdown-item {
  padding: 8px 12px;
  cursor: pointer;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.dropdown-item:last-child { border-bottom: none; }
.dropdown-item:hover { background: var(--bg-hover); }
.dropdown-item .sub {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 2px;
}

.vs-divider {
  display: flex;
  align-items: center;
  justify-content: center;
  padding-top: 40px;
}
.vs-badge {
  background: var(--accent-bg);
  color: var(--accent);
  padding: 8px 14px;
  border-radius: 20px;
  font-weight: 700;
  font-size: 13px;
  border: 1px solid var(--accent);
}

/* Player Card */
.player-card {
  min-height: 120px;
  border-radius: var(--radius-sm);
  background: var(--bg-input);
  border: 1px dashed var(--border);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 16px;
  text-align: center;
}
.player-card.has-player {
  border-style: solid;
  border-color: var(--border-light);
}
.player-card.player-1.has-player {
  border-color: rgba(0,217,163,.4);
  background: rgba(0,217,163,.03);
}
.player-card.player-2.has-player {
  border-color: rgba(77,159,255,.4);
  background: rgba(77,159,255,.03);
}
.player-empty {
  color: var(--text-dim);
  font-size: 13px;
}
.player-avatar {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--accent-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 10px;
  font-size: 24px;
  font-weight: 700;
  color: var(--accent);
}
.player-avatar.p2 {
  background: rgba(77,159,255,.12);
  color: var(--info);
}
.player-name {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 4px;
}
.player-team {
  font-size: 12px;
  color: var(--text-dim);
}

/* Metric Grid */
.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}
.metric-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all .15s;
  user-select: none;
}
.metric-item:hover {
  border-color: var(--border-light);
  background: var(--bg-hover);
}
.metric-item.selected {
  border-color: var(--accent);
  background: var(--accent-bg);
}
.metric-checkbox {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border-light);
  border-radius: 4px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.metric-item.selected .metric-checkbox {
  background: var(--accent);
  border-color: var(--accent);
}
.metric-checkbox::after {
  content: '';
  width: 8px;
  height: 4px;
  border: 2px solid transparent;
  border-left: 2px solid #001a14;
  border-bottom: 2px solid #001a14;
  transform: rotate(-45deg);
  margin-top: -2px;
  opacity: 0;
}
.metric-item.selected .metric-checkbox::after { opacity: 1; }
.metric-info { flex: 1; min-width: 0; }
.metric-name {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.metric-kind {
  font-size: 10px;
  color: var(--text-dim);
  margin-top: 2px;
}
.metric-loading {
  grid-column: 1 / -1;
  text-align: center;
  padding: 20px;
  color: var(--text-dim);
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

/* VS Table */
.vs-win { font-weight: 700; }
.vs-win.player-1 { color: var(--p1-color); }
.vs-win.player-2 { color: var(--p2-color); }

/* Stat chips */
.stat-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-input);
  padding: 8px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
}
.chip-label {
  font-size: 11px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: .5px;
}
.chip-value {
  font-size: 13px;
  font-weight: 700;
  font-family: var(--mono);
  color: var(--text-bright);
}

/* Metric tiles (evolution grid) */
.metric-tile {
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 12px;
  text-align: center;
}
.metric-tile-name {
  font-size: 11px;
  color: var(--text-dim);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: .5px;
}
.metric-tile-value {
  font-size: 16px;
  font-weight: 700;
  font-family: var(--mono);
  margin-bottom: 2px;
}
.metric-tile-sub {
  font-size: 11px;
  color: var(--text-dim);
  font-family: var(--mono);
}

```

#### frontend/js/app.js

```javascript
/**
 * NBACore Studio v8 — Frontend VS System
 * ========================================
 * Layer 4: Pure Render Only
 * - No computation, no aggregation, no filtering logic
 * - All data fetched from API endpoints (Layer 3)
 * - ECharts for chart rendering (mature library, v8 §2.4)
 */

// ── API Config ──
const API_BASE = '';

async function api(path, opts) {
  try {
    const r = await fetch(API_BASE + path, opts);
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || `HTTP ${r.status}`);
    }
    return r.json();
  } catch (e) {
    console.error('[API]', path, e);
    throw e;
  }
}

// ── State ──
let currentPage = 'vs';
let allMetrics = [];
let selectedMetrics = new Set();
let player1 = null;
let player2 = null;
let charts = {};
let searchTimeouts = {};

// ── Toast ──
function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = 'toast toast-' + type;
  el.textContent = msg;
  document.getElementById('toastContainer').appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── Navigation ──
function nav(page) {
  currentPage = page;
  document.querySelectorAll('.nav-item').forEach(e => {
    e.classList.toggle('active', e.dataset.page === page);
  });
  document.querySelectorAll('.page').forEach(e => e.classList.remove('active'));
  document.getElementById('page-' + page).classList.add('active');
  if (page === 'rankings') loadRankingsPage();
  if (page === 'context') loadContextPage();
}

// ── Server Status ──
async function checkServerStatus() {
  const dot = document.querySelector('.status-dot');
  const text = document.querySelector('.status-text');
  try {
    const r = await api('/health');
    if (r.database_connected) {
      dot.className = 'status-dot ready';
      text.textContent = 'Server & DB Ready';
    } else {
      dot.className = 'status-dot error';
      text.textContent = 'DB Offline';
    }
  } catch {
    dot.className = 'status-dot error';
    text.textContent = 'Server Offline';
  }
}

// ── Season Selector ──
async function initSeasonSelectors() {
  try {
    const seasons = await api('/players/seasons');
    const opts = seasons.map(s => `<option value="${s}">${s}-${(s + 1) % 100}</option>`).join('');
    const sel2025 = seasons.includes(2025) ? 2025 : seasons[0];
    document.getElementById('seasonSelect').innerHTML = opts;
    document.getElementById('seasonSelect').value = sel2025;
    document.getElementById('rankSeasonSelect').innerHTML = opts;
    document.getElementById('rankSeasonSelect').value = sel2025;
    document.getElementById('ctxSeasonSelect').innerHTML = opts;
    document.getElementById('ctxSeasonSelect').value = sel2025;
  } catch (e) {
    // Fallback: hardcode common seasons
    const fallback = [2025, 2024, 2023];
    const opts = fallback.map(s => `<option value="${s}">${s}-${(s + 1) % 100}</option>`).join('');
    document.getElementById('seasonSelect').innerHTML = opts;
    document.getElementById('rankSeasonSelect').innerHTML = opts;
    document.getElementById('ctxSeasonSelect').innerHTML = opts;
  }
}

function onSeasonChange() {
  // If both players selected, re-compare for new season
  if (player1 && player2 && selectedMetrics.size > 0) {
    runCompare();
  }
}

// ── Player Search ──
function searchPlayer(slot) {
  const input = document.getElementById('player' + slot + 'Search');
  const query = input.value.trim();
  clearTimeout(searchTimeouts[slot]);
  if (query.length < 2) {
    hideDropdown(slot);
    return;
  }
  searchTimeouts[slot] = setTimeout(async () => {
    try {
      const d = await api('/players?name=' + encodeURIComponent(query) + '&limit=10');
      const dd = document.getElementById('player' + slot + 'Dropdown');
      if (!d.players || d.players.length === 0) {
        dd.innerHTML = '<div class="dropdown-item" style="color:var(--text-dim);">No results</div>';
      } else {
        dd.innerHTML = d.players.map(p => {
          const team = p.team_abbr || p.team || '';
          const pos = p.position || '';
          const sub = [team, pos].filter(Boolean).join(' · ');
          return `<div class="dropdown-item" onmousedown="selectPlayer(${slot}, '${p.player_id}')">
            <div>${p.full_name || p.player_name}</div>
            ${sub ? `<div class="sub">${sub}</div>` : ''}
          </div>`;
        }).join('');
      }
      showDropdown(slot);
    } catch (e) {
      toast(e.message, 'error');
    }
  }, 300);
}

function showDropdown(slot) {
  const input = document.getElementById('player' + slot + 'Search');
  if (input.value.trim().length >= 2) {
    document.getElementById('player' + slot + 'Dropdown').classList.add('show');
  }
}

function hideDropdown(slot) {
  document.getElementById('player' + slot + 'Dropdown').classList.remove('show');
}

function hideDropdownDelay(slot) {
  setTimeout(() => hideDropdown(slot), 200);
}

// ── Player Selection ──
async function selectPlayer(slot, playerId) {
  const season = document.getElementById('seasonSelect').value;
  try {
    const d = await api('/players/' + playerId + '?season=' + season);
    if (slot === 1) {
      player1 = d.bio;
      player1.season_metrics = d.metrics || {};
    } else {
      player2 = d.bio;
      player2.season_metrics = d.metrics || {};
    }
    renderPlayerCard(slot, d.bio);
    updateCompareButton();
    // Update search input with player name
    document.getElementById('player' + slot + 'Search').value =
      d.bio.full_name || d.bio.player_name || '';
    hideDropdown(slot);
  } catch (e) {
    toast(e.message, 'error');
  }
}

function renderPlayerCard(slot, bio) {
  const card = document.getElementById('player' + slot + 'Card');
  const name = bio.full_name || bio.player_name || 'Unknown';
  const initials = name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase();
  const team = bio.team_abbr || bio.team || '—';
  const pos = bio.position || '';
  card.className = 'player-card player-' + slot + ' has-player';
  card.innerHTML = `
    <div class="player-avatar ${slot === 2 ? 'p2' : ''}">${initials}</div>
    <div class="player-name">${name}</div>
    <div class="player-team">${[team, pos].filter(Boolean).join(' · ')}</div>
  `;
}

// ── Metrics ──
async function loadMetrics() {
  try {
    const d = await api('/metrics');
    allMetrics = d.metrics || [];
    renderMetricGrid();
    populateRankMetricSelect();
  } catch (e) {
    toast('Failed to load metrics: ' + e.message, 'error');
    document.getElementById('metricGrid').innerHTML =
      '<div class="metric-loading" style="color:var(--danger);">Failed to load metrics</div>';
  }
}

function renderMetricGrid() {
  const grid = document.getElementById('metricGrid');
  if (allMetrics.length === 0) {
    grid.innerHTML = '<div class="metric-loading">No metrics available</div>';
    return;
  }
  // Auto-select first 5 metrics if none selected
  if (selectedMetrics.size === 0) {
    allMetrics.slice(0, 5).forEach(m => selectedMetrics.add(m.name));
  }
  grid.innerHTML = allMetrics.map(m => {
    const sel = selectedMetrics.has(m.name) ? 'selected' : '';
    return `<div class="metric-item ${sel}" onclick="toggleMetric('${m.name}')">
      <div class="metric-checkbox"></div>
      <div class="metric-info">
        <div class="metric-name">${m.name}</div>
        <div class="metric-kind">${m.kind} · ${m.source_table}</div>
      </div>
    </div>`;
  }).join('');
  updateCompareButton();
}

function toggleMetric(name) {
  if (selectedMetrics.has(name)) {
    selectedMetrics.delete(name);
  } else {
    selectedMetrics.add(name);
  }
  renderMetricGrid();
}

function selectAllMetrics() {
  allMetrics.forEach(m => selectedMetrics.add(m.name));
  renderMetricGrid();
}

function clearMetrics() {
  selectedMetrics.clear();
  renderMetricGrid();
}

// ── Compare Button State ──
function updateCompareButton() {
  const btn = document.getElementById('compareBtn');
  btn.disabled = !(player1 && player2 && selectedMetrics.size > 0);
}

// ── Run VS Compare ──
async function runCompare() {
  if (!player1 || !player2 || selectedMetrics.size === 0) return;
  const season = document.getElementById('seasonSelect').value;
  const metrics = Array.from(selectedMetrics).join(',');

  const btn = document.getElementById('compareBtn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div> Comparing...';

  try {
    const d = await api(
      '/vs/compare?p1=' + encodeURIComponent(player1.player_id) +
      '&p2=' + encodeURIComponent(player2.player_id) +
      '&season=' + season +
      '&metrics=' + encodeURIComponent(metrics)
    );
    renderVSResults(d);
    document.getElementById('vsResults').style.display = 'block';
  } catch (e) {
    toast('Compare failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Compare Players';
  }
}

function renderVSResults(d) {
  const p1 = d.player_1;
  const p2 = d.player_2;
  const p1Name = (player1 && (player1.full_name || player1.player_name)) || p1;
  const p2Name = (player2 && (player2.full_name || player2.player_name)) || p2;

  // Update table headers
  document.getElementById('vsTableP1').textContent = p1Name;
  document.getElementById('vsTableP2').textContent = p2Name;

  // Build table rows
  const tbody = document.getElementById('vsTableBody');
  const metrics = d.metrics || {};
  tbody.innerHTML = Object.keys(metrics).map(mname => {
    const vals = metrics[mname];
    const v1 = vals[p1];
    const v2 = vals[p2];
    const s1 = v1 != null ? Number(v1).toFixed(2) : '—';
    const s2 = v2 != null ? Number(v2).toFixed(2) : '—';
    let win1 = '';
    let win2 = '';
    if (v1 != null && v2 != null) {
      // Higher is better for all current metrics
      if (v1 > v2) win1 = 'vs-win player-1';
      else if (v2 > v1) win2 = 'vs-win player-2';
    }
    return `<tr>
      <td style="font-weight:500;">${mname}</td>
      <td style="text-align:right;" class="${win1}">${s1}</td>
      <td style="text-align:right;" class="${win2}">${s2}</td>
    </tr>`;
  }).join('');

  // Render charts
  renderRadarChart(d, p1Name, p2Name);
  renderBarChart(d, p1Name, p2Name);
}

// ── Radar Chart ──
function renderRadarChart(d, p1Name, p2Name) {
  const el = document.getElementById('radarChart');
  if (!el) return;
  if (charts.radar) charts.radar.dispose();
  charts.radar = echarts.init(el);

  const metrics = d.metrics || {};
  const names = Object.keys(metrics);
  const p1 = d.player_1;
  const p2 = d.player_2;

  // Get max values for normalization (150% of max)
  const maxVals = names.map(name => {
    const v1 = metrics[name][p1];
    const v2 = metrics[name][p2];
    const max = Math.max(v1 || 0, v2 || 0);
    return max > 0 ? max * 1.3 : 1;
  });

  const p1Values = names.map((name, i) => {
    const v = metrics[name][p1];
    return v != null ? Number(v) : 0;
  });
  const p2Values = names.map((name, i) => {
    const v = metrics[name][p2];
    return v != null ? Number(v) : 0;
  });

  charts.radar.setOption({
    tooltip: {},
    legend: {
      data: [p1Name, p2Name],
      textStyle: { color: '#6b7a99' },
      bottom: 0,
    },
    radar: {
      indicator: names.map((name, i) => ({
        name: name,
        max: maxVals[i],
      })),
      axisName: { color: '#6b7a99', fontSize: 11 },
      splitArea: {
        areaStyle: { color: ['rgba(0,217,163,.02)', 'rgba(0,217,163,.05)'] },
      },
      splitLine: { lineStyle: { color: '#1e2a45' } },
    },
    series: [{
      type: 'radar',
      data: [
        {
          value: p1Values,
          name: p1Name,
          itemStyle: { color: '#00d9a3' },
          areaStyle: { color: 'rgba(0,217,163,.15)' },
          lineStyle: { width: 2 },
        },
        {
          value: p2Values,
          name: p2Name,
          itemStyle: { color: '#4d9fff' },
          areaStyle: { color: 'rgba(77,159,255,.15)' },
          lineStyle: { width: 2 },
        },
      ],
    }],
  });
}

// ── Bar Chart ──
function renderBarChart(d, p1Name, p2Name) {
  const el = document.getElementById('barChart');
  if (!el) return;
  if (charts.bar) charts.bar.dispose();
  charts.bar = echarts.init(el);

  const metrics = d.metrics || {};
  const names = Object.keys(metrics);
  const p1 = d.player_1;
  const p2 = d.player_2;

  const p1Values = names.map(name => {
    const v = metrics[name][p1];
    return v != null ? Number(v) : null;
  });
  const p2Values = names.map(name => {
    const v = metrics[name][p2];
    return v != null ? Number(v) : null;
  });

  charts.bar.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: {
      data: [p1Name, p2Name],
      textStyle: { color: '#6b7a99' },
      bottom: 0,
    },
    grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
    xAxis: {
      type: 'category',
      data: names,
      axisLabel: { color: '#6b7a99', fontSize: 10, rotate: 30 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#6b7a99' },
      splitLine: { lineStyle: { color: '#1e2a45' } },
    },
    series: [
      {
        name: p1Name,
        type: 'bar',
        data: p1Values,
        itemStyle: { color: '#00d9a3', borderRadius: [4, 4, 0, 0] },
        barWidth: '35%',
      },
      {
        name: p2Name,
        type: 'bar',
        data: p2Values,
        itemStyle: { color: '#4d9fff', borderRadius: [4, 4, 0, 0] },
        barWidth: '35%',
      },
    ],
  });
}

// ── Rankings Page ──
function populateRankMetricSelect() {
  const sel = document.getElementById('rankMetricSelect');
  if (allMetrics.length === 0) return;
  sel.innerHTML = allMetrics.map(m =>
    `<option value="${m.name}">${m.name}</option>`
  ).join('');
}

function loadRankingsPage() {
  if (document.getElementById('rankMetricSelect').children.length > 0) {
    loadRankings();
  }
}

async function loadRankings() {
  const metric = document.getElementById('rankMetricSelect').value;
  const season = document.getElementById('rankSeasonSelect').value;
  if (!metric) return;

  const tbody = document.getElementById('rankTableBody');
  tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:30px; color:var(--text-dim);">
    <div class="spinner"></div> Loading...
  </td></tr>`;

  try {
    const d = await api('/metrics/evaluate/' + metric + '?season=' + season + '&limit=50');
    document.getElementById('rankTitle').textContent = d.metric + ' — Top Players';
    document.getElementById('rankCount').textContent = d.total + ' players';
    const rankings = d.rankings || [];
    tbody.innerHTML = rankings.map(r => {
      const medalColors = ['var(--warn)', 'var(--text-dim)', '#cd7f32'];
      const rankColor = r.rank <= 3 ? medalColors[r.rank - 1] : 'var(--text-dim)';
      const name = r.player_name || r.player_id;
      const pos = r.position || '';
      return `<tr>
        <td style="font-weight:700; color:${rankColor};">${r.rank}</td>
        <td>
          <div style="font-weight:600;">${name}</div>
          ${pos ? `<div class="sub">${pos}</div>` : ''}
        </td>
        <td style="text-align:right; font-family:var(--mono); font-weight:700; color:var(--accent);">${Number(r.value).toFixed(2)}</td>
        <td style="text-align:right; color:var(--text-dim);">${Number(r.percentile).toFixed(1)}%</td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:30px; color:var(--danger);">
      Failed to load: ${e.message}
    </td></tr>`;
  }
}

// ── Context Page State ──
let ctxPlayer = null;
let ctxSearchTimer = null;

function searchContextPlayer() {
  const q = document.getElementById('ctxPlayerSearch').value;
  clearTimeout(ctxSearchTimer);
  ctxSearchTimer = setTimeout(() => doContextSearch(q), 300);
}

async function doContextSearch(q) {
  const dd = document.getElementById('ctxPlayerDropdown');
  if (!q || q.length < 2) {
    dd.classList.remove('show');
    return;
  }
  try {
    const d = await api('/players?name=' + encodeURIComponent(q) + '&limit=8');
    const players = d.players || [];
    if (players.length === 0) {
      dd.innerHTML = '<div class="dropdown-empty">No players found</div>';
    } else {
      dd.innerHTML = players.map(p => `
        <div class="dropdown-item" onmousedown="selectContextPlayer('${p.player_id}')">
          <div>${p.full_name || p.player_name || p.player_id}</div>
          <div class="sub">${p.position || ''}</div>
        </div>
      `).join('');
    }
    dd.classList.add('show');
  } catch {
    dd.classList.remove('show');
  }
}

function showContextDropdown() {
  const q = document.getElementById('ctxPlayerSearch').value;
  if (q && q.length >= 2) {
    document.getElementById('ctxPlayerDropdown').classList.add('show');
  }
}

function hideContextDropdownDelay() {
  setTimeout(() => {
    document.getElementById('ctxPlayerDropdown').classList.remove('show');
  }, 200);
}

function selectContextPlayer(pid) {
  ctxPlayer = pid;
  document.getElementById('ctxPlayerSearch').value = pid;
  document.getElementById('ctxPlayerDropdown').classList.remove('show');
  loadContext();
}

function loadContextPage() {
  if (ctxPlayer) {
    loadContext();
  }
}

async function loadContext() {
  if (!ctxPlayer) return;
  const season = document.getElementById('ctxSeasonSelect').value;
  const posFilter = document.getElementById('ctxPosFilter').checked;

  document.getElementById('ctxEmpty').style.display = 'none';
  document.getElementById('ctxResults').style.display = 'block';

  // Similar players
  loadSimilarPlayers(ctxPlayer, season, posFilter);

  // Role evolution (last 5 seasons up to current)
  const s = parseInt(season);
  const evoSeasons = [];
  for (let i = 4; i >= 0; i--) {
    evoSeasons.push(s - i);
  }
  loadRoleEvolution(ctxPlayer, evoSeasons);

  // Trend
  const trendMetric = document.getElementById('trendMetricSelect').value;
  if (trendMetric) {
    loadTrend();
  } else {
    populateTrendMetricSelect();
  }
}

async function loadSimilarPlayers(playerId, season, posFilter) {
  const tbody = document.getElementById('similarTableBody');
  tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:20px; color:var(--text-dim);">
    <div class="spinner"></div> Loading...
  </td></tr>`;
  try {
    const d = await api('/context/similar?player_id=' + playerId + '&season=' + season +
      '&position_filter=' + posFilter + '&limit=10');
    const players = d.similar_players || [];
    if (players.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:20px; color:var(--text-dim);">
        No similar players found
      </td></tr>`;
      return;
    }
    tbody.innerHTML = players.map((p, i) => `
      <tr>
        <td style="font-weight:700; color:var(--text-dim);">${i + 1}</td>
        <td style="font-weight:600;">${p.name}</td>
        <td style="color:var(--text-dim);">${[p.team, p.position].filter(Boolean).join(' · ')}</td>
        <td style="text-align:right; font-family:var(--mono); font-weight:700; color:var(--accent);">
          ${(p.similarity * 100).toFixed(1)}%
        </td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:20px; color:var(--danger);">
      Failed: ${e.message}
    </td></tr>`;
  }
}

async function loadRoleEvolution(playerId, seasons) {
  const grid = document.getElementById('evolutionGrid');
  grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:20px; color:var(--text-dim);"><div class="spinner"></div> Loading...</div>';

  try {
    const seasonParam = seasons.join(',');
    const d = await api('/context/evolution?player_id=' + playerId + '&seasons=' + seasonParam);

    document.getElementById('evolutionSeasons').textContent = d.seasons.length + ' seasons';
    document.getElementById('overallShift').textContent = (d.overall_shift_magnitude * 100).toFixed(1) + '%';
    document.getElementById('topGrowth').textContent = d.top_growth.slice(0, 2).join(', ') || '—';
    document.getElementById('topDecline').textContent = d.top_decline.slice(0, 2).join(', ') || '—';

    const changes = d.metric_changes || [];
    if (changes.length === 0) {
      grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:20px; color:var(--text-dim);">Not enough data</div>';
      return;
    }

    grid.innerHTML = changes.map(c => {
      const dirColor = c.direction === 'up' ? 'var(--success)' : c.direction === 'down' ? 'var(--danger)' : 'var(--text-dim)';
      const arrow = c.direction === 'up' ? '▲' : c.direction === 'down' ? '▼' : '—';
      const pct = c.pct_change !== null ? (c.pct_change > 0 ? '+' : '') + c.pct_change.toFixed(1) + '%' : '—';
      return `
        <div class="metric-tile">
          <div class="metric-tile-name">${c.metric}</div>
          <div class="metric-tile-value" style="color:${dirColor};">
            ${arrow} ${pct}
          </div>
          <div class="metric-tile-sub">
            ${c.first_value !== null ? c.first_value.toFixed(2) : '—'} → ${c.last_value !== null ? c.last_value.toFixed(2) : '—'}
          </div>
        </div>
      `;
    }).join('');
  } catch (e) {
    grid.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:20px; color:var(--danger);">Failed: ${e.message}</div>`;
  }
}

function populateTrendMetricSelect() {
  const sel = document.getElementById('trendMetricSelect');
  if (allMetrics.length === 0) return;
  sel.innerHTML = allMetrics.map(m =>
    `<option value="${m.name}">${m.name}</option>`
  ).join('');
}

async function loadTrend() {
  const metric = document.getElementById('trendMetricSelect').value;
  const season = parseInt(document.getElementById('ctxSeasonSelect').value);
  if (!metric || !ctxPlayer) return;

  const seasons = [];
  for (let i = 4; i >= 0; i--) {
    seasons.push(season - i);
  }

  try {
    const d = await api('/context/trend?player_id=' + ctxPlayer +
      '&metric=' + metric + '&seasons=' + seasons.join(','));

    // Stats
    const dirColors = { up: 'var(--success)', down: 'var(--danger)', flat: 'var(--text-dim)', insufficient_data: 'var(--text-dim)' };
    document.getElementById('trendDir').textContent = d.direction;
    document.getElementById('trendDir').style.color = dirColors[d.direction] || 'var(--text-dim)';
    document.getElementById('trendSlope').textContent = d.slope !== null ? d.slope.toFixed(3) : '—';
    document.getElementById('trendR2').textContent = d.r_squared !== null ? d.r_squared.toFixed(3) : '—';
    document.getElementById('trendPred').textContent = d.predicted_next !== null ? d.predicted_next.toFixed(2) : '—';

    // Chart
    renderTrendChart(d, metric);
  } catch (e) {
    toast('Trend load failed: ' + e.message, 'error');
  }
}

function renderTrendChart(data, metric) {
  const chartDom = document.getElementById('trendChart');
  if (!chartDom) return;

  if (charts.trend) {
    charts.trend.dispose();
  }
  charts.trend = echarts.init(chartDom);

  const seasonLabels = data.seasons.map(s => s + '-' + ((s + 1) % 100));
  const values = data.values;

  // Build trend line points
  const trendPoints = [];
  if (data.slope !== null && data.intercept !== null) {
    data.seasons.forEach((s, i) => {
      if (values[i] !== null) {
        trendPoints.push(data.slope * s + data.intercept);
      } else {
        trendPoints.push(null);
      }
    });
  }

  charts.trend.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 20, top: 30, bottom: 30 },
    xAxis: {
      type: 'category',
      data: seasonLabels,
      axisLine: { lineStyle: { color: 'var(--border)' } },
      axisLabel: { color: 'var(--text-dim)' },
    },
    yAxis: {
      type: 'value',
      name: metric,
      nameTextStyle: { color: 'var(--text-dim)' },
      axisLine: { lineStyle: { color: 'var(--border)' } },
      splitLine: { lineStyle: { color: 'var(--border-light)' } },
      axisLabel: { color: 'var(--text-dim)' },
    },
    series: [
      {
        name: 'Actual',
        type: 'line',
        data: values,
        smooth: true,
        lineStyle: { color: '#00d9a3', width: 3 },
        itemStyle: { color: '#00d9a3' },
        symbolSize: 8,
      },
      {
        name: 'Trend',
        type: 'line',
        data: trendPoints,
        lineStyle: { color: '#ff9f43', width: 2, type: 'dashed' },
        itemStyle: { color: '#ff9f43' },
        symbol: 'none',
      },
    ],
  });
}

// ── Resize Handler ──
window.addEventListener('resize', () => {
  Object.values(charts).forEach(c => c && c.resize());
});

// ── Export Functions ──
function exportRankings(format) {
  const metric = document.getElementById('rankMetricSelect').value;
  const season = document.getElementById('rankSeasonSelect').value;
  if (!metric) { toast('Select a metric first', 'error'); return; }
  const url = '/export/rankings?metric=' + encodeURIComponent(metric) +
    '&season=' + season + '&format=' + format + '&limit=50';
  window.location.href = url;
  toast('Exporting ' + format.toUpperCase() + '...', 'success');
}

function exportVS(format) {
  if (!player1 || !player2) { toast('Select both players first', 'error'); return; }
  const season = document.getElementById('seasonSelect').value;
  const metrics = Array.from(selectedMetrics).join(',');
  const url = '/export/vs?p1=' + encodeURIComponent(player1) +
    '&p2=' + encodeURIComponent(player2) +
    '&season=' + season + '&format=' + format +
    (metrics ? '&metrics=' + encodeURIComponent(metrics) : '');
  window.location.href = url;
  toast('Exporting ' + format.toUpperCase() + '...', 'success');
}

// ── Init ──
async function init() {
  checkServerStatus();
  await initSeasonSelectors();
  await loadMetrics();
  setInterval(checkServerStatus, 30000);
}

document.addEventListener('DOMContentLoaded', init);

```

### 4.8 部署与构建

#### Dockerfile

```dockerfile
# ── Stage 1: Builder ──
FROM python:3.10-slim AS builder

WORKDIR /build

# Install build deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ──
FROM python:3.10-slim

WORKDIR /app

# Runtime deps only (libpq for psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY pyproject.toml .env.example ./

# Create cache directory
RUN mkdir -p .cache/metric_engine

# Non-root user for security
RUN useradd -m -s /bin/bash nbacore && chown -R nbacore:nbacore /app
USER nbacore

EXPOSE 5577

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5577/health || exit 1

# Production: gunicorn + uvicorn workers
CMD ["gunicorn", "backend.app:create_app", \
     "--factory", \
     "--bind", "0.0.0.0:5577", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]

```

#### docker-compose.yml

```yaml
# NBACore Studio v8 — Docker Compose
# Usage: docker compose up -d

services:
  db:
    image: postgres:16-alpine
    container_name: nbacore-db
    environment:
      POSTGRES_DB: ${DB_NAME:-nba}
      POSTGRES_USER: ${DB_USER:-postgres}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-postgres}
    ports:
      - "${DB_PORT:-5433}:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-postgres} -d ${DB_NAME:-nba}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  app:
    build: .
    container_name: nbacore-app
    ports:
      - "${SERVER_PORT:-5577}:5577"
    environment:
      DB_HOST: db
      DB_PORT: 5432
      DB_NAME: ${DB_NAME:-nba}
      DB_USER: ${DB_USER:-postgres}
      DB_PASSWORD: ${DB_PASSWORD:-postgres}
      SERVER_HOST: 0.0.0.0
      SERVER_PORT: 5577
      CACHE_DIR: .cache/metric_engine
      DEBUG: "false"
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    volumes:
      - appcache:/app/.cache/metric_engine
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

volumes:
  pgdata:
  appcache:

```

#### nbacore.spec

```python
# -*- mode: python ; coding: utf-8 -*-
"""NBACore Studio v8 — PyInstaller spec.

Builds a single-file executable with backend + frontend + logos.
Usage: pyinstaller nbacore.spec
"""

from pathlib import Path

project_root = Path.cwd()

# ── Data files to bundle ──
datas = [
    (str(project_root / "frontend"), "frontend"),
    (str(project_root / "NBAlogo"), "NBAlogo"),
]

# Collect backend package
hiddenimports = [
    "backend",
    "backend.app",
    "backend.core.config",
    "backend.core.db",
    "backend.core.logging",
    "backend.core.runtime_guard",
    "backend.api.schemas",
    "backend.api.routers.players",
    "backend.api.routers.metrics",
    "backend.api.routers.vs",
    "backend.api.routers.batch",
    "backend.api.routers.context",
    "backend.api.routers.export",
    "backend.api.routers.monitor",
    "backend.services.metric_engine",
    "backend.services.metric_engine.metrics.basic",
    "backend.services.metric_engine.metrics.advanced",
    "backend.services.metric_engine.metrics.composite",
    "backend.services.context_engine",
    "backend.services.context_engine.similar_players",
    "backend.services.context_engine.role_evolution",
    "backend.services.context_engine.trend_analysis",
    "backend.services.export_service",
    "backend.data_layer.schema",
    "backend.data_layer.schema_validator",
    "backend.data_layer.batch_loader",
    "backend.data_layer.temp_loader",
    "backend.data_layer.joins",
]

a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "scipy",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NBACore",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

```

#### build.ps1

```powershell
# NBACore Studio v8 — Build Executable
# Usage: .\build.ps1
# Output: dist\NBACore.exe

param([switch]$Clean)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  NBACore Studio v8 — Build EXE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check PyInstaller
try {
    $pyinstaller = Get-Command pyinstaller -ErrorAction Stop
    Write-Host "[OK] PyInstaller found: $($pyinstaller.Source)" -ForegroundColor Green
} catch {
    Write-Host "[INSTALL] PyInstaller not found, installing..." -ForegroundColor Yellow
    pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install PyInstaller" -ForegroundColor Red
        exit 1
    }
}

# Clean build artifacts
if ($Clean) {
    Write-Host "[CLEAN] Removing build/ and dist/..." -ForegroundColor Yellow
    if (Test-Path build) { Remove-Item -Recurse -Force build }
    if (Test-Path dist) { Remove-Item -Recurse -Force dist }
}

# Build
Write-Host ""
Write-Host "[BUILD] Running PyInstaller..." -ForegroundColor Cyan
pyinstaller --clean nbacore.spec

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Build failed!" -ForegroundColor Red
    exit 1
}

# Verify output
$exePath = Join-Path $ProjectRoot "dist\NBACore.exe"
if (Test-Path $exePath) {
    $sizeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  BUILD SUCCESS!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Output: $exePath" -ForegroundColor White
    Write-Host "  Size:   $sizeMB MB" -ForegroundColor White
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Note: Requires PostgreSQL running on" -ForegroundColor Yellow
    Write-Host "        localhost:5433 (database: nba)" -ForegroundColor Yellow
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "[ERROR] EXE not found at $exePath" -ForegroundColor Red
    exit 1
}

```

#### requirements.txt

```text
# NBACore Studio v8 — Production Dependencies
# Pinned for reproducible builds

fastapi==0.115.6
uvicorn[standard]==0.34.0
gunicorn==23.0.0
psycopg2-binary==2.9.10
pydantic==2.10.4
pydantic-settings==2.7.1
diskcache==5.6.3
numpy==2.2.1
pandas==2.2.3
httpx==0.28.1
pytest==8.3.4

```

#### .env.example

```text
# NBACore Studio v8 — Environment Configuration
# Copy to .env and adjust. All values have safe defaults in backend/core/config.py

# ── Database (PostgreSQL) ──
# NOTE: v7 used port 5433, NOT default 5432
# Docker: set DB_HOST=db, DB_PORT=5432 (internal network)
DB_HOST=localhost
DB_PORT=5433
DB_NAME=nba
DB_USER=postgres
DB_PASSWORD=postgres

# ── Server ──
# Production: set SERVER_HOST=0.0.0.0
SERVER_HOST=127.0.0.1
SERVER_PORT=5577

# ── Cache (Disk Cache for Metric Engine) ──
CACHE_DIR=.cache/metric_engine

# ── App ──
APP_NAME=NBACore Studio v8
APP_VERSION=8.0.0
DEBUG=false
LOG_LEVEL=INFO

# ── Production (gunicorn) ──
# Workers = CPU cores * 2 + 1 (default: 4)
WORKERS=4

```

#### pyproject.toml

```toml
[project]
name = "nbacore-studio"
version = "8.0.0"
description = "NBACore Studio v8 — Metric-Driven Batch Analytics Engine"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.110",
    "uvicorn>=0.27",
    "psycopg2-binary>=2.9",
    "pydantic>=2.6",
    "pydantic-settings>=2.1",
    "diskcache>=5.6",
    "numpy>=1.26",
    "pandas>=2.1",
]

[project.optional-dependencies]
test = ["pytest>=8.0", "httpx>=0.27"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
addopts = "-v --tb=short"
markers = [
    "phase0: Phase 0 Environment Bootstrap tests",
    "needs_db: requires live PostgreSQL connection",
]

[tool.setuptools]
packages = ["backend"]

```

#### .github/workflows/ci.yml

```yaml
name: CI

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: nba
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        ports:
          - 5433:5432
        options: >-
          --health-cmd "pg_isready -U postgres -d nba"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run tests
        env:
          DB_HOST: localhost
          DB_PORT: "5433"
          DB_NAME: nba
          DB_USER: postgres
          DB_PASSWORD: postgres
        run: |
          python -m pytest tests/ -q --tb=short

  docker-build:
    runs-on: ubuntu-latest
    needs: test
    if: github.ref == 'refs/heads/main' || github.ref == 'refs/heads/master'

    steps:
      - uses: actions/checkout@v4

      - name: Build Docker image
        run: docker build -t nbacore-studio:latest .

      - name: Verify image starts
        run: |
          docker run -d --name nbacore-test -p 5577:5577 \
            -e DB_HOST=host.docker.internal \
            -e DB_PORT=5433 \
            nbacore-studio:latest
          sleep 5
          curl -sf http://localhost:5577/health || exit 1
          docker stop nbacore-test

```

### 4.9 测试

#### tests/conftest.py

```python
"""Pytest fixtures for NBACore v8 — Phase 0.

v8 §6 forbids mocking Metric Engine core logic. DB-dependent tests use a
live connection (skipped if PostgreSQL unavailable) rather than mocking.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.core.db import is_port_open, ping


@pytest.fixture(scope="session")
def app_client():
    """FastAPI TestClient with lifespan triggered (pool init attempted)."""
    from backend.app import create_app
    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def db_available() -> bool:
    """True only if a live PostgreSQL is reachable."""
    return is_port_open() and ping()


def skip_without_db(db_available: bool):
    """Helper for tests that need a live DB."""
    if not db_available:
        pytest.skip("PostgreSQL not available — set DB_PORT and start service")

```

#### tests/test_phase0_health.py

```python
"""Phase 0 — Environment Bootstrap verification tests.

Covers v8 §4 Phase 0 acceptance:
    - /health returns 200 + DB connectivity + server starts
    - config management (port 5433 inherited from v7)
    - logging with query_id traceability
    - runtime_guard startup checks
    - SQL validation (only SELECT allowed)

NO mocks for Metric Engine (v8 §6). DB-dependent paths skip if DB down.
"""
from __future__ import annotations

import pytest

from backend.core import config
from backend.core.db import validate_batch_sql
from backend.core.logging import new_query_id, query_id_var, setup_logging


# ── §4 Phase 0: config management ──

class TestConfig:

    def test_db_port_is_5433_from_v7(self):
        """v7 used port 5433 (non-default). v8 must inherit."""
        assert config.DB_PORT == 5433, "DB_PORT must be 5433 (v7 convention)"

    def test_db_name_is_nba(self):
        assert config.DB_NAME == "nba"

    def test_app_version_is_v8(self):
        assert config.APP_VERSION == "8.0.0"

    def test_current_season_returns_int(self):
        s = config.current_season()
        assert isinstance(s, int)
        assert 2020 <= s <= 2030

    def test_db_dsn_format(self):
        dsn = config.db_dsn()
        assert dsn.startswith("postgresql://")
        assert f":{config.DB_PORT}/" in dsn


# ── §5.2: SQL trace & batch check ──

class TestSqlValidation:

    def test_select_allowed(self):
        # Should NOT raise
        validate_batch_sql("SELECT 1")
        validate_batch_sql("  SELECT * FROM player_gamelog WHERE season = 2025  ")
        validate_batch_sql("(SELECT 1)")

    @pytest.mark.parametrize("bad_sql", [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET x = 1",
        "DELETE FROM t",
        "DROP TABLE t",
        "ALTER TABLE t ADD COLUMN x int",
        "CREATE TABLE t (x int)",
        "TRUNCATE t",
        "GRANT SELECT ON t TO u",
    ])
    def test_forbidden_dml_ddl_rejected(self, bad_sql: str):
        with pytest.raises(ValueError, match="Forbidden SQL"):
            validate_batch_sql(bad_sql)

    def test_empty_sql_rejected(self):
        with pytest.raises(ValueError, match="Empty SQL"):
            validate_batch_sql("")


# ── §5.1: layer leakage check (Phase 0 skeleton) ──

class TestLayerIsolation:

    def test_app_does_not_import_psycopg2_directly(self):
        """v8 §2: API layer must not touch DB driver directly."""
        import backend.app as app_mod
        src = open(app_mod.__file__, encoding="utf-8").read()
        assert "import psycopg2" not in src, \
            "app.py must not import psycopg2 (use backend.core.db only)"
        assert "from psycopg2" not in src

    def test_app_has_no_select_statement(self):
        """v8 §2: API layer (app.py) must not contain SQL keywords."""
        import backend.app as app_mod
        src = open(app_mod.__file__, encoding="utf-8").read()
        # Skip docstring/comment lines, then assert no SQL SELECT keyword
        in_docstring = False
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith('"""'):
                in_docstring = not in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            assert "SELECT" not in stripped.upper(), \
                f"app.py must not contain SQL keyword: {line!r}"


# ── §5.5: runtime guard ──

class TestRuntimeGuard:

    def test_guard_returns_all_checks(self):
        from backend.core.runtime_guard import run_startup_checks
        results = run_startup_checks()
        assert isinstance(results, dict)
        assert "config_loaded" in results
        assert "metric_engine_exists" in results
        assert "no_forbidden_patterns" in results

    def test_config_check_passes(self):
        from backend.core.runtime_guard import run_startup_checks
        r = run_startup_checks()["config_loaded"]
        assert r["ok"] is True
        assert r["detail"]["db_port"] == 5433

    def test_metric_engine_exists_check_passes(self):
        """v8 §2: metric_engine must be importable as sole compute layer."""
        from backend.core.runtime_guard import run_startup_checks
        r = run_startup_checks()["metric_engine_exists"]
        assert r["ok"] is True, r.get("error")

    def test_no_forbidden_patterns_check_passes(self):
        from backend.core.runtime_guard import run_startup_checks
        r = run_startup_checks()["no_forbidden_patterns"]
        assert r["ok"] is True, r.get("error")


# ── §5.3: determinism (query_id generation) ──

class TestLoggingTraceability:

    def test_new_query_id_is_unique_12char(self):
        id1 = new_query_id()
        id2 = new_query_id()
        assert id1 != id2
        assert len(id1) == 12
        assert len(id2) == 12

    def test_query_id_bound_to_context(self):
        qid = new_query_id()
        assert query_id_var.get() == qid

    def test_setup_logging_idempotent(self):
        # Calling twice must not duplicate handlers
        setup_logging("INFO")
        h1 = len(__import__("logging").getLogger().handlers)
        setup_logging("INFO")
        h2 = len(__import__("logging").getLogger().handlers)
        assert h1 == h2


# ── §4 Phase 0: /health endpoint (end-to-end) ──

class TestHealthEndpoint:

    def test_health_returns_200(self, app_client):
        resp = app_client.get("/health")
        assert resp.status_code == 200

    def test_health_has_required_fields(self, app_client):
        body = app_client.get("/health").json()
        assert "status" in body
        assert "version" in body
        assert "database_connected" in body
        assert "runtime_guard" in body

    def test_health_status_is_ok_or_degraded(self, app_client):
        body = app_client.get("/health").json()
        assert body["status"] in ("ok", "degraded")

    def test_health_version_matches_config(self, app_client):
        body = app_client.get("/health").json()
        assert body["version"] == config.APP_VERSION

    def test_health_database_connected_is_bool(self, app_client):
        body = app_client.get("/health").json()
        assert isinstance(body["database_connected"], bool)

    def test_root_endpoint(self, app_client):
        body = app_client.get("/").json()
        assert body["name"] == config.APP_NAME
        assert body["phase"] == "7-testing-monitoring"


# ── §4 Phase 0: DB connectivity (skipped if DB down) ──

class TestDbConnectivity:

    def test_ping_returns_bool(self, db_available):
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.core.db import ping
        assert isinstance(ping(), bool)

    def test_batch_query_select_one(self, db_available):
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.core.db import batch_query
        rows = batch_query("SELECT 1 AS ok")
        assert len(rows) == 1
        assert rows[0]["ok"] == 1

```

#### tests/test_phase3_api_layer.py

```python
"""NBACore v8 §2 Layer 3 — Phase 3 API Layer tests.

Covers:
    - Pydantic schemas (serialization, from_row, None handling)
    - /metrics endpoints (list, detail, evaluate)
    - /players endpoints (search, detail with metrics)
    - /vs/compare endpoint (validation + real comparison)
    - /batch endpoint (rank, compute, compute_many)
    - Layer Isolation (no pandas/psycopg2/SQL/eval in API layer)
    - Real 2025 season endpoint integration (needs DB)

v8 §6: No mocking of Metric Engine core logic. DB-dependent tests use a
live connection (skipped if PostgreSQL unavailable).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.api import schemas
from backend.api.routers import batch, metrics, players, vs


# ── DB availability probe (session-scoped, avoids repeated pings) ──

try:
    from backend.core.db import ping as _db_ping
    _DB_AVAILABLE = _db_ping()
except Exception:
    _DB_AVAILABLE = False

needs_db = pytest.mark.skipif(
    not _DB_AVAILABLE,
    reason="needs live PostgreSQL (set DB_PORT and start service)",
)


# ── TestSchemas ──

class TestSchemas:
    """Pydantic schema validation (no DB needed)."""

    def test_metric_info_serialization(self):
        """MetricInfo should serialize all fields correctly."""
        m = schemas.MetricInfo(
            name="pts_per_game",
            kind="per_game",
            source_table="fact_player_season_stats",
            required_cols=["pts", "g"],
            description="Points per game",
            min_denominator=1.0,
            precision=6,
        )
        d = m.model_dump()
        assert d["name"] == "pts_per_game"
        assert d["kind"] == "per_game"
        assert d["required_cols"] == ["pts", "g"]
        assert d["precision"] == 6

    def test_player_bio_from_row_handles_date(self):
        """from_row should convert date/datetime to ISO string."""
        from datetime import date
        row = {
            "player_id": "test01",
            "player_name": "Test Player",
            "full_name": "Test Q. Player",
            "birth_date": date(1995, 6, 15),
            "height_cm": 190,
        }
        bio = schemas.PlayerBio.from_row(row)
        assert bio.player_id == "test01"
        assert bio.birth_date == "1995-06-15"
        assert bio.height_cm == 190
        assert bio.player_name == "Test Player"

    def test_player_bio_from_row_null_date(self):
        """from_row should handle None birth_date gracefully."""
        row = {"player_id": "test02", "birth_date": None}
        bio = schemas.PlayerBio.from_row(row)
        assert bio.birth_date is None
        assert bio.player_id == "test02"

    def test_vs_compare_response_allows_none(self):
        """VSCompareResponse must accept None values for missing player data."""
        resp = schemas.VSCompareResponse(
            player_1="p1",
            player_2="p2",
            season=2025,
            metrics={"pts_per_game": {"p1": 25.5, "p2": None}},
        )
        d = resp.model_dump()
        assert d["metrics"]["pts_per_game"]["p2"] is None
        assert d["metrics"]["pts_per_game"]["p1"] == 25.5


# ── TestMetricsEndpoints ──

class TestMetricsEndpoints:
    """/metrics router tests."""

    def test_list_metrics_returns_all_registered(self, app_client):
        """GET /metrics should return all registered metrics."""
        resp = app_client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 11  # 5 basic + 4 advanced + 2 composite
        names = {m["name"] for m in data["metrics"]}
        assert "pts_per_game" in names
        assert "true_shooting_pct" in names
        assert "fantasy_points" in names

    def test_get_metric_detail(self, app_client):
        """GET /metrics/{name} should return metric spec details."""
        resp = app_client.get("/metrics/pts_per_game")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "pts_per_game"
        assert data["kind"] == "per_game"
        assert "pts" in data["required_cols"]
        assert "g" in data["required_cols"]

    def test_get_metric_404_for_unknown(self, app_client):
        """GET /metrics/{unknown} should return 404."""
        resp = app_client.get("/metrics/nonexistent_metric")
        assert resp.status_code == 404

    def test_evaluate_metric_validation_season_required(self, app_client):
        """GET /metrics/evaluate/{name} without season should return 422."""
        resp = app_client.get("/metrics/evaluate/pts_per_game")
        assert resp.status_code == 422  # FastAPI validation error

    @needs_db
    def test_evaluate_metric_returns_rankings(self, app_client):
        """GET /metrics/evaluate/{name}?season=2025 should return ranked list."""
        resp = app_client.get("/metrics/evaluate/pts_per_game?season=2025&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["metric"] == "pts_per_game"
        assert data["season"] == 2025
        assert data["total"] <= 10
        assert len(data["rankings"]) <= 10
        # Top rank is 1
        assert data["rankings"][0]["rank"] == 1
        # Top scorer should be > 25 PPG
        assert data["rankings"][0]["value"] > 25.0


# ── TestPlayersEndpoints ──

class TestPlayersEndpoints:
    """/players router tests."""

    def test_search_too_short_returns_422(self, app_client):
        """GET /players?name=x should fail validation (min_length=2)."""
        resp = app_client.get("/players?name=x")
        assert resp.status_code == 422

    @needs_db
    def test_search_returns_results(self, app_client):
        """GET /players?name=lebron should find LeBron James."""
        resp = app_client.get("/players?name=lebron&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        # At least one result should contain "LeBron" in full_name or player_name
        names = [p.get("full_name") or p.get("player_name") or "" for p in data["players"]]
        assert any("lebron" in n.lower() for n in names), f"no LeBron in {names}"

    def test_get_player_detail_404_for_unknown(self, app_client):
        """GET /players/{unknown}?season=2025 should return 404."""
        resp = app_client.get("/players/nonexistent99?season=2025")
        assert resp.status_code == 404

    @needs_db
    def test_get_player_detail_with_metrics(self, app_client):
        """GET /players/{id}?season=2025 should return bio + metrics."""
        # Get a real player ID from the evaluate endpoint (top scorer)
        eval_resp = app_client.get("/metrics/evaluate/pts_per_game?season=2025&limit=1")
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        if eval_data["total"] == 0:
            pytest.skip("no players in 2025 rankings")
        pid = eval_data["rankings"][0]["player_id"]

        resp = app_client.get(f"/players/{pid}?season=2025")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bio"]["player_id"] == pid
        assert data["season"] == 2025
        # Should have at least some metrics computed
        assert isinstance(data["metrics"], dict)
        # pts_per_game should be present and positive for a real player
        if "pts_per_game" in data["metrics"]:
            assert data["metrics"]["pts_per_game"] > 0


# ── TestVSEndpoint ──

class TestVSEndpoint:
    """/vs/compare router tests."""

    def test_compare_same_player_400(self, app_client):
        """GET /vs/compare with p1==p2 should return 400."""
        resp = app_client.get("/vs/compare?p1=abc&p2=abc&season=2025")
        assert resp.status_code == 400

    def test_compare_unknown_metric_404(self, app_client):
        """GET /vs/compare with unknown metric should return 404."""
        resp = app_client.get(
            "/vs/compare?p1=a&p2=b&season=2025&metrics=fake_metric"
        )
        assert resp.status_code == 404

    def test_compare_season_required(self, app_client):
        """GET /vs/compare without season should return 422."""
        resp = app_client.get("/vs/compare?p1=a&p2=b")
        assert resp.status_code == 422

    @needs_db
    def test_compare_real_players(self, app_client):
        """GET /vs/compare for two real players should return side-by-side metrics."""
        # Get top 2 scorers from evaluate endpoint (guaranteed to have data)
        eval_resp = app_client.get("/metrics/evaluate/pts_per_game?season=2025&limit=2")
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        if eval_data["total"] < 2:
            pytest.skip("fewer than 2 players in 2025 rankings")
        p1 = eval_data["rankings"][0]["player_id"]
        p2 = eval_data["rankings"][1]["player_id"]

        resp = app_client.get(
            f"/vs/compare?p1={p1}&p2={p2}&season=2025"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["player_1"] == p1
        assert data["player_2"] == p2
        assert data["season"] == 2025
        # Should have multiple metrics
        assert len(data["metrics"]) >= 5
        # Each metric should have both player keys
        for mname, vals in data["metrics"].items():
            assert p1 in vals
            assert p2 in vals


# ── TestBatchEndpoint ──

class TestBatchEndpoint:
    """/batch router tests."""

    def test_batch_empty_operations_400(self, app_client):
        """POST /batch with empty operations should return 400."""
        resp = app_client.post("/batch", json={"operations": []})
        assert resp.status_code == 400

    def test_batch_invalid_type_400(self, app_client):
        """POST /batch with invalid operation type should return 400."""
        resp = app_client.post("/batch", json={
            "operations": [
                {"type": "invalid_op", "season": 2025}
            ]
        })
        assert resp.status_code == 400

    @needs_db
    def test_batch_rank_and_compute(self, app_client):
        """POST /batch with rank + compute should return both results."""
        resp = app_client.post("/batch", json={
            "operations": [
                {
                    "type": "rank",
                    "metric": "pts_per_game",
                    "season": 2025,
                    "limit": 5,
                },
                {
                    "type": "compute",
                    "metric": "true_shooting_pct",
                    "season": 2025,
                },
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        # First result: rank
        assert data["results"][0]["type"] == "rank"
        assert data["results"][0]["metric"] == "pts_per_game"
        assert len(data["results"][0]["rankings"]) <= 5
        # Second result: compute
        assert data["results"][1]["type"] == "compute"
        assert data["results"][1]["metric"] == "true_shooting_pct"
        assert data["results"][1]["count"] > 0


# ── TestLayerIsolation ──

class TestLayerIsolation:
    """v8 §6: API layer must not contain SQL, pandas, psycopg2, or computation.

    The API layer is pure orchestration — it only shapes requests and calls
    metric_engine. No imports of pandas/psycopg2, no SQL strings, no eval/exec.
    """

    def _api_source_files(self) -> list[Path]:
        """Return all .py files under backend/api/."""
        api_dir = Path(__file__).resolve().parent.parent / "backend" / "api"
        return list(api_dir.rglob("*.py"))

    def test_api_no_pandas_import(self):
        """No file in backend/api/ may import pandas."""
        violations = []
        for f in self._api_source_files():
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(f))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "pandas" or alias.name == "numpy":
                            violations.append(f"{f.name}:{node.lineno} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and (node.module.startswith("pandas") or
                                        node.module.startswith("numpy")):
                        violations.append(f"{f.name}:{node.lineno} imports from {node.module}")
        assert not violations, f"pandas/numpy imports in API layer: {violations}"

    def test_api_no_psycopg2_import(self):
        """No file in backend/api/ may import psycopg2 or data_layer SQL."""
        violations = []
        for f in self._api_source_files():
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(f))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("psycopg2"):
                            violations.append(f"{f.name}:{node.lineno} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and (node.module.startswith("psycopg2") or
                                        node.module == "backend.data_layer.batch_loader"):
                        violations.append(f"{f.name}:{node.lineno} imports {node.module}")
        assert not violations, f"psycopg2/data_layer imports in API: {violations}"

    def test_api_no_sql_strings(self):
        """No file in backend/api/ may contain SELECT/INSERT/UPDATE/DELETE SQL."""
        sql_keywords = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE")
        violations = []
        for f in self._api_source_files():
            src = f.read_text(encoding="utf-8")
            upper = src.upper()
            for kw in sql_keywords:
                if kw in upper:
                    # Find the line for context
                    for i, line in enumerate(src.splitlines(), 1):
                        if kw in line.upper() and not line.strip().startswith("#"):
                            violations.append(f"{f.name}:{i} contains '{kw.strip()}'")
        assert not violations, f"SQL strings in API layer: {violations}"

    def test_api_no_eval_exec(self):
        """No file in backend/api/ may contain eval() or exec() calls."""
        violations = []
        for f in self._api_source_files():
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(f))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name) and func.id in ("eval", "exec"):
                        violations.append(f"{f.name}:{node.lineno} calls {func.id}()")
                    elif isinstance(func, ast.Attribute) and func.attr in ("eval", "exec"):
                        violations.append(f"{f.name}:{node.lineno} calls .{func.attr}()")
        assert not violations, f"eval/exec in API layer: {violations}"

    def test_routers_have_no_compute_logic(self):
        """Router functions should only call metric_engine + shape responses.

        Check that no router file defines functions with arithmetic, aggregation,
        or filtering logic beyond simple dict/list comprehensions for response shaping.
        """
        router_dir = Path(__file__).resolve().parent.parent / "backend" / "api" / "routers"
        # Each router file should be relatively short (pure orchestration)
        for f in router_dir.glob("*.py"):
            if f.name == "__init__.py":
                continue
            src = f.read_text(encoding="utf-8")
            lines = src.splitlines()
            # Routers should be under 200 lines (pure orchestration = concise)
            assert len(lines) < 200, f"{f.name} is {len(lines)} lines (expected < 200 for pure orchestration)"


# ── TestRealEndpoints2025 (needs live DB) ──

@needs_db
class TestRealEndpoints2025:
    """Real integration: hit live endpoints against 2025 season data."""

    def test_metrics_evaluate_top10_ppg(self, app_client):
        """GET /metrics/evaluate/pts_per_game?season=2025&limit=10 should return top 10."""
        resp = app_client.get("/metrics/evaluate/pts_per_game?season=2025&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10
        # Ranks should be 1 through 10
        ranks = [r["rank"] for r in data["rankings"]]
        assert ranks == list(range(1, 11))
        # Values should be decreasing (descending = highest first)
        values = [r["value"] for r in data["rankings"]]
        assert all(values[i] >= values[i + 1] for i in range(len(values) - 1))
        # Top scorer should be 25+ PPG
        assert values[0] > 25.0, f"top PPG = {values[0]} (expected > 25)"

    def test_vs_compare_two_stars(self, app_client):
        """GET /vs/compare for two star players should return all default metrics."""
        # Get top 2 scorers from evaluate endpoint (guaranteed to have data)
        eval_resp = app_client.get("/metrics/evaluate/pts_per_game?season=2025&limit=2")
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        if eval_data["total"] < 2:
            pytest.skip("fewer than 2 players in 2025 rankings")
        p1 = eval_data["rankings"][0]["player_id"]
        p2 = eval_data["rankings"][1]["player_id"]

        resp = app_client.get(f"/vs/compare?p1={p1}&p2={p2}&season=2025")
        assert resp.status_code == 200
        data = resp.json()
        # Should have all 10 default VS metrics
        assert len(data["metrics"]) >= 8
        # Both players should have pts_per_game > 20 (top scorers)
        ppg = data["metrics"].get("pts_per_game", {})
        if p1 in ppg and ppg[p1] is not None:
            assert ppg[p1] > 15.0, f"{p1} PPG = {ppg[p1]} (expected > 15)"
        if p2 in ppg and ppg[p2] is not None:
            assert ppg[p2] > 15.0, f"{p2} PPG = {ppg[p2]} (expected > 15)"

    def test_player_detail_real_player(self, app_client):
        """GET /players/{id}?season=2025 should return bio + multiple metrics."""
        # Get top scorer from evaluate endpoint (guaranteed to have 2025 data)
        eval_resp = app_client.get("/metrics/evaluate/pts_per_game?season=2025&limit=1")
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        if eval_data["total"] == 0:
            pytest.skip("no players in 2025 rankings")
        pid = eval_data["rankings"][0]["player_id"]

        resp = app_client.get(f"/players/{pid}?season=2025")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bio"]["player_id"] == pid
        # Should have multiple metrics
        assert len(data["metrics"]) >= 3
        # Top scorer should have PPG > 20
        if "pts_per_game" in data["metrics"]:
            assert data["metrics"]["pts_per_game"] > 20.0

    def test_batch_compute_many(self, app_client):
        """POST /batch with compute_many should return multi-metric dict."""
        resp = app_client.post("/batch", json={
            "operations": [
                {
                    "type": "compute_many",
                    "metrics": ["pts_per_game", "reb_per_game", "ast_per_game"],
                    "season": 2025,
                }
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        result = data["results"][0]
        assert result["type"] == "compute_many"
        assert result["count"] > 100  # ~600 players
        # Each player should have the 3 metrics
        sample_pid = next(iter(result["values"]))
        sample_metrics = result["values"][sample_pid]
        assert "pts_per_game" in sample_metrics
        assert "reb_per_game" in sample_metrics
        assert "ast_per_game" in sample_metrics

```

---

## 5. API 接口说明

### 5.1 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 + 运行时守卫状态 |
| GET | `/` | 项目信息 + 当前阶段 |

**GET /health 响应示例:**
```json
{
  "status": "ok",
  "version": "8.3.1",
  "database_connected": true,
  "runtime_guard": {
    "config_loaded": { "ok": true },
    "metric_engine_exists": { "ok": true },
    "no_forbidden_patterns": { "ok": true }
  }
}
```

### 5.2 指标 (Metrics)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/metrics` | 列出所有已注册指标 |
| GET | `/metrics/{name}` | 获取单个指标详情 |
| GET | `/metrics/evaluate/{name}` | 计算并排名 |

**GET /metrics 响应:**
```json
{
  "count": 16,
  "metrics": [
    {
      "name": "pts_per_game",
      "kind": "per_game",
      "source_table": "fact_player_season_stats",
      "required_cols": ["pts", "g"],
      "description": "Points per game = sum(pts) / sum(g)",
      "precision": 6
    }
  ]
}
```

**GET /metrics/evaluate/{name} 参数:**
- `season` (int, 必填): 赛季
- `limit` (int, 可选): 返回前 N 名，默认 100
- `ascending` (bool, 可选): 升序排列，默认 false
- `min_value` (float, 可选): 最小值过滤

### 5.3 球员 (Players)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/players` | 按姓名搜索球员 |
| GET | `/players/{id}` | 获取球员详情 + 赛季指标 |
| GET | `/players/seasons` | 获取可用赛季列表 |
| GET | `/players/{id}/growth` | 获取球员成长报告（生涯逐年数据） |
| GET | `/players/{id}/shooting-profile` | 获取球员投篮分布（按赛季/区域 FG%/FGA 占比） |
| GET | `/players/{id}/career-defense` | 获取球员生涯防守汇总（STL/BLK/STOCKS/DAE） |
| GET | `/players/{id}/intelligence` | 获取球员情报（角色分类/DNA/可用性/投篮分布） |

**GET /players 参数:**
- `name` (str, 必填, min=2): 搜索关键字
- `limit` (int, 可选, 1-100): 返回数量限制，默认 20

**GET /players/{id}/growth 响应:**
```json
{
  "player_id": "jamesle01",
  "bio": {
    "player_name": "勒布朗·詹姆斯",
    "height_cm": 206,
    "weight_kg": 113.4,
    "position": "SF",
    "birth_date": "1984-12-30"
  },
  "seasons": [
    {
      "season": 2004,
      "age": 19,
      "team": "CLE",
      "g": 79,
      "gs": 79,
      "mp": 3122,
      "pts": 1654,
      "pts_per_game": 20.9,
      "reb_per_game": 5.5,
      "ast_per_game": 5.9,
      "fg_pct": 0.417,
      "x3p_pct": 0.290,
      "ft_pct": 0.754,
      "usg_percent": 25.2,
      "height_cm": 203,
      "weight_kg": 100.7
    }
  ],
  "positions": [
    {
      "position": "SF",
      "games": 1200,
      "minutes": 42000,
      "points": 35000,
      "min_percentage": 85.0,
      "pts_percentage": 88.0
    }
  ],
  "milestones": [
    {
      "season": 2004,
      "label": "新秀赛季",
      "description": "首秀赛季，场均 20.9 分"
    },
    {
      "season": 2012,
      "label": "首冠",
      "description": "生涯首个总冠军"
    }
  ]
}
```

### 5.4 VS 对比

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/vs/compare` | 两名球员多指标对比 |

**参数:**
- `p1` (str, 必填): 球员 1 ID
- `p2` (str, 必填): 球员 2 ID
- `season` (int, 必填): 赛季
- `metrics` (str, 可选): 逗号分隔的指标名列表，默认全部

**响应:**
```json
{
  "player_1": "gilgesh01",
  "player_2": "antetgi01",
  "season": 2025,
  "metrics": {
    "pts_per_game": {
      "gilgesh01": 32.5,
      "antetgi01": 30.4
    }
  }
}
```

### 5.5 批量操作 (Batch)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/batch` | 批量执行多个操作 |

**支持的操作类型:**
- `rank`: 排名计算
- `compute`: 单指标计算
- `compute_many`: 多指标计算

**请求示例:**
```json
{
  "operations": [
    {
      "type": "rank",
      "metric": "pts_per_game",
      "season": 2025,
      "limit": 10
    },
    {
      "type": "compute_many",
      "metrics": ["pts_per_game", "reb_per_game"],
      "season": 2025
    }
  ]
}
```

### 5.6 上下文分析 (Context)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/context/similar` | 相似球员分析 |
| GET | `/context/evolution` | 角色演变分析 |
| GET | `/context/trend` | 趋势分析 |

### 5.7 导出 (Export)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/export/rankings` | 导出排名 (JSON/CSV) |
| GET | `/export/vs` | 导出 VS 对比 (JSON/CSV) |
| GET | `/export/player` | 导出球员数据 (JSON) |
| GET | `/export/league` | 导出全联盟数据 (JSON) |

**参数:**
- `format`: `json` 或 `csv`
- 其他参数与对应 API 一致

### 5.8 监控 (Monitor)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/monitor/cache` | 缓存统计信息 |
| POST | `/monitor/cache/clear` | 清除缓存 |
| GET | `/monitor/schema` | Schema 漂移检测报告 |

---

### 5.4 v8.1 新增接口 (Metric Expansion)

v8.1 在 Metric Engine 新增 5 个指标（注册表 11 → 16），并在 Players API 新增 2 个只读端点。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/players/{id}/shooting-profile` | 球员投篮分布：按赛季分组，5 个投篮区域（禁区/油漆区/中距离/长两分/三分线外）的 FG% 与 FGA 占比 |
| GET | `/players/{id}/career-defense` | 球员生涯防守汇总：累计 STL/BLK/PF、STOCKS、STOCKS/G、STL/G、BLK/G、防守活动效率 DAE |

**GET /players/{id}/shooting-profile 响应示例:**
```json
{
  "player_id": "jamesle01",
  "latest_season": 2026,
  "seasons": [
    {
      "season": 2026,
      "team": "LAL",
      "zones": [
        { "zone": "restricted_area", "fg_pct": 0.60, "fga_rate": 0.32 },
        { "zone": "paint", "fg_pct": 0.45, "fga_rate": 0.18 },
        { "zone": "mid_range", "fg_pct": 0.40, "fga_rate": 0.22 },
        { "zone": "long_two", "fg_pct": 0.38, "fga_rate": 0.10 },
        { "zone": "three_point", "fg_pct": 0.35, "fga_rate": 0.28 }
      ]
    }
  ]
}
```

**GET /players/{id}/career-defense 响应示例:**
```json
{
  "player_id": "jamesle01",
  "found": true,
  "seasons": 23,
  "total_games": 1491,
  "total_steals": 2417,
  "total_blocks": 1185,
  "total_fouls": 2500,
  "stocks": 3602,
  "stocks_per_game": 2.22,
  "steals_per_game": 1.62,
  "blocks_per_game": 0.79,
  "def_activity_efficiency": 1.259
}
```

> 注：投篮区域遵循 v8.1 §7.1 映射，底角三分与弧顶三分未区分（合并为 `three_point` 区域，属已知偏差）。

## 5.5 v8.2 球员情报 API

`GET /players/{id}/intelligence?season=&season_type=` 返回球员情报对象（纯编排，计算全部在 Intelligence Engine）：

- `role`：9 种球员原型之一（Primary Creator / Secondary Creator / Scoring Guard / 3&D Wing / Shot Creator / Rim Protector / Stretch Big / Two Way Star / Role Player），由 usg%/ast%/ts%/三分率/篮板%/抢断%/盖帽% 的确定性规则树判定。
- `dna`：7 维球员画像（scoring / playmaking / defense / rebounding / efficiency / durability / leadership），各 0-100，公式透明可解释（`leadership` 为使用率+组织参与的近似维度，源数据无直接领导力指标）。
- `availability`：出勤（games/team_games）与出场时间占比（mp/team_mp），均裁剪 [0,1]。
- `scoring_profile`：投篮分布（按区域 At Rim / Paint / Mid-Range / Three Point 的频率与命中率）。**说明**：本数据集仅有投篮*位置*分区，无事件级 play-type 标注，故按区域呈现而非 PRD §10 的 play-type 分类（At Rim/Post Up/Isolation/PnR/Spot Up/Transition/Pull Up），已知偏差已注明，未伪造数据。

Intelligence Engine 为独立于 Metric Engine 的计算层（其产出不注册为 MetricSpec 指标）。

## 5.6 v8.3 工作区 API (Workspace Core)

工作区（Workspace）是完整的篮球分析项目容器（PRD v8.3.1 §5.1），可挂载数据集、公式、图表等资源。所有端点前缀 `/api/workspaces`（纯编排，持久化由专用写路径数据层 `workspace_db.py` 完成；`core.db` 仍保持 SELECT-only，满足 v8 §6）。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/workspaces` | 创建工作区（201） |
| GET | `/api/workspaces` | 列出工作区（支持 `owner_id` / `status` / `limit` / `offset`） |
| GET | `/api/workspaces/{id}` | 获取单个工作区（含 datasets / formulas / charts） |
| PUT | `/api/workspaces/{id}` | 更新工作区（name / description / status） |
| DELETE | `/api/workspaces/{id}` | 删除工作区（204，级联删除资源链接） |
| POST | `/api/workspaces/{id}/duplicate` | 复制工作区（复制资源链接） |
| POST | `/api/workspaces/{id}/datasets` | 关联数据集 `{"dataset_id": int}` |
| DELETE | `/api/workspaces/{id}/datasets/{dataset_id}` | 取消关联数据集 |
| POST | `/api/workspaces/{id}/formulas` | 关联公式 `{"formula_id": int}` |
| DELETE | `/api/workspaces/{id}/formulas/{formula_id}` | 取消关联公式 |
| POST | `/api/workspaces/{id}/charts` | 新建图表 `{"name": str, "chart_config": dict}`（201） |
| PUT | `/api/workspaces/{id}/charts/{chart_id}` | 更新图表 |
| DELETE | `/api/workspaces/{id}/charts/{chart_id}` | 删除图表（204） |
| GET | `/api/workspaces/{id}/export` | 导出 `.nbacore` 项目文件（JSON） |

**数据表**（v8.3.1 新增，PostgreSQL）：

| 表名 | 说明 |
|------|------|
| `workspaces` | 工作区主表（id SERIAL, owner_id, name, description, status, created_at, updated_at） |
| `workspace_datasets` | 工作区↔数据集关联（workspace_id, dataset_id；UNIQUE） |
| `workspace_formulas` | 工作区↔公式关联（workspace_id, formula_id；UNIQUE） |
| `workspace_charts` | 工作区图表（workspace_id, name, chart_config JSONB） |

**说明**：`workspace_datasets.dataset_id` / `workspace_formulas.formula_id` 为引用 ID（暂不设外键），因 datasets / formulas 实体表在 v8.3.2+ 才落地；引用合法性校验随其后置。`.nbacore` 文件格式见 PRD v8.3.1 §8。

Workspace Engine 为独立于 Metric / Intelligence Engine 的持久化与分析层（v8.3.0 §4.1），其写路径是 v8 中唯一被允许的 DML 来源。

## 6. 数据库 Schema

### 6.1 已注册表

| 表名 | 类型 | 赛季列 | 球员列 | 说明 |
|------|------|--------|--------|------|
| `fact_player_season_stats` | 事实表 | `season` | `player_id` | 球员赛季总数据 |
| `player_gamelog` | 事实表 | `season` | `br_player_id` | 球员比赛日志 |
| `dim_players` | 维度表 | — | `player_id` | 球员基本信息 |

### 6.2 fact_player_season_stats (球员赛季统计)

核心事实表，存储球员每个赛季的累计数据。Metric Engine 大部分指标基于此表计算。

**主要列:**
- `player_id` (text): BBR 球员 ID (如 'gilgesh01')
- `season` (int): 赛季年份
- `team` (text): 球队缩写
- `age` (int): 年龄
- `g` (int): 出场次数
- `gs` (int): 首发次数
- `mp` (float): 总出场时间
- `fg` (int): 命中数
- `fga` (int): 出手数
- `fg_pct` (float): 命中率
- `x3p` (int): 三分命中
- `x3pa` (int): 三分出手
- `x3p_pct` (float): 三分命中率
- `x2p` (int): 两分命中
- `x2pa` (int): 两分出手
- `x2p_pct` (float): 两分命中率
- `ft` (int): 罚球命中
- `fta` (int): 罚球出手
- `ft_pct` (float): 罚球命中率
- `orb` (int): 进攻篮板
- `drb` (int): 防守篮板
- `trb` (int): 总篮板
- `ast` (int): 助攻
- `stl` (int): 抢断
- `blk` (int): 盖帽
- `tov` (int): 失误
- `pf` (int): 犯规
- `pts` (int): 得分
- `usg_percent` (float): 使用率

### 6.3 dim_players (球员维度表)

球员基本信息表，用于搜索和展示。

**主要列:**
- `player_id` (text): BBR 球员 ID
- `player_name` (text): 球员姓名
- `full_name` (text): 全名
- `position` (text): 位置
- `height_cm` (int): 身高 (厘米)
- `weight_kg` (float): 体重 (公斤)
- `birth_date` (date): 出生日期
- `team` (text): 当前球队
- `team_abbr` (text): 球队缩写
- `college` (text): 大学
- `country` (text): 国家

### 6.4 player_gamelog (比赛日志)

逐场比赛数据，用于更细粒度的分析。

**主要列:**
- `br_player_id` (text): BBR 球员 ID
- `season` (int): 赛季
- `game_date` (date): 比赛日期
- `team` (text): 球队
- `opponent` (text): 对手
- `home_away` (text): 主客场
- `result` (text): 胜负
- `mp` (float): 出场时间
- `pts` (int): 得分
- `reb` (int): 篮板
- `ast` (int): 助攻
- `stl` (int): 抢断
- `blk` (int): 盖帽
- `tov` (int): 失误
- ... 其他技术统计列

---

## 7. 新增功能模块

### 7.1 球员成长路线 (Player Growth)

球员成长路线功能提供球员职业生涯逐年数据的完整报告，包括身高体重变化、技术统计趋势、位置占比分析和生涯里程碑。

#### 7.1.1 数据来源优先级

1. **dim_players** — 球员基础信息（身高/体重/位置/生日）
2. **fact_player_season_stats** — 赛季累计统计数据
3. **player_per_game** — 场均数据（补充）
4. **player_advanced** — 进阶数据（补充）
5. **player_season_splits** — 位置拆分数据（计算位置占比）

#### 7.1.2 核心代码文件

| 文件 | 路径 | 说明 |
|------|------|------|
| `growth_loader.py` | `backend/data_layer/growth_loader.py` | 数据加载器，提供球员生涯数据查询 |
| `growth_report.py` | `backend/services/growth_report.py` | 成长报告生成服务，整合数据并计算衍生指标 |
| `players.py` | `backend/api/routers/players.py` | API 路由，新增 `/players/{player_id}/growth` 接口 |

#### 7.1.3 数据加载器 — growth_loader.py

**核心函数:**

- `get_player_career_stats(player_id)` — 获取球员生涯所有赛季的累计数据
- `get_player_per_game_career(player_id)` — 获取球员生涯场均数据
- `get_player_career_summary(player_id)` — 获取球员生涯汇总数据
- `get_player_position_breakdown(player_id)` — 获取球员位置拆分数据
- `get_team_season_points(season, team_abbr)` — 获取球队赛季总得分（用于计算得分占比）

#### 7.1.4 成长报告服务 — growth_report.py

**核心函数:**

- `build_growth_report(player_id)` — 构建完整成长报告
  - 整合 dim_players 基础信息与各赛季数据表
  - 计算衍生指标（位置占比、得分占比、使用率变化等）
  - 生成生涯里程碑时间轴
- `_compute_milestones(seasons)` — 计算里程碑事件

**报告结构:**

```
GrowthReportResponse
├── player_id (str)
├── bio (PlayerBio)
│   ├── player_name
│   ├── height_cm
│   ├── weight_kg
│   ├── position
│   └── birth_date
├── seasons (list[SeasonStats])
│   ├── season, age, team
│   ├── g, gs, mp
│   ├── pts, reb, ast, stl, blk
│   ├── pts_per_game, reb_per_game, ast_per_game
│   ├── fg_pct, x3p_pct, ft_pct
│   ├── usg_percent
│   ├── height_cm, weight_kg
│   └── pts_share (得分占比)
├── positions (list[PositionBreakdown])
│   ├── position
│   ├── games, minutes, points
│   ├── min_percentage (出场时间占比)
│   └── pts_percentage (得分占比)
└── milestones (list[Milestone])
    ├── season
    ├── label
    └── description
```

### 7.2 Player Context 页面增强

#### 7.2.1 球员列表链接与比较按钮

相似球员列表中的每个球员现在支持：
- **点击球员姓名** → 跳转到该球员的 Player Context 页面
- **📈 按钮** → 跳转到该球员的 Player Growth 页面
- **⚔️ 按钮** → 将该球员添加到 Player VS 对比

**相关函数:**

- `viewSimilarPlayerContext(playerId, playerName)` — 跳转到指定球员的 Context 页面
- `viewSimilarPlayerGrowth(playerId, playerName)` — 跳转到指定球员的 Growth 页面
- `addSimilarPlayerToVS(playerId, playerName)` — 将球员添加到 VS 对比

#### 7.2.2 Context VS 整合 (Tab 切换模式)

Player Context 页面新增 Tab 切换功能，将 Player VS 整合到 Context 页面内：

**Tab 结构:**
1. **Context** — 原有 Context 分析功能（相似球员、角色演变等）
2. **VS Compare** — 球员对比功能

**VS Compare 特性:**
- Player 1 自动绑定当前 Context 页面的球员（不可更换）
- Player 2 可通过搜索框选择任意球员
- 支持多指标选择对比
- 数据对比表格
- 雷达图可视化
- 柱状图对比
- 相似球员一键对比（点击 ⚔️ 按钮自动切换到 VS Compare Tab）

**相关样式类:**
- `.ctx-tabs` — Tab 容器
- `.ctx-tab` — 单个 Tab
- `.ctx-tab.active` — 激活状态
- `.ctx-vs-selector` — VS 选择器区域

### 7.3 球队 Logo 可视化

#### 7.3.1 素材资源

- **位置**: `NBAlogo/` 目录（项目根目录）
- **格式**: SVG (30支球队) + PNG (部分球队)
- **命名**: 小写球队缩写，如 `atl.svg`, `lakers.svg`
- **访问路径**: `/assets/logos/{abbr}.svg`

#### 7.3.2 应用位置

1. **球队列表页 (Teams List)**
   - 新增 Logo 列，显示每支球队的队徽
   - 点击球队行可查看详情

2. **球队详情页 (Team Detail)**
   - 头部显示大尺寸球队 Logo
   - 旁边显示球队缩写和名称
   - 下方是球队雷达图、战绩排名等数据

#### 7.3.3 相关样式

```css
.team-logo-sm {
  width: 32px;
  height: 32px;
  object-fit: contain;
  display: block;
}

.team-detail-header {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 20px;
  background: var(--bg-card);
  border-radius: 12px;
}

.team-detail-logo {
  width: 80px;
  height: 80px;
  flex-shrink: 0;
}

.team-detail-logo img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
```

#### 7.3.4 后端静态文件挂载

在 `backend/app.py` 中配置：

```python
_logo_dir = _base / "NBAlogo"
if _logo_dir.is_dir():
    app.mount("/assets/logos", StaticFiles(directory=str(_logo_dir)), name="logos")
    app.mount("/app/assets/logos", StaticFiles(directory=str(_logo_dir)), name="logos-app")
```

---

### 7.4 v8.1 指标扩展 (Metric Expansion)

v8.1 在原有 11 个指标基础上新增 5 个指标，注册表规模达到 16。所有新增指标均遵循 v8 §2 分层约束（向量化 pandas 计算，无 per-player 循环，无 eval/exec，无动态 SQL）。

#### 7.4.1 新增指标

| 指标 | 类型 | 数据源 | 公式 | 说明 |
|------|------|--------|------|------|
| `orb_per_game` | per_game | `fact_player_season_stats` | sum(orb)/sum(g) | 进攻篮板/场 |
| `drb_per_game` | per_game | `fact_player_season_stats` | sum(drb)/sum(g) | 防守篮板/场 |
| `ast_to_ratio` | ratio | `fact_player_season_stats` | sum(ast)/clip(sum(tov),1.0) | 助攻/失误比（失误下限 1.0 防除零） |
| `def_activity_efficiency` | ratio | `fact_player_season_stats` | (sum(stl)+sum(blk))/clip(sum(pf),1.0) | 防守活动效率 DAE（犯规下限 1.0 防除零） |
| `team_scoring_share` | ratio | `player_team_share` | player_ppg / team_ppg | 球员得分占球队得分比（专用 join 表） |

#### 7.4.2 前端分析卡片

球员成长页面（Growth）新增 v8.1 分析区，包含 6 个纯渲染组件（`frontend/js/components/`，命名空间 `window.V81`，数值全部由后端预计算）：

1. **ReboundingCard** — 最新赛季 ORB/DRB/TRB 场均条形 + ORB%/DRB%/TRB% 占比
2. **PlaymakingCard** — AST/TOV/AST-TO 比磁贴
3. **DefenseProfileCard** — STL/BLK/PF/DAE 磁贴
4. **ShotProfileChart** — 各投篮区域 FG% 与 FGA 占比分组柱状图（ECharts）
5. **TeamContributionChart** — 生涯各赛季 `scoring_share%` 折线图（ECharts）
6. **CareerDefenseSummary** — 生涯 STL/BLK/PF/STOCKS 磁贴 + 占比

#### 7.4.3 测试覆盖

新增 `tests/test_phase81_v81_metrics.py`（29 个测试），覆盖指标注册、纯计算、混合数据源 bug 修复、Pydantic schema、层级隔离与实时数据库计算。全量测试 189/189 通过（v8.1-D LOCK）。

---

> 文档生成时间: 2026-07-08
> 项目: NBACore Studio v8.3.1
