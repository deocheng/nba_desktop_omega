"""NBACore v8 §2 Layer 1 — Player Chart Loader.

Player chart-related data queries for the v8 data layer.
All functions follow v8 §2 rules:
    - season parameter is REQUIRED (no default)
    - Only SELECT statements
    - All SQL passes through backend.core.db.batch_query
    - Returns list[dict]
    - sort_by parameters validated against whitelists to prevent SQL injection
"""
from __future__ import annotations

from backend.core.db import batch_query

def compute_box_stats(values: list[float]) -> dict:
    """Compute box plot statistics (min, Q1, median, Q3, max).

    Uses linear interpolation for percentile calculation.
    Moved from API layer (charts.py) to data layer per v8 §2.

    Args:
        values: List of numeric values.

    Returns:
        dict: Box plot stats with keys min, q1, median, q3, max.
            All values rounded to 2 decimal places.
    """
    if not values:
        return {"min": 0, "q1": 0, "median": 0, "q3": 0, "max": 0}
    sorted_vals = sorted(values)
    min_val = sorted_vals[0]
    max_val = sorted_vals[-1]

    def percentile(data: list[float], p: float) -> float:
        k = (len(data) - 1) * p
        f = int(k)
        c = f + 1 if f + 1 < len(data) else f
        return data[f] + (k - f) * (data[c] - data[f])

    q1 = percentile(sorted_vals, 0.25)
    median = percentile(sorted_vals, 0.5)
    q3 = percentile(sorted_vals, 0.75)

    return {
        "min": round(min_val, 2),
        "q1": round(q1, 2),
        "median": round(median, 2),
        "q3": round(q3, 2),
        "max": round(max_val, 2),
    }


_ALLOWED_ADVANCED_SORTS = {
    "per", "ts_percent", "usg_percent", "ast_percent",
    "tov_percent", "stl_percent", "blk_percent",
    "bpm", "vorp", "ws", "ows", "dws",
}

_ALLOWED_PER_GAME_SORTS = {
    "pts", "reb", "ast", "stl", "blk", "tov",
    "fg_pct", "fg3_pct", "ft_pct", "mp",
}

_PER_GAME_COL_MAP = {
    "pts": "pts_per_game",
    "reb": "trb_per_game",
    "ast": "ast_per_game",
    "stl": "stl_per_game",
    "blk": "blk_per_game",
    "tov": "tov_per_game",
    "fg_pct": "fg_percent",
    "fg3_pct": "x3p_percent",
    "ft_pct": "ft_percent",
    "mp": "mp_per_game",
}


def get_scoring_distribution(season: int, min_games: int) -> list[dict]:
    """Player scoring distribution data for box plots.

    Returns per-game stat values for all qualifying players.
    Box plot statistics (min/q1/median/q3/max) can be computed
    by the caller from this raw data.

    Args:
        season: NBA season (required, no default).
        min_games: Minimum games played to qualify.

    Returns:
        list[dict]: Each dict has pts, reb, ast, stl, blk, tov.
            Sorted by pts descending.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    if not isinstance(min_games, int) or min_games < 0:
        raise ValueError(f"Invalid min_games {min_games!r}")

    sql = """
        SELECT pts_per_game AS pts, trb_per_game AS reb,
               ast_per_game AS ast, stl_per_game AS stl,
               blk_per_game AS blk, tov_per_game AS tov
        FROM player_per_game
        WHERE season = %s AND g >= %s AND pts_per_game IS NOT NULL
        ORDER BY pts_per_game DESC
    """
    return batch_query(sql, (season, min_games))


def get_player_advanced(season: int, limit: int, sort_by: str) -> list[dict]:
    """Player advanced metrics ranking.

    Args:
        season: NBA season (required, no default).
        limit: Maximum number of players to return (capped at 200).
        sort_by: Column to sort by (whitelist validated).

    Returns:
        list[dict]: Advanced stats for top players.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    if not isinstance(limit, int) or limit < 1:
        raise ValueError(f"Invalid limit {limit!r}")
    limit = min(limit, 200)

    sort_key = sort_by.lower() if sort_by else "per"
    if sort_key not in _ALLOWED_ADVANCED_SORTS:
        sort_key = "per"

    sql = f"""
        WITH ranked AS (
            SELECT p.season, p.player, p.team, p.pos, p.g, p.mp,
                   p.per, p.ts_percent, p.x3p_ar, p.f_tr,
                   p.orb_percent, p.drb_percent, p.trb_percent,
                   p.ast_percent, p.stl_percent, p.blk_percent,
                   p.tov_percent, p.usg_percent,
                   p.ows, p.dws, p.ws, p.ws_48,
                   p.obpm, p.dbpm, p.bpm, p.vorp,
                   ROW_NUMBER() OVER (PARTITION BY p.player ORDER BY p.g DESC) as rn
            FROM player_advanced p
            WHERE p.season = %s AND p.g >= 10
              AND p.team NOT IN ('2TM', '3TM', '4TM', 'TOT')
        )
        SELECT season, player, team, pos, g, mp,
               per, ts_percent, x3p_ar, f_tr,
               orb_percent, drb_percent, trb_percent,
               ast_percent, stl_percent, blk_percent,
               tov_percent, usg_percent,
               ows, dws, ws, ws_48,
               obpm, dbpm, bpm, vorp
        FROM ranked WHERE rn = 1
        ORDER BY {sort_key} DESC NULLS LAST
        LIMIT %s
    """
    return batch_query(sql, (season, limit))


def get_player_shooting(season: int, limit: int) -> list[dict]:
    """Player shooting breakdown by distance zone.

    Args:
        season: NBA season (required, no default).
        limit: Maximum number of players to return (capped at 100).

    Returns:
        list[dict]: Shooting zone distribution data for top players by minutes.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    if not isinstance(limit, int) or limit < 1:
        raise ValueError(f"Invalid limit {limit!r}")
    limit = min(limit, 100)

    sql = """
        WITH ranked AS (
            SELECT s.season, s.player, s.team, s.g, s.mp,
                   s.fg_percent, s.avg_dist_fga,
                   s.percent_fga_from_x0_3_range,
                   s.percent_fga_from_x3_10_range,
                   s.percent_fga_from_x10_16_range,
                   s.percent_fga_from_x16_3p_range,
                   s.percent_fga_from_x3p_range,
                   s.fg_percent_from_x0_3_range,
                   s.fg_percent_from_x3_10_range,
                   s.fg_percent_from_x10_16_range,
                   s.fg_percent_from_x16_3p_range,
                   s.fg_percent_from_x3p_range,
                   s.percent_assisted_x2p_fg,
                   s.percent_assisted_x3p_fg,
                   s.percent_dunks_of_fga,
                   s.num_of_dunks,
                   s.percent_corner_3s_of_3pa,
                   s.corner_3_point_percent,
                   ROW_NUMBER() OVER (PARTITION BY s.player ORDER BY s.g DESC) as rn
            FROM player_shooting s
            WHERE s.season = %s AND s.g >= 10
              AND s.team NOT IN ('2TM', '3TM', '4TM', 'TOT')
        )
        SELECT season, player, team, g, mp,
               fg_percent, avg_dist_fga,
               percent_fga_from_x0_3_range,
               percent_fga_from_x3_10_range,
               percent_fga_from_x10_16_range,
               percent_fga_from_x16_3p_range,
               percent_fga_from_x3p_range,
               fg_percent_from_x0_3_range,
               fg_percent_from_x3_10_range,
               fg_percent_from_x10_16_range,
               fg_percent_from_x16_3p_range,
               fg_percent_from_x3p_range,
               percent_assisted_x2p_fg,
               percent_assisted_x3p_fg,
               percent_dunks_of_fga,
               num_of_dunks,
               percent_corner_3s_of_3pa,
               corner_3_point_percent
        FROM ranked WHERE rn = 1
        ORDER BY mp DESC
        LIMIT %s
    """
    return batch_query(sql, (season, limit))


def get_player_ratios(season: int, min_games: int) -> list[dict]:
    """Player-level AST/TOV ratio and STL/PF ratio.

    Also includes turnover breakdown and other play-by-play derived stats
    when available.

    Args:
        season: NBA season (required, no default).
        min_games: Minimum games played to qualify.

    Returns:
        list[dict]: Player ratio stats sorted by ast_tov_ratio descending.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    if not isinstance(min_games, int) or min_games < 0:
        raise ValueError(f"Invalid min_games {min_games!r}")

    sql = """
        WITH ranked AS (
            SELECT p.player, p.team, p.g,
                   p.ast_per_game, p.tov_per_game,
                   p.stl_per_game, p.pf_per_game,
                   p.pts_per_game, p.mp_per_game,
                   ROW_NUMBER() OVER (PARTITION BY p.player ORDER BY p.g DESC) as rn
            FROM player_per_game p
            WHERE p.season = %s AND p.g >= %s
              AND p.team NOT IN ('2TM', '3TM', '4TM', 'TOT')
        )
        SELECT player, team, g,
               ast_per_game, tov_per_game,
               stl_per_game, pf_per_game,
               pts_per_game, mp_per_game,
               ROUND(CAST(ast_per_game AS numeric) / NULLIF(CAST(tov_per_game AS numeric), 0), 3) AS ast_tov_ratio,
               ROUND(CAST(stl_per_game AS numeric) / NULLIF(CAST(pf_per_game AS numeric), 0), 3) AS stl_pf_ratio
        FROM ranked WHERE rn = 1
        ORDER BY ast_tov_ratio DESC NULLS LAST
    """
    return batch_query(sql, (season, min_games))


def get_player_per_game(season: int, limit: int, sort_by: str) -> list[dict]:
    """Player basic per-game stats ranking.

    Args:
        season: NBA season (required, no default).
        limit: Maximum number of players to return (capped at 200).
        sort_by: Column to sort by (whitelist validated).

    Returns:
        list[dict]: Basic per-game stats for top players.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    if not isinstance(limit, int) or limit < 1:
        raise ValueError(f"Invalid limit {limit!r}")
    limit = min(limit, 200)

    sort_key = sort_by.lower() if sort_by else "pts"
    if sort_key not in _ALLOWED_PER_GAME_SORTS:
        sort_key = "pts"

    sql = f"""
        WITH ranked AS (
            SELECT player AS player_name, team, g, mp_per_game AS mp,
                   pts_per_game AS pts, trb_per_game AS reb, ast_per_game AS ast,
                   stl_per_game AS stl, blk_per_game AS blk, tov_per_game AS tov,
                   fg_percent AS fg_pct, x3p_percent AS fg3_pct, ft_percent AS ft_pct,
                   e_fg_percent AS e_fg_pct,
                   ROW_NUMBER() OVER (PARTITION BY player ORDER BY g DESC) as rn
            FROM player_per_game
            WHERE season = %s AND g >= 10
              AND team NOT IN ('2TM', '3TM', '4TM', 'TOT')
              AND (season_type = 'Regular' OR season_type IS NULL)
        )
        SELECT player_name, team, g, mp, pts, reb, ast, stl, blk, tov,
               fg_pct, fg3_pct, ft_pct, e_fg_pct
        FROM ranked WHERE rn = 1
        ORDER BY {sort_key} DESC NULLS LAST
        LIMIT %s
    """
    return batch_query(sql, (season, limit))
