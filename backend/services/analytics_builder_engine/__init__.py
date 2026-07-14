"""NBACore v8.3.2 — Analytics Builder engine package (public facade).

The router and CLI consume only these names. All SQL funnels through
``ab_queries`` (``db.batch_query``) and all flow persistence through
``workspace_db``; this engine never touches psycopg2 directly.
"""
from __future__ import annotations

from backend.services.analytics_builder_engine.ab_service import get_meta, run_flow
from backend.services.analytics_builder_engine.ab_validation import (
    FlowValidationError,
    validate_flow,
)

__all__ = [
    "run_flow",
    "get_meta",
    "validate_flow",
    "FlowValidationError",
]
