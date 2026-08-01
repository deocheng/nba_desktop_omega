"""NBACore v8 §2 Layer 1 — Batch Loader.

The ONLY module that fetches data from PostgreSQL for the metric engine.
Every function enforces the v8 §2 mandates:
    1. season filter is a REQUIRED parameter (no default, no "load all")
    2. player filtering uses IN-clause batch (never per-player loop)
    3. all SQL passes through backend.core.db.batch_query (single DB entry)

Returns plain list[dict]; Phase 2 Metric Engine will reshape into matrices.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.core.db import batch_query
from backend.data_layer.schema import get_schema, season_required

logger = logging.getLogger("nbacore.data.batch")

# Safety hard-cap for full-season gamelog loads.
# A single NBA season (regular + playoffs) can have ~100K gamelog rows.
# 200K is a generous upper bound — roughly 2 full seasons worth.
# This prevents accidental OOM on desktop EXE deployments if someone loads
# an entire season's gamelog without player filtering.
MAX_GAMELOG_ROWS = 200_000


# ── Helpers ──

def _build_in_clause(values: list[Any]) -> tuple[str, tuple]:
    """Build a parameterized IN-clause: (%s,%s,...) + params tuple."""
    if not values:
        raise ValueError("IN-clause requires at least one value (no empty batches)")
    placeholders = ",".join(["%s"] * len(values))
    return f"({placeholders})", tuple(values)


def _assert_season(schema_name: str, season: int) -> None:
    """Enforce v8 §2: season filter required for fact tables."""
    if not season_required(schema_name):
        return  # dimension table, no season filter needed
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r} for {schema_name}")


# ── Public Loaders ──

def load_player_gamelog(
    season: int,
    player_ids: list[str] | None = None,
    *,
    _bypass_limit: bool = False,
) -> list[dict]:
    """Batch load player_gamelog rows for a season.

    Args:
        season: required NBA season (e.g. 2025)
        player_ids: optional BBR br_player_id list for IN-clause filter.
                    If None, loads ALL players for the season (still batch).
        _bypass_limit: internal use only — skip the MAX_GAMELOG_ROWS safety
                       cap (e.g. for known-safe internal callers).

    Returns: list[dict] with 54 columns per row.

    Safety: when player_ids is None (full-season load), we first check the
    row count and reject if it exceeds MAX_GAMELOG_ROWS. This prevents
    accidental OOM on lightweight desktop deployments.
    """
    _assert_season("player_gamelog", season)
    schema = get_schema("player_gamelog")

    if player_ids is None and not _bypass_limit:
        count_sql = f"SELECT COUNT(*) AS cnt FROM {schema.name} WHERE {schema.season_col} = %s"
        count_rows = batch_query(count_sql, (season,))
        row_count = count_rows[0]["cnt"] if count_rows else 0
        if row_count > MAX_GAMELOG_ROWS:
            raise ValueError(
                f"load_player_gamelog: season {season} has {row_count:,} rows, "
                f"exceeds safety cap of {MAX_GAMELOG_ROWS:,}. "
                f"Pass player_ids to filter, or use paginated loading."
            )
        logger.info(
            "load_player_gamelog: full-season load | season=%s | rows=%d (cap=%d)",
            season, row_count, MAX_GAMELOG_ROWS,
        )

    sql = f"SELECT * FROM {schema.name} WHERE {schema.season_col} = %s"
    params: list[Any] = [season]
    if player_ids:
        in_clause, in_params = _build_in_clause(player_ids)
        sql += f" AND {schema.player_col} IN {in_clause}"
        params.extend(in_params)
    return batch_query(sql, tuple(params))


def load_player_season_stats(season: int) -> list[dict]:
    """Batch load fact_player_season_stats for a season (all players)."""
    _assert_season("fact_player_season_stats", season)
    schema = get_schema("fact_player_season_stats")
    sql = f"SELECT * FROM {schema.name} WHERE {schema.season_col} = %s"
    return batch_query(sql, (season,))


def load_team_season_stats(season: int) -> list[dict]:
    """Batch load fact_team_season_stats for a season (all 30 teams)."""
    _assert_season("fact_team_season_stats", season)
    schema = get_schema("fact_team_season_stats")
    sql = f"SELECT * FROM {schema.name} WHERE {schema.season_col} = %s"
    return batch_query(sql, (season,))


def load_player_team_share(season: int, player_ids: list[str] | None = None) -> list[dict]:
    """v8.1 §8 — Join player season stats with team season points.

    Produces one row per (player, season) — excluding TOT/combined team rows
    and keeping the team stint with the most games — with the player's own
    pts/g plus the team's season total pts/g. This is the Layer-1 source for
    the `team_scoring_share` metric (the cross-table join lives here, keeping
    the Metric Engine as the sole compute layer per v8 §2 isolation).

    Args:
        season: required NBA season.
        player_ids: optional BBR ID filter (IN-clause). If None, all players.

    Returns:
        list[dict] with: player_id, pts, g, team_pts, team_g.
    """
    _assert_season("fact_player_season_stats", season)
    player_schema = get_schema("fact_player_season_stats")
    team_schema = get_schema("fact_team_season_stats")

    in_clause = ""
    params: list[Any] = [season, season]
    if player_ids:
        clause, in_params = _build_in_clause(player_ids)
        in_clause = f" AND pr.player_id IN {clause}"
        params.extend(in_params)

    sql = f"""
        WITH player_ranked AS (
            SELECT player_id, season, team, pts, g,
                   ROW_NUMBER() OVER (PARTITION BY player_id, season ORDER BY g DESC) AS rn
            FROM {player_schema.name}
            WHERE season = %s AND team NOT IN ('TOT', '2TM', '3TM', '4TM')
        ),
        team_pts AS (
            -- NOTE: in this dataset `fact_team_season_stats.playoffs` is a
            -- *qualification* flag (did the team make the playoffs?), NOT a
            -- regular-vs-playoff game-type split. Every (season, abbreviation)
            -- row IS the regular-season total and is unique, so we join on
            -- (season, abbreviation) WITHOUT a playoffs filter. Filtering
            -- `playoffs = false` previously dropped ~20/30 teams per season and
            -- made team_scoring_share return None for most players (v8.1 FIX).
            SELECT abbreviation, season, pts AS team_pts, g AS team_g
            FROM {team_schema.name}
            WHERE season = %s
        )
        SELECT pr.player_id, pr.pts, pr.g, tp.team_pts, tp.team_g
        FROM player_ranked pr
        JOIN team_pts tp ON tp.abbreviation = pr.team AND tp.season = pr.season
        WHERE pr.rn = 1{in_clause}
        ORDER BY pr.player_id
    """
    return batch_query(sql, tuple(params))


def load_games(
    season: int,
    season_type: str | None = None,
) -> list[dict]:
    """Batch load dim_games for a season. Optional season_type filter."""
    _assert_season("dim_games", season)
    schema = get_schema("dim_games")
    sql = f"SELECT * FROM {schema.name} WHERE {schema.season_col} = %s"
    params: list[Any] = [season]
    if season_type:
        sql += " AND season_type = %s"
        params.append(season_type)
    return batch_query(sql, tuple(params))


def load_players(player_ids: list[str]) -> list[dict]:
    """Batch load dim_players by BBR player_id list (dimension, no season).

    This is the ONLY loader allowed without a season parameter because
    dim_players is a dimension table (v8 §2 exception for dims).
    """
    if not player_ids:
        raise ValueError("load_players requires at least one player_id")
    schema = get_schema("dim_players")
    in_clause, in_params = _build_in_clause(player_ids)
    sql = f"SELECT * FROM {schema.name} WHERE {schema.player_col} IN {in_clause}"
    return batch_query(sql, in_params)


def load_seasons_available(table_name: str = "fact_player_season_stats") -> list[int]:
    """Return distinct seasons available in a table (descending)."""
    schema = get_schema(table_name)
    if schema.season_col is None:
        raise ValueError(f"{table_name} has no season column")
    sql = f"SELECT DISTINCT {schema.season_col} AS s FROM {schema.name} ORDER BY s DESC"
    rows = batch_query(sql)
    return [int(r["s"]) for r in rows]


def load_player_honors(player_id: str) -> list[dict]:
    """Load a player's career honors from ``player_career_honors`` (bio_ext).

    Additive — does not modify any LOCKED function. Uses the Layer-1
    ``batch_query`` single entry point (SELECT-only, v8 §2 compliant).

    Args:
        player_id: BBR player_id.

    Returns:
        list[dict] with columns (player_id, honor_raw, honor_type,
        honor_count, honor_year, honor_detail). Empty list if no honors.
    """
    if not player_id:
        return []
    sql = """
        SELECT player_id, honor_raw, honor_type, honor_count, honor_year, honor_detail
        FROM public.player_career_honors
        WHERE player_id = %s
        ORDER BY honor_year NULLS LAST, honor_type, honor_raw
    """
    return batch_query(sql, (player_id,))


def search_players(name: str, limit: int = 20) -> list[dict]:
    """Search dim_players by name (case-insensitive ILIKE).

    Phase 3 extension: required for /players search endpoint.
    Additive — does not modify any Phase 1 LOCKED function.

    Args:
        name: search string (matched against player_name + full_name via ILIKE)
        limit: max results (default 20, capped at 100)

    Returns: list[dict] with dim_players columns.
    """
    if not name or len(name.strip()) < 2:
        raise ValueError("search name must be at least 2 chars")
    if limit < 1 or limit > 100:
        limit = max(1, min(limit, 100))
    schema = get_schema("dim_players")
    sql = (
        f"SELECT * FROM {schema.name} "
        f"WHERE player_name ILIKE %s OR full_name ILIKE %s "
        f"ORDER BY player_name LIMIT %s"
    )
    pattern = f"%{name.strip()}%"
    return batch_query(sql, (pattern, pattern, limit))
