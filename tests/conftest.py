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


# 判定「库里有 schema」的探针表：dim_games 是全库最核心的事实表，
# 它的**存在**即代表 schema 已还原（哪怕表里 0 行）。
# 用「表存在」而不是硬编码表清单 —— CI 还原的是完整 DDL（db/schema.sql，
# 197 个对象），任何一张核心表缺失即说明 schema 不完整。
_SCHEMA_PROBE_TABLE = "dim_games"

# 判定「库里有数据」的探针表：dim_games 是全库最核心的事实表（每场比赛一行），
# 空库时它必然为空。用「表存在且有行」而不是硬编码行数阈值。
_POPULATION_PROBE_TABLE = "dim_games"


def _probe_has_schema() -> bool:
    """库可达且核心表存在 → 判定「有 schema」。

    这是「有 schema」与「有数据」的分界：**空表也是 schema**。
    CI 用 ``db/schema.sql``（仅结构、无数据行）还原的库就是这一档 ——
    结构契约类测试能在 CI 真跑，内容断言类测试必须 skip。
    """
    try:
        from backend.core.db import batch_query

        rows = batch_query(
            "SELECT 1 AS ok FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s LIMIT 1",
            (_SCHEMA_PROBE_TABLE,),
        )
        return bool(rows)
    except Exception:  # noqa: BLE001 - 表不存在/无权限 → 视为无 schema
        return False


@pytest.fixture(scope="session")
def db_has_schema() -> bool:
    """True if the DB is reachable **and** carries the core schema (tables exist).

    与 ``db_available`` 的区别：``db_available`` 只问「连得上吗」，
    而空容器（无任何表）也能通过 ``ping()``；本 fixture 额外要求
    **核心表存在** —— 这是「结构契约类测试」在 CI 里能真跑的前提。
    """
    if not (is_port_open() and ping()):
        return False
    return _probe_has_schema()


@pytest.fixture(scope="session")
def db_populated() -> bool:
    """True if the live DB is reachable **and** carries the core fact table with rows.

    CI 环境说明（2026-11-10 实测三场景定稿）
    ----------------------------------------
    同一套 781 个用例，在三种库环境下的实测结果：

    | 场景                              | passed | skipped | failed | error |
    |-----------------------------------|--------|---------|--------|-------|
    | A 不提供 postgres（不可达）        |   620 |     161 |      0 |     0 |
    | B 提供 postgres 但**空库无 schema**|   654 |      25 |     89 |    13 |
    | C 提供 postgres + **schema-only** |   686 |      36 |     59 |     0 |

    结论与 CI 策略：
      * CI 采用**场景 C**（起一次性 postgres + 还原 db/schema.sql，0.3s）→
        结构契约类测试在 CI **真跑真过**，内容断言类测试（needs_data）统一 skip；
      * 「可连」≠「有数据」：``ping()`` 只跑 ``SELECT 1``，空库也能通过 →
        若只判可连，数据依赖测试会在空库上「真跑并失败」，把「环境缺数据」
        误报成「代码有 bug」；
      * 因此内容层回归仍需对着**真库**跑（本地真实库 / 后续 nightly job），
        CI 绿只代表「不依赖生产数据」的部分。

    - ``db_available``  → 仅可连（端口 + SELECT 1）
    - ``db_has_schema`` → 可连 **且** 核心表存在 ← 结构契约类测试用这个
    - ``db_populated``  → 可连 + 有表 **且表里有行** ← 内容断言类测试用这个
    """
    if not (is_port_open() and ping()):
        return False
    if not _probe_has_schema():
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

    与 ``skip_without_db`` 的区别：空库 / 无 schema 也 skip，
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
#   needs_db    → 需要「一个可用的库」（能连上 **且** 核心表存在 = schema 完整）
#   needs_data  → 需要「库里有数据」（表存在 **且** 有行）—— 内容断言类测试
#
# 为什么需要 needs_data：
#   ``ping()`` 只跑 ``SELECT 1``，**空库也能通过** → 只判可连的话，
#   数据依赖测试会在空库上「真跑并失败」，把「环境缺数据」误报成「代码有 bug」。
#
# CI 提供 postgres + schema-only 还原（实测数据，2026-11-10）：
#   不提供 postgres（不可达）    →  0 failed / 620 passed / 161 skipped
#   提供 postgres 但空库无 schema → 102 failed（89+13）/ 654 passed / 25 skipped
#   提供 postgres + schema-only   → 结构契约类真跑、数据类 skip（CI 采用此档）
#   schema-only 还原成本：psql -f db/schema.sql ≈ 0.3s，197 个对象，与生产库一致。
#   数据内容层回归仍需对着真库跑（本地真实库 / 后续 nightly job）。
# ─────────────────────────────────────────────────────────────────────────────
_DB_MARKERS = ("needs_db", "needs_data")


def pytest_configure(config: pytest.Config) -> None:
    for marker in _DB_MARKERS:
        if marker not in config.getini("markers"):
            config.addinivalue_line(
                "markers",
                f"{marker}: 需要 PostgreSQL 的测试（DB 不可用/无 schema/无数据时自动 skip）",
            )


def pytest_collection_modifyitems(config: pytest.Config, items) -> None:
    """给标记了 needs_db / needs_data 的测试注入 skip 条件。

    判定在 collection 阶段做一次，避免每个用例重复探活。

    三档门控（2026-11-10）：
      1) 库不可达          → needs_db 与 needs_data 全部 skip
      2) 可达但无 schema    → needs_db 与 needs_data 全部 skip
      3) 可达 + 有 schema   → needs_db **真跑**；needs_data 若表里无行仍 skip
    """
    need_db = [it for it in items if it.get_closest_marker("needs_db")]
    need_data = [it for it in items if it.get_closest_marker("needs_data")]
    if not need_db and not need_data:
        return

    from backend.core.db import is_port_open, ping

    reachable = is_port_open() and ping()
    has_schema = reachable and _probe_has_schema()
    populated = False
    if has_schema:
        try:
            from backend.core.db import batch_query

            populated = bool(
                batch_query(f"SELECT 1 AS ok FROM {_POPULATION_PROBE_TABLE} LIMIT 1")
            )
        except Exception:  # noqa: BLE001 - 表不存在 → 视为无数据
            populated = False

    if need_db and not has_schema:
        skip = pytest.mark.skip(reason="needs_db: 无可用库（不可达或缺 schema）— 跳过")
        for it in need_db:
            it.add_marker(skip)
    if need_data and not populated:
        skip = pytest.mark.skip(reason="needs_data: 数据库无数据（空表）— 跳过")
        for it in need_data:
            it.add_marker(skip)
