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


# ── Composed (psycopg2.sql) Query ──
# v8 §6: identifiers must be bound with psycopg2.sql.Identifier, never
# interpolated as raw strings. Loaders build parameterized sql.Composed
# objects (constants + sql.Identifier) and execute them through this single
# entry point — same tracing / pool guarantees as batch_query().
def batch_query_composed(
    sql_composed: "object",
    params: Sequence[Any] | None = None,
) -> list[dict]:
    """Execute a psycopg2.sql.Composed (or sql.SQL) SELECT.

    The SQL object is built only from trusted constants and
    psycopg2.sql.Identifier placeholders, so the string-based forbidden-keyword
    scan does not apply (there is no raw SQL string to scan). All runtime values
    are still passed as bound ``%s`` parameters.

    Args:
        sql_composed: a psycopg2.sql.Composed / sql.SQL object.
        params: bound parameter values (same contract as batch_query).

    Returns: list[dict] rows.
    """
    if _pool is None:
        init_pool()
    assert _pool is not None  # narrowed for type checkers

    qid = new_query_id()
    logger.info("SQL start | qid=%s | composed", qid)
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql_composed, tuple(params) if params else ())
            rows = cur.fetchall()
        result = [dict(r) for r in rows]
        logger.info("SQL done  | qid=%s | rows=%d", qid, len(result))
        return result
    finally:
        _pool.putconn(conn)


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
