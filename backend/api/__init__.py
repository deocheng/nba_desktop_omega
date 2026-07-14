"""NBACore v8 §2 Layer 3 — API Layer (pure orchestration).

This package contains FastAPI routers that:
    - Call metric_engine for ALL computation
    - Call metric_engine wrappers for data fetches (no direct data_layer imports)
    - Return Pydantic-validated structured responses

v8 §6 forbidden in this package:
    - no SQL strings (SELECT/FROM/WHERE)
    - no pandas operations
    - no psycopg2 imports
    - no computation (sum/mean/aggregation/filtering logic)
    - no business logic beyond request routing + response shaping
"""
from backend.api.routers import batch, metrics, players, vs

__all__ = ["players", "metrics", "vs", "batch"]
