"""NBACore v8.3.2 — Analytics Builder read-layer SQL (SELECT only).

Every SELECT issued by the engine lives HERE and is executed through
``db.batch_query`` (core.db hard-rejects anything but SELECT). Table names come
from the introspection white-list; column names come from introspection results
— nothing user-supplied is ever concatenated into a SQL identifier, so there is
no injection surface (v8 §6).

NOTE on node scope: per the execution model, ``source`` is the only node that
reads from PostgreSQL. ``filter`` / ``aggregate`` / ``transform`` operate on the
in-memory Table produced upstream (pure Python in ``ab_executors``), which is
more robust for post-derivation aggregation and still satisfies §6 (no SQL
outside this module; computation in the engine is allowed).
"""
from __future__ import annotations

from typing import Any

from backend.core import db
from backend.services.analytics_builder_engine import ab_constants as C
from backend.services.analytics_builder_engine.ab_utils import _pg_type_to_logical


def _whitelisted_tables() -> set[str]:
    """Tables whose name matches the introspection white-list (minus _bak)."""
    rows = db.batch_query(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public'"
    )
    out: set[str] = set()
    for r in rows:
        name = r["table_name"]
        if not name.startswith(C.INTROSPECTION_PREFIXES):
            continue
        if any(sub in name for sub in C.INTROSPECTION_EXCLUDE_SUBSTR):
            continue
        out.add(name)
    return out


def introspect_tables() -> list[dict]:
    """Return ``[{name, columns:[{name, type}]}]`` for analytic tables.

    Columns are ordered by their ordinal position in the table. Column ``type``
    is one of {text, int, float, bool}.
    """
    allowed = _whitelisted_tables()
    if not allowed:
        return []
    placeholders = ", ".join(["%s"] * len(allowed))
    params = list(allowed)
    rows = db.batch_query(
        "SELECT table_name, column_name, data_type, ordinal_position "
        "FROM information_schema.columns "
        f"WHERE table_schema = 'public' AND table_name IN ({placeholders}) "
        "ORDER BY table_name, ordinal_position",
        params,
    )
    by_table: dict[str, list[dict]] = {}
    for r in rows:
        tname = r["table_name"]
        by_table.setdefault(tname, []).append(
            {"name": r["column_name"], "type": _pg_type_to_logical(r["data_type"])}
        )
    return [
        {"name": t, "columns": cols}
        for t, cols in sorted(by_table.items())
    ]


def get_workspace_datasets(workspace_id: int) -> list[dict]:
    """Resolve datasets mounted on a workspace.

    O1 decision: there is NO ``datasets`` table in this deployment and
    ``workspace_datasets`` is empty, so the ``workspace_dataset`` source mode is
    deferred to P1. This helper therefore returns ``[]`` (the frontend hides the
    option). If a stored flow tries the dataset mode, the source executor
    returns a clear Chinese error instead of crashing.
    """
    return []


def build_source_sql(
    table: str,
    season_from: int | None,
    season_to: int | None,
    limit: int,
    has_season_col: bool,
) -> tuple[str, list[Any]]:
    """Build a parameterized SELECT for a source (table) node.

    ``table`` MUST come from the introspection white-list (caller guarantees
    this). Season filter is only appended when the table actually exposes a
    ``season`` column (``has_season_col``). Limit is bounded by ROW_LIMIT.
    """
    params: list[Any] = []
    clauses: list[str] = []
    if has_season_col and season_from is not None and season_to is not None:
        clauses.append("season BETWEEN %s AND %s")
        params.append(int(season_from))
        params.append(int(season_to))
    limit = max(1, min(int(limit), C.ROW_LIMIT))
    params.append(limit)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM {table}{where} LIMIT %s"
    return sql, params


def get_allowed_tables() -> set[str]:
    """Public accessor for the whitelisted analytic table names."""
    return _whitelisted_tables()


def get_table_columns(table: str) -> list[dict]:
    """Return ``[{name, type}]`` for one whitelisted table.

    ``table`` MUST be in the introspection white-list (enforced here); it is
    then bound as a parameter in an INFORMATION_SCHEMA query, so there is no
    identifier injection surface (v8 §6).
    """
    allowed = _whitelisted_tables()
    if table not in allowed:
        raise ValueError(f"表 {table!r} 不在允许的分析表白名单内")
    rows = db.batch_query(
        "SELECT column_name, data_type, ordinal_position "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s "
        "ORDER BY ordinal_position",
        (table,),
    )
    return [
        {"name": r["column_name"], "type": _pg_type_to_logical(r["data_type"])}
        for r in rows
    ]
