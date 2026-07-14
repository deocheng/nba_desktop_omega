"""NBACore v8.2 §2 Layer 1 — Intelligence Loader.

Sole DB access for the Intelligence Engine. Mirrors
``backend.data_layer.batch_loader``: season filter is MANDATORY, player
filtering uses IN-clause batches (never a per-player loop), and every query
passes through ``backend.core.db.batch_query`` (the single DB entry point).

No psycopg2 import here, no dynamic SQL, no compute logic — this module only
fetches rows. All intelligence math lives in the sibling compute modules.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.core.db import batch_query
from backend.data_layer.schema import get_schema
from backend.services.intelligence_engine.season_type import normalize_season_type

logger = logging.getLogger("nbacore.data.intel")


def _build_in_clause(values: list[Any]) -> tuple[str, tuple]:
    if not values:
        raise ValueError("IN-clause requires at least one value (no empty batches)")
    placeholders = ",".join(["%s"] * len(values))
    return f"({placeholders})", tuple(values)


def load_player_intel(
    season: int,
    season_type: str = "Regular",
    player_ids: list[str] | None = None,
) -> list[dict]:
    """Batch load fact_player_season_stats for a season + season_type.

    Args:
        season: required NBA season (v8 §2 mandate).
        season_type: 'Regular' | 'Playoffs' | 'PlayIn' (normalized).
        player_ids: optional BBR player_id IN-clause filter.

    Returns: list[dict] of player season rows (all 74 columns available).
    """
    st = normalize_season_type(season_type)
    schema = get_schema("fact_player_season_stats")

    sql = f"SELECT * FROM {schema.name} WHERE {schema.season_col} = %s AND season_type = %s"
    params: list[Any] = [season, st]
    if player_ids:
        clause, in_params = _build_in_clause(player_ids)
        sql += f" AND {schema.player_col} IN {clause}"
        params.extend(in_params)
    return batch_query(sql, tuple(params))


def load_team_intel(season: int) -> list[dict]:
    """Batch load fact_team_season_stats for a season (all 30 teams).

    NOTE: the team fact table carries only regular-season totals (its
    `playoffs` column is a qualification flag, not a game-type split). Team
    pace/minutes are therefore regular-season figures regardless of the
    player season_type requested upstream.
    """
    schema = get_schema("fact_team_season_stats")
    sql = f"SELECT * FROM {schema.name} WHERE {schema.season_col} = %s"
    return batch_query(sql, (season,))


def load_player_shooting(
    player_id: str,
    season: int,
    season_type: str = "Regular",
) -> list[dict]:
    """Batch load player_shooting zone splits for one player + season.

    Used by the Scoring Profile module (v8.2 §10). Returns the BR shot-zone
    rows; there is typically exactly one row per (player, season, season_type).
    """
    st = normalize_season_type(season_type)
    schema = get_schema("player_shooting")
    sql = (
        f"SELECT * FROM {schema.name} "
        f"WHERE {schema.season_col} = %s AND season_type = %s AND {schema.player_col} = %s"
    )
    return batch_query(sql, (season, st, player_id))
