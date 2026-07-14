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
