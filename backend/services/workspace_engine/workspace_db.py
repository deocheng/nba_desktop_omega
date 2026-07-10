"""NBACore v8.3.1 — Workspace write-path Data Layer (DEDICATED WRITER).

IMPORTANT — architectural boundary (v8 §2 / §6):
    The analytics read path in `backend.core.db` is deliberately SELECT-only
    (it hard-rejects INSERT/UPDATE/DELETE/CREATE). Workspace persistence needs
    writes, so THIS module is the *designated* Data Layer for the Workspace
    module. It is the only module in `workspace_engine` that imports psycopg2;
    the API and compute layers never touch psycopg2 directly (v8 §2 / §5.5).

v8 §6 compliance:
    - NO dynamic SQL: every statement is a hardcoded constant; column names in
      SET/WHERE fragments are drawn from a fixed literal set, never from user
      input. All values are bound via parameterized queries (%s).
    - DDL is idempotent CREATE TABLE IF NOT EXISTS (hardcoded constants).
    - No eval()/exec(); no per-row loops over DB writes.
"""
from __future__ import annotations

import logging
from typing import Any

from psycopg2.extras import Json, RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from backend.core import config

logger = logging.getLogger("nbacore.workspace_db")

_pool: ThreadedConnectionPool | None = None
_schema_ready = False

# ── Idempotent DDL (hardcoded constants — NOT dynamic SQL) ──
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workspaces (
    id          SERIAL PRIMARY KEY,
    owner_id    INTEGER NOT NULL DEFAULT 1,
    name        TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS workspace_datasets (
    id          SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL,
    dataset_id   INTEGER NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, dataset_id)
);
CREATE TABLE IF NOT EXISTS workspace_formulas (
    id          SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL,
    formula_id   INTEGER NOT NULL,
    UNIQUE (workspace_id, formula_id)
);
CREATE TABLE IF NOT EXISTS workspace_charts (
    id           SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL,
    name         TEXT NOT NULL DEFAULT 'chart',
    chart_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ws_datasets_ws ON workspace_datasets(workspace_id);
CREATE INDEX IF NOT EXISTS ix_ws_formulas_ws ON workspace_formulas(workspace_id);
CREATE INDEX IF NOT EXISTS ix_ws_charts_ws   ON workspace_charts(workspace_id);
"""


def init_pool() -> None:
    """Initialize the dedicated workspace write pool (1-10 connections)."""
    global _pool
    if _pool is not None:
        return
    _pool = ThreadedConnectionPool(
        1, 10, **config.DB_CONFIG, cursor_factory=RealDictCursor
    )
    logger.info("workspace_db pool initialized")


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("workspace_db pool closed")


def ensure_schema() -> None:
    """Create workspace tables if absent (idempotent, memoized per process)."""
    global _schema_ready
    if _schema_ready:
        return
    if _pool is None:
        init_pool()
    assert _pool is not None
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA_SQL)
        conn.commit()
        _schema_ready = True
        logger.info("workspace schema ensured")
    finally:
        _pool.putconn(conn)


def _conn():
    if _pool is None:
        init_pool()
    return _pool.getconn()


def _put(conn) -> None:
    _pool.putconn(conn)


# ── Workspace DML ──

def insert_workspace(name: str, owner_id: int, description: str, status: str) -> dict:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workspaces (name, owner_id, description, status) "
                "VALUES (%s, %s, %s, %s) RETURNING id, created_at, updated_at",
                (name, owner_id, description, status),
            )
            row = cur.fetchone()
        conn.commit()
        return dict(row)
    finally:
        _put(conn)


def select_workspace(workspace_id: int) -> dict | None:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM workspaces WHERE id = %s", (workspace_id,))
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        _put(conn)


def select_workspaces(
    owner_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    ensure_schema()
    clauses: list[str] = []
    params: list[Any] = []
    if owner_id is not None:
        clauses.append("owner_id = %s")
        params.append(owner_id)
    if status is not None:
        clauses.append("status = %s")
        params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.extend([limit, offset])
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM workspaces{where} ORDER BY id DESC LIMIT %s OFFSET %s",
                tuple(params),
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        _put(conn)


def update_workspace(
    workspace_id: int,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> dict | None:
    ensure_schema()
    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        sets.append("name = %s")
        params.append(name)
    if description is not None:
        sets.append("description = %s")
        params.append(description)
    if status is not None:
        sets.append("status = %s")
        params.append(status)
    if not sets:
        return select_workspace(workspace_id)
    sets.append("updated_at = now()")
    params.append(workspace_id)
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE workspaces SET {', '.join(sets)} "
                f"WHERE id = %s RETURNING id, created_at, updated_at",
                tuple(params),
            )
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None
    finally:
        _put(conn)


def delete_workspace(workspace_id: int) -> bool:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM workspace_datasets WHERE workspace_id = %s", (workspace_id,)
            )
            cur.execute(
                "DELETE FROM workspace_formulas WHERE workspace_id = %s", (workspace_id,)
            )
            cur.execute(
                "DELETE FROM workspace_charts WHERE workspace_id = %s", (workspace_id,)
            )
            cur.execute("DELETE FROM workspaces WHERE id = %s", (workspace_id,))
            deleted = cur.rowcount
        conn.commit()
        return deleted > 0
    finally:
        _put(conn)


# ── Dataset links ──

def insert_dataset_link(workspace_id: int, dataset_id: int) -> int | None:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workspace_datasets (workspace_id, dataset_id) "
                "VALUES (%s, %s) ON CONFLICT (workspace_id, dataset_id) DO NOTHING "
                "RETURNING id",
                (workspace_id, dataset_id),
            )
            row = cur.fetchone()
        conn.commit()
        return row["id"] if row else None
    finally:
        _put(conn)


def delete_dataset_link(workspace_id: int, dataset_id: int) -> bool:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM workspace_datasets "
                "WHERE workspace_id = %s AND dataset_id = %s",
                (workspace_id, dataset_id),
            )
            n = cur.rowcount
        conn.commit()
        return n > 0
    finally:
        _put(conn)


def select_dataset_ids(workspace_id: int) -> list[int]:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT dataset_id FROM workspace_datasets "
                "WHERE workspace_id = %s ORDER BY id",
                (workspace_id,),
            )
            rows = cur.fetchall()
        return [r["dataset_id"] for r in rows]
    finally:
        _put(conn)


# ── Formula links ──

def insert_formula_link(workspace_id: int, formula_id: int) -> int | None:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workspace_formulas (workspace_id, formula_id) "
                "VALUES (%s, %s) ON CONFLICT (workspace_id, formula_id) DO NOTHING "
                "RETURNING id",
                (workspace_id, formula_id),
            )
            row = cur.fetchone()
        conn.commit()
        return row["id"] if row else None
    finally:
        _put(conn)


def delete_formula_link(workspace_id: int, formula_id: int) -> bool:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM workspace_formulas "
                "WHERE workspace_id = %s AND formula_id = %s",
                (workspace_id, formula_id),
            )
            n = cur.rowcount
        conn.commit()
        return n > 0
    finally:
        _put(conn)


def select_formula_ids(workspace_id: int) -> list[int]:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT formula_id FROM workspace_formulas "
                "WHERE workspace_id = %s ORDER BY id",
                (workspace_id,),
            )
            rows = cur.fetchall()
        return [r["formula_id"] for r in rows]
    finally:
        _put(conn)


# ── Charts ──

def insert_chart(workspace_id: int, name: str, chart_config: dict) -> int:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workspace_charts (workspace_id, name, chart_config) "
                "VALUES (%s, %s, %s) RETURNING id",
                (workspace_id, name, Json(chart_config)),
            )
            row = cur.fetchone()
        conn.commit()
        return row["id"]
    finally:
        _put(conn)


def update_chart(
    chart_id: int,
    name: str | None = None,
    chart_config: dict | None = None,
) -> dict | None:
    ensure_schema()
    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        sets.append("name = %s")
        params.append(name)
    if chart_config is not None:
        sets.append("chart_config = %s")
        params.append(Json(chart_config))
    if not sets:
        return select_chart(chart_id)
    params.append(chart_id)
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE workspace_charts SET {', '.join(sets)} "
                f"WHERE id = %s RETURNING *",
                tuple(params),
            )
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None
    finally:
        _put(conn)


def delete_chart(chart_id: int) -> bool:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM workspace_charts WHERE id = %s", (chart_id,))
            n = cur.rowcount
        conn.commit()
        return n > 0
    finally:
        _put(conn)


def select_chart(chart_id: int) -> dict | None:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM workspace_charts WHERE id = %s", (chart_id,))
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        _put(conn)


def select_charts(workspace_id: int) -> list[dict]:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM workspace_charts WHERE workspace_id = %s ORDER BY id",
                (workspace_id,),
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        _put(conn)


# ── Duplicate (copy resource links to a fresh workspace) ──

def copy_links(target_id: int, source_id: int) -> None:
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workspace_datasets (workspace_id, dataset_id) "
                "SELECT %s, dataset_id FROM workspace_datasets "
                "WHERE workspace_id = %s ON CONFLICT DO NOTHING",
                (target_id, source_id),
            )
            cur.execute(
                "INSERT INTO workspace_formulas (workspace_id, formula_id) "
                "SELECT %s, formula_id FROM workspace_formulas "
                "WHERE workspace_id = %s ON CONFLICT DO NOTHING",
                (target_id, source_id),
            )
            cur.execute(
                "INSERT INTO workspace_charts (workspace_id, name, chart_config) "
                "SELECT %s, name, chart_config FROM workspace_charts "
                "WHERE workspace_id = %s",
                (target_id, source_id),
            )
        conn.commit()
    finally:
        _put(conn)
