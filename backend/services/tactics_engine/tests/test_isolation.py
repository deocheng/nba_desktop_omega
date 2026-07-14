"""Requirement 6 — Four-layer isolation red line (architecture §11).

Static checks (no execution of the app):
  - frontend/js/components/tactics.js must NOT contain coordinate math
    (map_xy_to_svg / map_point / _lerp / interpolation / psycopg2); it only
    consumes pre-mapped x_px/y_px via requestAnimationFrame + SVG render.
  - backend/api/routers/tactics.py must NOT import psycopg2 and must NOT
    contain inline SQL (pure orchestration: imports engine, returns envelope).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[4])  # .../nba_desktop_omega
FRONTEND = os.path.join(ROOT, "frontend", "js", "components", "tactics.js")
ROUTER = os.path.join(ROOT, "backend", "api", "routers", "tactics.py")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_frontend_has_no_coordinate_calculation():
    src = _read(FRONTEND)
    forbidden = ["map_xy_to_svg", "map_point", "_lerp", "interpolat", "psycopg2"]
    for token in forbidden:
        assert token not in src, f"frontend contains forbidden token: {token}"


def test_frontend_consumes_premapped_coords_and_uses_raf():
    src = _read(FRONTEND)
    # advances frames with rAF, consumes engine-pre-mapped pixels
    assert "requestAnimationFrame" in src
    assert "x_px" in src and "y_px" in src


def test_router_has_no_psycopg2_and_no_inline_sql():
    src = _read(ROUTER)
    assert "psycopg2" not in src
    for kw in ("select", "insert", "update", "delete", "cursor(", "execute("):
        assert kw not in src.lower(), f"router contains forbidden SQL token: {kw}"


def test_router_imports_only_engine_and_fastapi():
    src = _read(ROUTER)
    assert "from backend.services.tactics_engine import" in src
    # no direct coordinate-mapping import in the orchestration layer
    assert "coords" not in src
    assert "map_xy_to_svg" not in src
