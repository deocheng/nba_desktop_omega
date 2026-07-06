"""NBACore v8 §2 Layer 2.5 — Context Engine (pure Metric Engine consumer).

Context System provides higher-level analysis built ENTIRELY on top of Metric Engine.
It has NO direct database access — all data flows through Layer 2.

Three sub-systems:
    - similar_players  — cosine similarity across metric vector (same position filter)
    - role_evolution   — how a player's role changed across seasons
    - trend_analysis   — linear trend + momentum for a metric across seasons

v8 §2 compliance:
    - All data comes from Metric Engine (compute_many, rank)
    - No psycopg2 / data_layer imports
    - Computation here is "context-level (aggregation, similarity, trend)
    - Still vectorized (pandas / numpy) — no per-player Python loops
"""
from __future__ import annotations

from backend.services.context_engine.similar_players import find_similar_players
from backend.services.context_engine.role_evolution import player_role_evolution
from backend.services.context_engine.trend_analysis import player_trend

__all__ = [
    "find_similar_players",
    "player_role_evolution",
    "player_trend",
]
