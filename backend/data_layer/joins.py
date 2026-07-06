"""NBACore v8 §2 Layer 1 — Cross-table Join Batch Loaders.

Single batch query that returns joined data, avoiding multiple round-trips.
The metric engine (Phase 2) consumes these to build enriched matrices.

All loaders enforce the v8 §2 season filter (required parameter).
"""
from __future__ import annotations

import logging

from backend.core.db import batch_query
from backend.data_layer.schema import get_schema

logger = logging.getLogger("nbacore.data.joins")

# Safety cap — same as batch_loader.MAX_GAMELOG_ROWS
# (redeclared here to avoid circular import; keep in sync)
_MAX_GAMELOG_ROWS = 200_000


def load_player_gamelog_with_game_context(season: int) -> list[dict]:
    """Batch load player_gamelog joined with dim_games (game date, teams, scores).

    Single query — avoids N+1 game lookups per gamelog row.
    Returns gamelog columns + game_date + home/away team + pts.

    Safety: checks row count before loading to prevent OOM on desktop EXE.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    gl = get_schema("player_gamelog")
    dg = get_schema("dim_games")

    count_sql = f"SELECT COUNT(*) AS cnt FROM {gl.name} WHERE {gl.season_col} = %s"
    count_rows = batch_query(count_sql, (season,))
    row_count = count_rows[0]["cnt"] if count_rows else 0
    if row_count > _MAX_GAMELOG_ROWS:
        raise ValueError(
            f"load_player_gamelog_with_game_context: season {season} has "
            f"{row_count:,} rows, exceeds safety cap of {_MAX_GAMELOG_ROWS:,}."
        )
    logger.info(
        "load_player_gamelog_with_game_context: full-season load | season=%s | rows=%d",
        season, row_count,
    )

    sql = f"""
        SELECT
            g.*,
            d.game_date, d.home_team_abbr, d.away_team_abbr,
            d.home_pts, d.away_pts, d.season_type
        FROM {gl.name} g
        LEFT JOIN {dg.name} d
          ON g.gameid = d.game_id
        WHERE g.{gl.season_col} = %s
    """
    return batch_query(sql, (season,))


def load_player_season_stats_with_bio(season: int) -> list[dict]:
    """Batch load fact_player_season_stats joined with dim_players (bio).

    Single query — returns season stats + player bio (height, weight, position).
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    fps = get_schema("fact_player_season_stats")
    dp = get_schema("dim_players")
    sql = f"""
        SELECT
            s.*,
            p.height_cm, p.weight_lbs, p.position AS bio_position,
            p.college, p.nationality
        FROM {fps.name} s
        LEFT JOIN {dp.name} p
          ON s.{fps.player_col} = p.{dp.player_col}
        WHERE s.{fps.season_col} = %s
    """
    return batch_query(sql, (season,))
