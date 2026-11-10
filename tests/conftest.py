"""Pytest fixtures for NBACore v8 — Phase 0.

v8 §6 forbids mocking Metric Engine core logic. DB-dependent tests use a
live connection (skipped if PostgreSQL unavailable) rather than mocking.

DB 口令来源（2026-11-10 统一）
--------------------------------
本层只做 **env → env 的派生**，不硬编码任何口令：

- ``backend.core.config`` 在导入时把仓库根 ``.env`` 注入 ``os.environ``
  （``DB_PASSWORD`` 等），因此 ``DB_PASSWORD`` 天然来自 env；
- 部分测试直接用 ``psycopg2.connect(..., password=os.environ["PGPASSWORD"])``，
  而 libpq 的标准变量名是 ``PGPASSWORD``，此前二者未打通 → 这批测试被
  ``pytest.skip("未设置 PGPASSWORD")`` 静默跳过，DB 覆盖形同虚设；
- 这里把 ``DB_PASSWORD`` 派生为 ``PGPASSWORD``，打通两者。

优先级：显式 ``PGPASSWORD``（CI secret 注入）> ``DB_PASSWORD``（本地 .env）。
两者都缺失时保持为空 —— 由各测试自己的 skip 守卫决定跳过，不静默连库。
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from backend.core import config as _core_config  # noqa: F401  导入即加载 .env → os.environ
from backend.core.db import is_port_open, ping


def _derive_pgpassword() -> str:
    """把 ``DB_PASSWORD`` 派生为 ``PGPASSWORD``，返回最终生效的口令。

    - 已有 ``PGPASSWORD`` → 原样保留（CI 显式注入优先，不被 .env 覆盖）
    - 否则取 ``DB_PASSWORD``（由 config 导入时从 .env 注入）
    - 值统一去引号：``config._load_dotenv`` 不去引号，而工作区 ``dbutil``
      会去，两套口径不一致会让带引号的 .env 认证失败 —— 这里清洗一次
    """
    pw = os.environ.get("PGPASSWORD") or os.environ.get("DB_PASSWORD", "")
    pw = pw.strip().strip('"').strip("'")
    if pw and not os.environ.get("PGPASSWORD"):
        os.environ["PGPASSWORD"] = pw
    return pw


# 导入期即派生：保证任何测试模块在 collection 阶段读 os.environ 也能拿到
_derive_pgpassword()


@pytest.fixture(scope="session")
def app_client():
    """FastAPI TestClient with lifespan triggered (pool init attempted)."""
    from backend.app import create_app
    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def db_available() -> bool:
    """True only if a live PostgreSQL is reachable.

    仅代表「连得上」。注意：空库也能通过（``ping()`` 只跑 ``SELECT 1``），
    因此**不能**用它判断「库里有可供断言的数据」—— 需要真实数据的测试
    请用 ``db_populated``。
    """
    return is_port_open() and ping()


# 判定「库里有数据」的探针表：dim_games 是全库最核心的事实表（每场比赛一行），
# 空库时它必然为空。用「表存在且有行」而不是硬编码行数阈值。
_POPULATION_PROBE_TABLE = "dim_games"


@pytest.fixture(scope="session")
def db_populated() -> bool:
    """True if the live DB is reachable **and** carries the core fact table.

    CI 环境说明（2026-11-10 定稿）
    ----------------------------
    CI **刻意不提供 postgres 服务**（实测：起一次性空容器 → 105 failed + 3 errors；
    不起库 → DB 依赖测试统一 skip）。因此 CI 上本 fixture 返回 False，
    ``needs_data`` 标记的用例会全部 skip —— CI 只验证不依赖生产数据的部分
    （纯逻辑 / 契约 / 静态检查 / 架构合规）。

    即便将来 CI 恢复提供 DB，「可连」也不等于「有数据」：
    空库能通过 ``ping()``（它只跑 ``SELECT 1``），数据依赖测试在空库上
    会「真跑并失败」——把「环境缺数据」误报成「代码有 bug」。

    - ``db_available``  → 仅可连（端口 + SELECT 1）
    - ``db_populated``  → 可连 **且** dim_games 有行 ← 需要真实数据的测试用这个
    """
    if not (is_port_open() and ping()):
        return False
    try:
        from backend.core.db import batch_query

        rows = batch_query(f"SELECT 1 AS ok FROM {_POPULATION_PROBE_TABLE} LIMIT 1")
        return bool(rows)
    except Exception:  # noqa: BLE001 - 表不存在/无权限 → 视为无数据
        return False


def skip_without_db(db_available: bool):
    """Helper for tests that need a live DB."""
    if not db_available:
        pytest.skip("PostgreSQL not available — set DB_PORT and start service")


def skip_without_data(db_populated: bool):
    """Helper for tests that need a live DB **carrying data**.

    与 ``skip_without_db`` 的区别：空库（CI 的一次性 postgres）也 skip，
    避免「环境缺数据」被误报成「代码有 bug」。
    """
    if not db_populated:
        pytest.skip("PostgreSQL reachable but carries no data (empty DB) — 数据依赖测试跳过")


# ─────────────────────────────────────────────────────────────────────────────
# needs_db / needs_data marker 机制（2026-11-10）
# -----------------------------------------------------------------------------
# 复用仓库既有的 ``needs_db`` marker（pyproject.toml 已注册，见
# backend/services/tactics_engine/tests/ 与 tests/test_a1_3_acceptance.py 的既有用法），
# 本层只做**统一实现** —— 此前各测试文件各自写 skipif，口径不一，漏一处
# 就会在 CI 上变成 ERROR/FAILED。
#
#   needs_db    → 需要「能连上数据库」（连不上即 skip）
#   needs_data  → 需要「库里有数据」（空库也 skip）—— CI 场景的关键
#
# 为什么需要 needs_data：
#   ``ping()`` 只跑 ``SELECT 1``，**空库也能通过** → 只判可连的话，
#   数据依赖测试会在空库上「真跑并失败」，把「环境缺数据」误报成「代码有 bug」。
#
# CI 为什么不提供 postgres 服务（实测数据，2026-11-10）：
#   CI 起空 postgres            → 105 failed + 3 errors
#   CI 不起 postgres（不可达）  →  21 failed + 0 errors（修完存量断言与本机路径
#                                  依赖后 → **0 failed / 620 passed / 161 skipped**）
#   空库噪音大且无诊断价值；不起库 → DB 依赖测试统一 skip，
#   CI 只验证不依赖生产数据的部分（纯逻辑、契约、静态检查、架构合规）。
# ─────────────────────────────────────────────────────────────────────────────
_DB_MARKERS = ("needs_db", "needs_data")


def pytest_configure(config: pytest.Config) -> None:
    for marker in _DB_MARKERS:
        if marker not in config.getini("markers"):
            config.addinivalue_line(
                "markers",
                f"{marker}: 需要 PostgreSQL 的测试（DB 不可用/无数据时自动 skip）",
            )


def pytest_collection_modifyitems(config: pytest.Config, items) -> None:
    """给标记了 needs_db / needs_data 的测试注入 skip 条件。

    判定在 collection 阶段做一次，避免每个用例重复探活。
    """
    need_db = [it for it in items if it.get_closest_marker("needs_db")]
    need_data = [it for it in items if it.get_closest_marker("needs_data")]
    if not need_db and not need_data:
        return

    from backend.core.db import is_port_open, ping

    reachable = is_port_open() and ping()
    populated = False
    if reachable:
        try:
            from backend.core.db import batch_query

            populated = bool(
                batch_query(f"SELECT 1 AS ok FROM {_POPULATION_PROBE_TABLE} LIMIT 1")
            )
        except Exception:  # noqa: BLE001 - 表不存在 → 视为无数据
            populated = False

    if need_db and not reachable:
        skip = pytest.mark.skip(reason="needs_db: PostgreSQL 不可用 — 跳过")
        for it in need_db:
            it.add_marker(skip)
    if need_data and not populated:
        skip = pytest.mark.skip(reason="needs_data: 数据库无数据（空库）— 跳过")
        for it in need_data:
            it.add_marker(skip)
