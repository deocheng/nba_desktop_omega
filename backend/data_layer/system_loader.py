"""NBACore v8 §2 Layer 1 — System Loader.

System management queries: table listing, table browsing, status summary.
All functions follow v8 §2 rules:
    - Only SELECT statements
    - All SQL passes through backend.core.db.batch_query
    - Table names validated against whitelist to prevent SQL injection
    - sort_by parameters validated against column whitelist per table

Robustness hardening (2026-07-07):
    - list_tables() uses pg_stat_user_tables (single query, no N+1, no f-string SQL)
    - get_status_summary() logs warnings instead of silently swallowing exceptions
"""
from __future__ import annotations

import logging

from backend.core.db import batch_query, ping

logger = logging.getLogger("nbacore.data_layer.system_loader")

_ALLOWED_TABLES = frozenset({
    "team_mapping",
    "team_game_splits",
    "team_summaries",
    "team_stats_per_game",
    "games",
    "play_by_play",
    "play_by_play_api",
    "player_gamelog",
    "player_per_game",
    "player_totals",
    "player_advanced",
    "player_shooting",
    "player_per_100_poss",
    "player_play_by_play",
    "player_bio",
    "player_season_splits",
    "dim_players",
    "dim_teams",
    "dim_games",
    "fact_player_season_stats",
    "fact_team_season_stats",
    "game_metadata",
    "game_id_mapping",
    "player_contracts",
    "draft_combine",
    "pbp_g5_raw",
})


def list_tables() -> list[dict]:
    """List all public tables with estimated row counts.

    Uses pg_stat_user_tables for fast single-query row count estimates.
    This avoids N+1 queries (one COUNT(*) per table) and eliminates
    f-string SQL construction — defense-in-depth against SQL injection.

    Returns:
        list[dict]: Each dict has name (table name) and rows (estimated count).
            Sorted by row count descending.
    """
    sql = """
        SELECT c.relname AS name,
               GREATEST(COALESCE(c.reltuples, 0), 0)::bigint AS rows
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY c.reltuples DESC NULLS LAST
    """
    return batch_query(sql)


def _get_table_columns(table_name: str) -> list[str]:
    """Get column names for a table (sorted by ordinal position).

    Args:
        table_name: Table name (must be in whitelist).

    Returns:
        list[str]: Column names.
    """
    sql = """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
    """
    rows = batch_query(sql, (table_name,))
    return [r["column_name"] for r in rows]


def get_table_data(
    table_name: str,
    page: int,
    per_page: int,
    search: str,
    sort_by: str,
    sort_order: str,
) -> tuple[list[dict], int, list[str]]:
    """Browse a table with pagination, search, and sort.

    Args:
        table_name: Table to browse (must be in security whitelist).
        page: Page number (1-based).
        per_page: Items per page (capped at 500).
        search: Search string (matches first text column via ILIKE).
        sort_by: Column to sort by (must be a valid column of the table).
        sort_order: 'ASC' or 'DESC'.

    Returns:
        tuple[list[dict], int, list[str]]: (rows, total_count, columns).

    Raises:
        ValueError: If table_name not in whitelist or parameters invalid.
    """
    if table_name not in _ALLOWED_TABLES:
        raise ValueError(
            f"Access denied: table {table_name!r} not in security whitelist"
        )

    if page < 1:
        raise ValueError("page must be >= 1")
    if per_page < 1:
        raise ValueError("per_page must be >= 1")
    per_page = min(per_page, 500)

    columns = _get_table_columns(table_name)
    if not columns:
        return [], 0, []

    sort_col = sort_by.strip() if sort_by else columns[0]
    if sort_col not in columns:
        sort_col = columns[0]

    sort_dir = sort_order.upper().strip() if sort_order else "ASC"
    if sort_dir not in ("ASC", "DESC"):
        sort_dir = "ASC"

    offset = (page - 1) * per_page

    where = ""
    params: list = []
    if search and search.strip():
        search_val = search.strip()
        text_cols = [c for c in columns if c in (
            "player_name", "full_name", "player", "team", "team_abbr",
            "team_name", "abbreviation", "game_id", "gameid",
            "position", "pos", "season_type", "split_type",
        )]
        if text_cols:
            search_col = text_cols[0]
            where = f"WHERE {search_col} ILIKE %s"
            params.append(f"%{search_val}%")

    total_sql = f"SELECT count(*) AS cnt FROM {table_name} {where}"
    total_rows = batch_query(total_sql, tuple(params))
    total = total_rows[0]["cnt"] if total_rows else 0

    data_sql = f"""
        SELECT * FROM {table_name}
        {where}
        ORDER BY {sort_col} {sort_dir}
        LIMIT %s OFFSET %s
    """
    rows = batch_query(data_sql, tuple(params + [per_page, offset]))
    return rows, total, columns


def get_status_summary(season: int) -> dict:
    """Full dashboard status summary.

    Aggregates table counts, team info, recent games, top scorers, etc.

    Args:
        season: NBA season (required, no default) for season-specific stats.

    Returns:
        dict: Status summary with tables, total_records, active_teams,
            last_game_date, splits info, top_scorers, recent_games, season.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")

    db_up = False
    try:
        db_up = ping()
    except Exception as e:
        logger.warning("DB connectivity check failed: %s", e)
        db_up = False

    tables = list_tables()
    total_records = sum(t["rows"] for t in tables)

    active_teams = 0
    try:
        sql = "SELECT count(*) AS cnt FROM team_mapping WHERE is_active = true"
        rows = batch_query(sql)
        if rows:
            active_teams = rows[0]["cnt"]
    except Exception as e:
        logger.warning("Failed to query active teams: %s", e)

    last_game = None
    try:
        sql = "SELECT max(game_date) AS d FROM games"
        rows = batch_query(sql)
        if rows and rows[0]["d"]:
            last_game = str(rows[0]["d"])
    except Exception as e:
        logger.warning("Failed to query last game date: %s", e)

    splits = {"teams": 0, "seasons": 0, "total": 0}
    try:
        sql = """
            SELECT count(distinct team_abbr) AS t,
                   count(distinct season) AS s,
                   count(*) AS c
            FROM team_game_splits
        """
        rows = batch_query(sql)
        if rows:
            splits = {"teams": rows[0]["t"], "seasons": rows[0]["s"], "total": rows[0]["c"]}
    except Exception as e:
        logger.warning("Failed to query splits summary: %s", e)

    top_scorers = []
    try:
        sql = """
            SELECT team_abbr, pts, games, plus_minus
            FROM team_game_splits
            WHERE season = %s AND split_type = 'total'
            ORDER BY pts DESC LIMIT 10
        """
        rows = batch_query(sql, (season,))
        top_scorers = [
            {
                "team": r["team_abbr"],
                "pts": float(r["pts"]) if r["pts"] else 0,
                "games": r["games"],
                "plus_minus": float(r["plus_minus"]) if r["plus_minus"] else 0,
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("Failed to query top scorers: %s", e)

    recent_games = []
    try:
        sql = """
            SELECT game_date, away_team_abbr, home_team_abbr, away_pts, home_pts
            FROM games WHERE game_date IS NOT NULL
            ORDER BY game_date DESC LIMIT 10
        """
        rows = batch_query(sql)
        recent_games = [
            {
                "date": str(r["game_date"]) if r["game_date"] else "",
                "away": r["away_team_abbr"],
                "home": r["home_team_abbr"],
                "away_pts": r["away_pts"],
                "home_pts": r["home_pts"],
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("Failed to query recent games: %s", e)

    return {
        "tables": tables,
        "database_connected": db_up,
        "total_tables": len(tables),
        "total_records": total_records,
        "active_teams": active_teams,
        "last_game_date": last_game,
        "splits": splits,
        "top_scorers": top_scorers,
        "recent_games": recent_games,
        "season": season,
    }
