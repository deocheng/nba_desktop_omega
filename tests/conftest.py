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

from backend.core import config  # noqa: F401  导入即加载 .env → os.environ
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
    """True only if a live PostgreSQL is reachable."""
    return is_port_open() and ping()


def skip_without_db(db_available: bool):
    """Helper for tests that need a live DB."""
    if not db_available:
        pytest.skip("PostgreSQL not available — set DB_PORT and start service")
