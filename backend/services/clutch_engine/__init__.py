"""NBACore v8 — Clutch Engine (Layer 2 compute / aggregation).

Pure aggregation layer for "clutch time" player stats. Builds read-only
SELECT statements (``clutch_queries``), post-processes the rows
(``clutch_service``), and exposes small SQL-fragment + rating helpers
(``clutch_utils``). No pandas / no psycopg2 imports here.
"""
from __future__ import annotations

from backend.services.clutch_engine import (
    clutch_queries,
    clutch_service,
    clutch_utils,
)

__all__ = ["clutch_queries", "clutch_service", "clutch_utils"]
