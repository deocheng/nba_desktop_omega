"""NBACore v8 §2 Layer 1 — Player Growth Loader.

Player career growth/trajectory data for the growth report.
All functions follow v8 §2 rules.
"""
from __future__ import annotations

from backend.core.db import batch_query


def get_player_career_stats(player_id: str) -> list[dict]:
    """Get per-season stats for a player's entire career.

    Uses fact_player_season_stats as the primary source (most complete).
    Excludes TOT/2TM/3TM rows (trade mid-season totals) to avoid double counting.
    Takes the team with most games for each season.

    Args:
        player_id: BBR player ID (e.g. 'jamesle01').

    Returns:
        list[dict]: One row per season, ordered by season ascending.
            Each row has: season, age, team, pos, g, gs, mp,
            pts, trb, ast, stl, blk, tov, pf,
            fg_percent, x3p_percent, ft_percent,
            per, ts_percent, usg_percent, ws, bpm, vorp,
            orb_percent, drb_percent, trb_percent, ast_percent,
            stl_percent, blk_percent, tov_percent
    """
    if not player_id or not isinstance(player_id, str):
        raise ValueError("player_id must be a non-empty string")

    sql = """
        WITH ranked AS (
            SELECT season, age, team, pos, g, gs, mp,
                   pts, trb, ast, stl, blk, tov, pf,
                   orb, drb,
                   fg_percent, x3p_percent, ft_percent,
                   per, ts_percent, usg_percent, ws, bpm, vorp,
                   orb_percent, drb_percent, trb_percent, ast_percent,
                   stl_percent, blk_percent, tov_percent,
                   ROW_NUMBER() OVER (PARTITION BY season ORDER BY g DESC) as rn
            FROM fact_player_season_stats
            WHERE player_id = %s
              AND team NOT IN ('TOT', '2TM', '3TM', '4TM')
        )
        SELECT season, age, team, pos, g, gs, mp,
               pts, trb, ast, stl, blk, tov, pf,
               orb, drb,
               fg_percent, x3p_percent, ft_percent,
               per, ts_percent, usg_percent, ws, bpm, vorp,
               orb_percent, drb_percent, trb_percent, ast_percent,
               stl_percent, blk_percent, tov_percent
        FROM ranked
        WHERE rn = 1
        ORDER BY season ASC
    """
    return batch_query(sql, (player_id,))


def get_player_per_game_career(player_id: str) -> list[dict]:
    """Get per-game stats for a player's entire career.

    Uses player_per_game table. Excludes TOT rows.
    Takes the team with most games for each season.

    Args:
        player_id: BBR player ID.

    Returns:
        list[dict]: One row per season with per-game averages.
    """
    if not player_id or not isinstance(player_id, str):
        raise ValueError("player_id must be a non-empty string")

    sql = """
        WITH ranked AS (
            SELECT season, age, team, pos, g, gs,
                   mp_per_game, pts_per_game, trb_per_game, ast_per_game,
                   stl_per_game, blk_per_game, tov_per_game, pf_per_game,
                   fg_percent, x3p_percent, ft_percent, e_fg_percent,
                   ROW_NUMBER() OVER (PARTITION BY season ORDER BY g DESC) as rn
            FROM player_per_game
            WHERE player_id = %s
              AND team NOT IN ('TOT', '2TM', '3TM', '4TM')
        )
        SELECT season, age, team, pos, g, gs,
               mp_per_game, pts_per_game, trb_per_game, ast_per_game,
               stl_per_game, blk_per_game, tov_per_game, pf_per_game,
               fg_percent, x3p_percent, ft_percent, e_fg_percent
        FROM ranked
        WHERE rn = 1
        ORDER BY season ASC
    """
    return batch_query(sql, (player_id,))


def get_player_career_summary(player_id: str) -> dict:
    """Get a player's bio + career summary for the growth report header.

    Args:
        player_id: BBR player ID.

    Returns:
        dict with bio info and career totals.
    """
    if not player_id or not isinstance(player_id, str):
        raise ValueError("player_id must be a non-empty string")

    sql = """
        SELECT p.player_id, p.player_name, p.full_name, p.position,
               p.height_display, p.height_cm, p.weight_lbs, p.weight_kg,
               p.birth_date, p.birth_city, p.birth_state_country,
               p.college, p.nba_debut, p.year_from, p.year_to, p.experience
        FROM dim_players p
        WHERE p.player_id = %s
    """
    rows = batch_query(sql, (player_id,))
    if not rows:
        return {}
    bio = dict(rows[0])

    # Career totals from fact_player_season_stats
    sql_totals = """
        SELECT COUNT(*) AS seasons,
               SUM(g)::int AS total_games,
               SUM(gs)::int AS total_games_started,
               SUM(mp)::int AS total_minutes,
               SUM(pts)::int AS total_points,
               SUM(trb)::int AS total_rebounds,
               SUM(orb)::int AS total_offensive_rebounds,
               SUM(drb)::int AS total_defensive_rebounds,
               SUM(ast)::int AS total_assists,
               SUM(stl)::int AS total_steals,
               SUM(blk)::int AS total_blocks,
               SUM(tov)::int AS total_turnovers,
               SUM(pf)::int AS total_fouls,
               SUM(ws) AS total_win_shares
        FROM fact_player_season_stats
        WHERE player_id = %s
          AND team NOT IN ('TOT', '2TM', '3TM', '4TM')
    """
    totals_rows = batch_query(sql_totals, (player_id,))
    if totals_rows:
        bio.update(dict(totals_rows[0]))

    return bio


def get_player_position_breakdown(player_id: str) -> list[dict]:
    """Get per-position stats breakdown across a player's career.

    Aggregates stats by the position listed for each season.
    Useful for showing how a player's role evolved.

    Args:
        player_id: BBR player ID.

    Returns:
        list[dict]: One row per position with aggregated stats.
            Sorted by total games descending.
    """
    if not player_id or not isinstance(player_id, str):
        raise ValueError("player_id must be a non-empty string")

    sql = """
        SELECT pos,
               COUNT(*) AS seasons,
               SUM(g)::int AS total_games,
               SUM(gs)::int AS total_games_started,
               SUM(mp)::int AS total_minutes,
               SUM(pts)::int AS total_points,
               SUM(trb)::int AS total_rebounds,
               SUM(ast)::int AS total_assists,
               SUM(stl)::int AS total_steals,
               SUM(blk)::int AS total_blocks,
               ROUND(AVG(pts::numeric / NULLIF(g, 0)), 2) AS ppg,
               ROUND(AVG(trb::numeric / NULLIF(g, 0)), 2) AS rpg,
               ROUND(AVG(ast::numeric / NULLIF(g, 0)), 2) AS apg,
               ROUND(AVG(per::numeric), 2) AS avg_per,
               ROUND(AVG(usg_percent::numeric), 2) AS avg_usg,
               ROUND(SUM(pts::numeric) / NULLIF(SUM(mp::numeric), 0) * 36, 2) AS pts_per_36
        FROM fact_player_season_stats
        WHERE player_id = %s
          AND team NOT IN ('TOT', '2TM', '3TM', '4TM')
          AND pos IS NOT NULL
        GROUP BY pos
        ORDER BY total_games DESC
    """
    return batch_query(sql, (player_id,))


def get_team_season_points(team: str, season: int) -> int | None:
    """Get a team's total points for a season (for usage% / scoring share calculation).

    Used to compute what percentage of a team's scoring a player accounted for.

    Args:
        team: Team abbreviation (e.g. 'LAL').
        season: NBA season (e.g. 2024).

    Returns:
        int: Team total points for the season, or None if not found.
    """
    if not team or not season:
        return None

    sql = """
        SELECT pts
        FROM fact_team_season_stats
        WHERE abbreviation = %s AND season = %s
        LIMIT 1
    """
    rows = batch_query(sql, (team, season))
    if rows and rows[0].get('pts') is not None:
        return int(rows[0]['pts'])
    return None


def get_player_shooting_career(player_id: str) -> list[dict]:
    """Get shooting profile data for a player's entire career.

    Uses player_shooting table to get shot distribution by distance zones.

    Args:
        player_id: BBR player ID.

    Returns:
        list[dict]: One row per season with shooting zone data.
    """
    if not player_id or not isinstance(player_id, str):
        raise ValueError("player_id must be a non-empty string")

    sql = """
        WITH player_name AS (
            SELECT player_name FROM dim_players WHERE player_id = %s
        ),
        ranked AS (
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
                   ROW_NUMBER() OVER (PARTITION BY s.season ORDER BY s.g DESC) as rn
            FROM player_shooting s
            WHERE s.player = (SELECT player_name FROM player_name)
              AND s.team NOT IN ('TOT', '2TM', '3TM', '4TM')
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
               percent_assisted_x3p_fg
        FROM ranked
        WHERE rn = 1
        ORDER BY season ASC
    """
    return batch_query(sql, (player_id,))
