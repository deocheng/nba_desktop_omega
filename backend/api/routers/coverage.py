"""NBACore v8 §2 Layer 3 — /coverage router (pure orchestration).

Data-coverage timeline dashboard endpoint. This router contains NO SQL and NO
filesystem access — it only calls :func:`backend.data_layer.coverage_loader
.get_coverage`, which is the sole owner of DB + filesystem reads (v8 §6 four
layer isolation). The frontend (``frontend/coverage.html``) polls this endpoint
to render a heatmap + span bars highlighting coverage gaps.
"""
from __future__ import annotations

from fastapi import APIRouter

from backend.data_layer.coverage_loader import get_coverage

router = APIRouter(prefix="/coverage", tags=["coverage"])


@router.get("")
def coverage() -> dict:
    """Return per-category data-coverage timeline (season + attribute).

    The JSON is computed entirely by the data layer. Shape::

        {
          "generated_at": "2026-07-19T...",
          "fetch_duration_seconds": 1.83,
          "seasons": ["1947-48", ..., "2025-26"],
          "reference": {"dim_games": {"1947-48": 350, ...}},
          "datasets": [
            {"key": "play_by_play", "label": "逐回合 PBP", "by": "season",
             "coverage": {"1947-48": {"count": 0, "expected": 350, "pct": 0.0}, ...},
             "span": {"first": "2025-26", "last": "2025-26"},
             "source": "...", "approx": false, "note": "..."},
            ...
          ]
        }
    """
    return get_coverage()
