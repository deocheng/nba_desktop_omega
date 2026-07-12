"""NBACore v8 §2 Layer 1 — Cross-table Join Batch Loaders.

Single batch query that returns joined data, avoiding multiple round-trips.
The metric engine (Phase 2) consumes these to build enriched matrices.

All loaders enforce the v8 §2 season filter (required parameter).
"""
from __future__ import annotations

import logging

from psycopg2 import sql as psql

from backend.core.db import batch_query, batch_query_composed
from backend.data_layer.schema import get_schema

logger = logging.getLogger("nbacore.data.joins")

# Safety cap — same as batch_loader.MAX_GAMELOG_ROWS
# (redeclared here to avoid circular import; keep in sync)
_MAX_GAMELOG_ROWS = 200_000

# ── v8 §6 weight JOIN helper (A2: JOIN-at-read, never physical回填) ──
# Player-key columns that may be used to JOIN dim_players for weight.
# Restricted to a trusted allowlist — the column name is bound via
# psycopg2.sql.Identifier (never interpolated as a raw string). This is the
# §6 red line: no string concatenation of table/column identifiers.
_WEIGHT_JOIN_KEYS = ("player_id", "br_player_id", "player", "player_name")


def join_player_weight(key_col: str, table_alias: str = "fact") -> "psql.Composed":
    """Return a LEFT JOIN clause (psycopg2.sql.Composed) that brings
    ``weight_lbs`` / ``weight_kg`` from ``dim_players`` into a query whose
    player-key column is ``key_col``.

    The local key column and the driving-table alias are bound with
    :class:`psycopg2.sql.Identifier` — no string concatenation of identifiers
    (v8 §6 red line). The fragment is meant to be composed into a larger
    :func:`psycopg2.sql.SQL` query and executed via
    :func:`backend.core.db.batch_query_composed`.

    Args:
        key_col: local player-key column on the driving table. Must be one of
            :data:`_WEIGHT_JOIN_KEYS`.
        table_alias: alias of the driving table in the outer query.

    Returns:
        sql.Composed fragment, e.g.::

            LEFT JOIN dim_players p_w ON <alias>.<key_col> = p_w.player_id
    """
    if key_col not in _WEIGHT_JOIN_KEYS:
        raise ValueError(
            f"join_player_weight: key_col {key_col!r} not in allowed "
            f"{_WEIGHT_JOIN_KEYS}"
        )
    if not table_alias or not table_alias.isidentifier():
        raise ValueError(f"join_player_weight: invalid table_alias {table_alias!r}")
    return psql.SQL(
        " LEFT JOIN dim_players p_w ON {alias}.{key} = p_w.player_id"
    ).format(alias=psql.Identifier(table_alias), key=psql.Identifier(key_col))


def select_weight_cols(alias: str = "p_w") -> "psql.Composed":
    """Return the weight SELECT fragment for use with :func:`join_player_weight`.

    Args:
        alias: dim_players alias used in :func:`join_player_weight`
            (default ``'p_w'``).

    Returns:
        sql.Composed fragment::

            p_w.weight_lbs AS weight_lbs, p_w.weight_kg AS weight_kg
    """
    if not alias or not alias.isidentifier():
        raise ValueError(f"select_weight_cols: invalid alias {alias!r}")
    return psql.SQL(
        "{alias}.weight_lbs AS weight_lbs, {alias}.weight_kg AS weight_kg"
    ).format(alias=psql.Identifier(alias))


def load_player_gamelog_with_game_context(
    season: int, player_id: str | None = None
) -> list[dict]:
    """Batch load player_gamelog joined with dim_games (game date, teams, scores).

    Single query — avoids N+1 game lookups per gamelog row.
    Returns gamelog columns + game_date + home/away team + pts + weight.

    Args:
        season: required NBA season filter.
        player_id: optional BBR player_id filter. When provided, only that
            player's gamelog rows are loaded (keeps the full-season scan
            out of the hot path). When None the original full-season load
            behavior is preserved (backward compatible).

    Safety: checks row count before loading to prevent OOM on desktop EXE.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    gl = get_schema("player_gamelog")
    dg = get_schema("dim_games")

    count_sql = f"SELECT COUNT(*) AS cnt FROM {gl.name} WHERE {gl.season_col} = %s"
    count_params: tuple = (season,)
    if player_id:
        count_sql += f" AND {gl.player_col} = %s"
        count_params = (season, player_id)
    count_rows = batch_query(count_sql, count_params)
    row_count = count_rows[0]["cnt"] if count_rows else 0
    if row_count > _MAX_GAMELOG_ROWS:
        raise ValueError(
            f"load_player_gamelog_with_game_context: season {season} has "
            f"{row_count:,} rows, exceeds safety cap of {_MAX_GAMELOG_ROWS:,}."
        )
    logger.info(
        "load_player_gamelog_with_game_context: load | season=%s | player_id=%s | rows=%d",
        season, player_id, row_count,
    )

    weight_join = join_player_weight(gl.player_col, table_alias="g")
    weight_cols = select_weight_cols("p_w")
    sql = psql.SQL(
        """
        SELECT
            g.*,
            d.game_date, d.home_team_abbr, d.away_team_abbr,
            d.home_pts, d.away_pts, d.home_wl, d.away_wl, d.season_type,
            {weight_cols}
        FROM {gl} g
        LEFT JOIN {dg} d
          ON g.gameid = d.nba_api_id::text
        {weight_join}
        WHERE g.{season_col} = %s
        """
    ).format(
        weight_cols=weight_cols,
        gl=psql.Identifier(gl.name),
        dg=psql.Identifier(dg.name),
        weight_join=weight_join,
        season_col=psql.Identifier(gl.season_col),
    )
    params: tuple = (season,)
    if player_id:
        sql = psql.SQL(
            "{sql} AND g.{player_col} = %s"
        ).format(sql=sql, player_col=psql.Identifier(gl.player_col))
        params = (season, player_id)
    return batch_query_composed(sql, params)


def load_player_season_stats_with_bio(season: int) -> list[dict]:
    """Batch load fact_player_season_stats joined with dim_players (bio).

    Single query — returns season stats + player bio (height, weight, position).
    Weight (lbs + kg) is surfaced via the existing dim_players join (A2
    JOIN-at-read; no physical column is added to the fact table).
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    fps = get_schema("fact_player_season_stats")
    dp = get_schema("dim_players")
    sql = f"""
        SELECT
            s.*,
            p.height_cm, p.weight_lbs, p.weight_kg, p.position AS bio_position,
            p.college, p.nationality
        FROM {fps.name} s
        LEFT JOIN {dp.name} p
          ON s.{fps.player_col} = p.{dp.player_col}
        WHERE s.{fps.season_col} = %s
    """
    return batch_query(sql, (season,))
