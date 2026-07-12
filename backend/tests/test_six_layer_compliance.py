"""NBACore v8 §6 four-layer isolation compliance guard (v8.3.2).

Two invariants:
  1. No router file in ``backend/api/routers/*.py`` may contain a raw SQL
     substring (``"SELECT "`` / ``"INSERT "`` / ``"UPDATE "`` / ``"DELETE "`` /
     ``"CREATE "`` with a trailing space). All SQL must live in the engine's
     ``*_queries`` modules or in ``workspace_db`` (the authorized write layer).
  2. ``ab_constants.NODE_TYPES`` must be exactly the five P0 node types so the
     frontend and backend share a single source of truth.
"""
from __future__ import annotations

import pathlib

from backend.services.analytics_builder_engine import ab_constants as C

ROUTERS_DIR = pathlib.Path(__file__).resolve().parents[1] / "api" / "routers"

# Raw SQL substrings that must NEVER appear inside a router file (v8 §6).
_FORBIDDEN = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "CREATE ")

EXPECTED_NODE_TYPES = {"source", "filter", "aggregate", "transform", "visualize"}


def test_routers_contain_no_sql_substrings():
    router_files = sorted(ROUTERS_DIR.glob("*.py"))
    assert router_files, "no router files found"
    violations = []
    for f in router_files:
        text = f.read_text(encoding="utf-8")
        for sub in _FORBIDDEN:
            if sub in text:
                violations.append((f.name, sub))
    assert not violations, f"SQL substrings found in routers: {violations}"


def test_node_types_exactly_p0():
    assert set(C.NODE_TYPES) == EXPECTED_NODE_TYPES
