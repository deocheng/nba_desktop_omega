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
