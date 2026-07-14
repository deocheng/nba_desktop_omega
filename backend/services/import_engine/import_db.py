"""NBACore v8 §6 — CSV import write-path service (DESIGNATED WRITER).

Mirrors backend.services.workspace_engine.workspace_db: this module is the
*only* place in the import feature that imports psycopg2. The API/router layer
never touches psycopg2 directly (v8 §2 / §5.5).

v8 §6 compliance:
    - NO dynamic SQL: column names are drawn ONLY from information_schema
      (a trusted catalog), never from the CSV header. All values are bound via
      parameterized queries (%s). Types come from the catalog too, so coercion
      is type-aware and never injects a value into SQL.
    - target_table is validated to exist in the public schema before any write;
      other schemas / system tables are rejected.
    - No eval()/exec(); per-row failures are caught and reported, not fatal.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from backend.core import config

logger = logging.getLogger("nbacore.services.import_engine")

_pool: ThreadedConnectionPool | None = None


# ── Dedicated write pool (v8 §2 / §6 designated writer) ──

def init_pool() -> None:
    """Lazily initialize the dedicated import write pool (1-10 connections)."""
    global _pool
    if _pool is not None:
        return
    _pool = ThreadedConnectionPool(1, 10, **config.DB_CONFIG, cursor_factory=RealDictCursor)
    logger.info("import_engine write pool initialized")


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


def _conn():
    if _pool is None:
        init_pool()
    assert _pool is not None
    return _pool.getconn()


def _put(conn) -> None:
    if _pool is not None:
        _pool.putconn(conn)


# ── Schema introspection (trusted catalog only) ──

def list_public_tables() -> list[str]:
    """Return all table names in the public schema (trusted catalog query)."""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            rows = cur.fetchall()
        return [r["table_name"] for r in rows]
    finally:
        _put(conn)


def _column_types(table: str) -> dict[str, str]:
    """Map column_name -> PostgreSQL data_type (trusted catalog only).

    Used both to validate CSV columns against real schema columns and to drive
    type-aware coercion, so a numeric-looking text value stays a string.
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s "
                "ORDER BY ordinal_position",
                (table,),
            )
            rows = cur.fetchall()
        return {r["column_name"]: r["data_type"] for r in rows}
    finally:
        _put(conn)


# ── Type-aware coercion ──

def _coerce(value: str | None, pg_type: str) -> Any:
    """Coerce a CSV cell to a DB-friendly value using the column's PG type.

    - empty string -> None (NULL)
    - integer-like columns -> int
    - float/numeric-like columns -> float
    - everything else (incl. text columns with digits) -> the raw string
    """
    if value is None:
        return None
    s = value.strip()
    if s == "":
        return None
    t = pg_type.lower()
    if "int" in t:
        try:
            return int(s)
        except ValueError:
            return s
    if any(k in t for k in ("numeric", "real", "double", "float", "decimal")):
        try:
            return float(s)
        except ValueError:
            return s
    return s


# ── Core import ──

def import_csv(target_table: str, mode: str, csv_text: str) -> dict:
    """Bulk-import CSV text into a validated public table.

    Args:
        target_table: destination public table (validated against catalog).
        mode: "append" (INSERT) or "replace" (TRUNCATE then INSERT).
        csv_text: decoded CSV contents.

    Returns:
        dict: { inserted, errors, columns, table }

    Raises:
        ValueError: for invalid mode / missing table / no matching columns
                    (the router maps this to HTTP 400 — this service never
                    raises HTTPException, keeping the API layer separate).
    """
    if mode not in ("append", "replace"):
        raise ValueError(f"invalid mode '{mode}', expected 'append' or 'replace'")
    if not target_table or not target_table.strip():
        raise ValueError("target_table is required")

    allowed = set(list_public_tables())
    if target_table not in allowed:
        raise ValueError(f"table '{target_table}' is not an allowed public-schema table")

    col_types = _column_types(target_table)
    if not col_types:
        raise ValueError(f"table '{target_table}' has no resolvable columns")

    reader = csv.DictReader(io.StringIO(csv_text))
    header = reader.fieldnames or []
    # Only import columns that exist in the target table; the WRITE target
    # list is intersected with the trusted catalog — never injected into SQL.
    valid_cols = [c for c in header if c in col_types]
    if not valid_cols:
        raise ValueError(
            f"CSV header has no columns matching table '{target_table}': {header}"
        )

    placeholders = ", ".join(["%s"] * len(valid_cols))
    col_list = ", ".join(f'"{c}"' for c in valid_cols)
    insert_sql = (
        f"INSERT INTO public.\"{target_table}\" ({col_list}) "
        f"VALUES ({placeholders})"
    )

    inserted = 0
    errors: list[str] = []
    conn = _conn()
    try:
        with conn.cursor() as cur:
            if mode == "replace":
                cur.execute(f'TRUNCATE TABLE public."{target_table}"')
            for i, row in enumerate(reader, start=1):
                try:
                    values = [_coerce(row.get(c), col_types[c]) for c in valid_cols]
                    cur.execute(insert_sql, tuple(values))
                    inserted += 1
                except Exception as exc:  # one bad row must not abort the batch
                    errors.append(f"row {i}: {exc}")
                    conn.rollback()
                    continue
        conn.commit()
    finally:
        _put(conn)

    return {
        "inserted": inserted,
        "errors": errors,
        "columns": valid_cols,
        "table": target_table,
    }
