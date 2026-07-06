"""NBACore v8 §2 Layer 1 — Team Loader.

Team-related data queries for the v8 data layer.
All functions follow v8 §2 rules:
    - season parameter is REQUIRED (no default) where applicable
    - Only SELECT statements
    - All SQL passes through backend.core.db.batch_query
    - Returns list[dict]
"""
from __future__ import annotations

from backend.core.db import batch_query

_NBA_TO_BR_ABBR = {
    'BKN': 'BRK',
    'PHX': 'PHO',
    'CHA': 'CHO',
    'UTAH': 'UTA',
    'WAS': 'WAS',
}


def _to_br_abbr(team_abbr: str) -> str:
    """Convert NBA standard abbreviation to Basketball Reference style."""
    abbr = team_abbr.upper()
    return _NBA_TO_BR_ABBR.get(abbr, abbr)


def list_all_teams(active_only: bool = True) -> list[dict]:
    """List all teams with abbreviation, name, and active status.

    Args:
        active_only: If True, only return currently active teams (30 NBA teams).
            If False, return all teams including historical/relocated teams.

    Returns:
        list[dict]: Each dict has team_abbr, team_name, is_active.
    """
    where = "WHERE is_active = TRUE" if active_only else ""
    sql = f"""
        SELECT team_code AS team_abbr, team_name, is_active
        FROM team_mapping
        {where}
        ORDER BY team_code
    """
    return batch_query(sql)


def get_team_splits(team_abbr: str, season: int) -> list[dict]:
    """Get team game splits for a specific team and season.

    Args:
        team_abbr: Team abbreviation (e.g. 'BOS').
        season: NBA season (required, no default).

    Returns:
        list[dict]: Team split rows.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    if not team_abbr or not isinstance(team_abbr, str):
        raise ValueError("team_abbr must be a non-empty string")

    sql = """
        SELECT * FROM team_game_splits
        WHERE team_abbr = %s AND season = %s
        ORDER BY split_type
    """
    return batch_query(sql, (team_abbr.upper(), season))


_EASTERN_CONF = {
    'BOS', 'BKN', 'BRK', 'NYK', 'PHI', 'TOR',
    'CHI', 'CLE', 'DET', 'IND', 'MIL',
    'ATL', 'CHA', 'CHO', 'MIA', 'ORL', 'WAS',
}

_WESTERN_CONF = {
    'DEN', 'MIN', 'OKC', 'POR', 'UTA',
    'GSW', 'LAC', 'LAL', 'PHX', 'PHO', 'SAC',
    'DAL', 'HOU', 'MEM', 'NOP', 'NOH', 'SAS',
}


def _get_conference(abbr: str) -> str:
    if abbr in _EASTERN_CONF:
        return 'East'
    if abbr in _WESTERN_CONF:
        return 'West'
    return ''


def get_team_standings(season: int) -> list[dict]:
    """Get team standings (W/L records and advanced metrics) from team_summaries.

    Note: Playoff teams store their regular-season data with playoffs=True,
    so we include all rows and dedupe by team (keep most games).

    Args:
        season: NBA season (required, no default).

    Returns:
        list[dict]: Team standings sorted by wins descending.
            Each dict has team_abbr, w, l, win_pct, rank, conference,
            pw, pl, mov, srs, o_rtg, d_rtg, n_rtg, pace,
            ts_percent, e_fg_percent, tov_percent, orb_percent.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")

    sql = """
        SELECT DISTINCT ON (abbreviation)
               abbreviation AS team_abbr, w, l, pw, pl,
               mov, srs, o_rtg, d_rtg, n_rtg, pace,
               ts_percent, e_fg_percent, tov_percent, orb_percent
        FROM team_summaries
        WHERE season = %s
        ORDER BY abbreviation, w DESC
    """
    rows = batch_query(sql, (season,))
    rows.sort(key=lambda r: r.get('w', 0), reverse=True)

    result = []
    east_count = 0
    west_count = 0
    for r in rows:
        row = dict(r)
        w = row.get('w', 0) or 0
        l = row.get('l', 0) or 0
        total = w + l
        row['win_pct'] = round(w / total, 4) if total > 0 else 0.0
        conf = _get_conference(row['team_abbr'])
        row['conference'] = conf
        if conf == 'East':
            east_count += 1
            row['rank'] = east_count
        elif conf == 'West':
            west_count += 1
            row['rank'] = west_count
        else:
            row['rank'] = len(result) + 1
        result.append(row)
    return result


def get_team_stats_per_game(season: int) -> list[dict]:
    """Get team per-game stats from team_stats_per_game.

    Note: Playoff teams store their regular-season data with playoffs=True
    (g=82 indicates regular season), so we include all rows and dedupe by team.

    Args:
        season: NBA season (required, no default).

    Returns:
        list[dict]: Team per-game stats (regular season),
            sorted by points per game descending.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")

    sql = """
        SELECT DISTINCT ON (abbreviation)
               abbreviation AS team_abbr,
               pts_per_game AS off_pts,
               opp_pts_per_game AS def_pts,
               g, fg_percent, x3p_percent, ft_percent,
               trb_per_game, ast_per_game, stl_per_game, blk_per_game,
               tov_per_game, pf_per_game, fta_per_game
        FROM team_stats_per_game
        WHERE season = %s
        ORDER BY abbreviation, g DESC
    """
    rows = batch_query(sql, (season,))
    rows.sort(key=lambda r: r.get('off_pts', 0), reverse=True)
    return rows


def get_team_ratios(season: int) -> list[dict]:
    """Get team-level AST/TOV ratio and STL/PF ratio.

    Also includes offensive/defensive ratings and pace.

    Args:
        season: NBA season (required, no default).

    Returns:
        list[dict]: Team ratio stats sorted by ast_tov_ratio descending.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")

    sql = """
        SELECT t.abbreviation AS team_abbr,
               t.ast_per_game, t.tov_per_game, t.stl_per_game, t.pf_per_game,
               t.pts_per_game, t.opp_pts_per_game, t.g,
               ROUND((CAST(t.ast_per_game AS numeric) / NULLIF(CAST(t.tov_per_game AS numeric), 0))::numeric, 3) AS ast_tov_ratio,
               ROUND((CAST(t.stl_per_game AS numeric) / NULLIF(CAST(t.pf_per_game AS numeric), 0))::numeric, 3) AS stl_pf_ratio
        FROM team_stats_per_game t
        WHERE t.season = %s AND t.playoffs IS NOT TRUE
        ORDER BY ast_tov_ratio DESC NULLS LAST
    """
    return batch_query(sql, (season,))


def get_team_scoring_trend(team_abbr: str) -> list[dict]:
    """Get team scoring trend across multiple seasons.

    Args:
        team_abbr: Team abbreviation (e.g. 'BOS').

    Returns:
        list[dict]: Season-by-season scoring stats sorted by season ascending.
            Each dict has season, pts, plus_minus, games, reb, ast, stl, blk.
    """
    if not team_abbr or not isinstance(team_abbr, str):
        raise ValueError("team_abbr must be a non-empty string")

    sql = """
        SELECT season, pts, plus_minus, games, reb, ast, stl, blk
        FROM team_game_splits
        WHERE team_abbr = %s AND split_type = 'total'
        ORDER BY season
    """
    return batch_query(sql, (team_abbr.upper(),))


def get_team_radar(team_abbr: str, season: int) -> dict:
    """Get radar chart data for a single team in a season.

    Uses team_stats_per_game JOIN team_summaries for full radar metrics.
    Falls back to team_game_splits if needed.

    Args:
        team_abbr: Team abbreviation (e.g. 'BOS').
        season: NBA season (required, no default).

    Returns:
        dict: Radar chart stats including pts, reb, ast, stl, blk,
            fg_pct, fg3_pct, ft_pct, pace, x3p_ar, fta.
            Returns empty dict if no data found.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    if not team_abbr or not isinstance(team_abbr, str):
        raise ValueError("team_abbr must be a non-empty string")

    abbr_upper = team_abbr.upper()
    br_abbr = _to_br_abbr(abbr_upper)

    sql_regular = """
        SELECT s.pts_per_game AS pts,
               s.trb_per_game AS reb,
               s.ast_per_game AS ast,
               s.stl_per_game AS stl,
               s.blk_per_game AS blk,
               s.fg_percent AS fg_pct,
               s.x3p_percent AS fg3_pct,
               s.ft_percent AS ft_pct,
               s.fta_per_game AS fta,
               s.tov_per_game AS tov,
               s.pf_per_game AS pf,
               m.pace AS pace,
               m.x3p_ar AS x3p_ar
        FROM team_stats_per_game s
        LEFT JOIN team_summaries m
            ON s.abbreviation = m.abbreviation
           AND s.season = m.season
           AND s.playoffs = m.playoffs
        WHERE s.abbreviation = %s AND s.season = %s AND s.playoffs IS NOT TRUE
        LIMIT 1
    """
    rows = batch_query(sql_regular, (br_abbr, season))
    if rows:
        return dict(rows[0])

    sql_playoffs = """
        SELECT s.pts_per_game AS pts,
               s.trb_per_game AS reb,
               s.ast_per_game AS ast,
               s.stl_per_game AS stl,
               s.blk_per_game AS blk,
               s.fg_percent AS fg_pct,
               s.x3p_percent AS fg3_pct,
               s.ft_percent AS ft_pct,
               s.fta_per_game AS fta,
               s.tov_per_game AS tov,
               s.pf_per_game AS pf,
               m.pace AS pace,
               m.x3p_ar AS x3p_ar
        FROM team_stats_per_game s
        LEFT JOIN team_summaries m
            ON s.abbreviation = m.abbreviation
           AND s.season = m.season
           AND s.playoffs = m.playoffs
        WHERE s.abbreviation = %s AND s.season = %s
        LIMIT 1
    """
    rows = batch_query(sql_playoffs, (br_abbr, season))
    if rows:
        return dict(rows[0])

    sql2 = """
        SELECT pts, reb, ast, stl, blk, fg_pct, fg3_pct, ft_pct
        FROM team_game_splits
        WHERE team_abbr = %s AND season = %s AND split_type = 'total'
    """
    rows2 = batch_query(sql2, (abbr_upper, season))
    return dict(rows2[0]) if rows2 else {}


def get_league_radar_avg(season: int) -> dict:
    """Get league average radar stats for a season.

    Uses team_stats_per_game JOIN team_summaries for full metrics.

    Args:
        season: NBA season (required, no default).

    Returns:
        dict: League average stats including pts, reb, ast, stl, blk,
            fg_pct, fg3_pct, ft_pct, pace, x3p_ar, fta.
            Returns empty dict if no data.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")

    sql = """
        SELECT ROUND(AVG(s.pts_per_game)::numeric, 2) AS pts,
               ROUND(AVG(s.trb_per_game)::numeric, 2) AS reb,
               ROUND(AVG(s.ast_per_game)::numeric, 2) AS ast,
               ROUND(AVG(s.stl_per_game)::numeric, 2) AS stl,
               ROUND(AVG(s.blk_per_game)::numeric, 2) AS blk,
               ROUND(AVG(s.fg_percent)::numeric, 4) AS fg_pct,
               ROUND(AVG(s.x3p_percent)::numeric, 4) AS fg3_pct,
               ROUND(AVG(s.ft_percent)::numeric, 4) AS ft_pct,
               ROUND(AVG(s.fta_per_game)::numeric, 2) AS fta,
               ROUND(AVG(s.tov_per_game)::numeric, 2) AS tov,
               ROUND(AVG(s.pf_per_game)::numeric, 2) AS pf,
               ROUND(AVG(m.pace)::numeric, 2) AS pace,
               ROUND(AVG(m.x3p_ar)::numeric, 4) AS x3p_ar
        FROM team_stats_per_game s
        LEFT JOIN team_summaries m
            ON s.abbreviation = m.abbreviation
           AND s.season = m.season
           AND s.playoffs = m.playoffs
        WHERE s.season = %s AND s.playoffs IS NOT TRUE
    """
    rows = batch_query(sql, (season,))
    if rows and rows[0]['pts'] is not None:
        return dict(rows[0])

    sql2 = """
        SELECT ROUND(AVG(s.pts_per_game)::numeric, 2) AS pts,
               ROUND(AVG(s.trb_per_game)::numeric, 2) AS reb,
               ROUND(AVG(s.ast_per_game)::numeric, 2) AS ast,
               ROUND(AVG(s.stl_per_game)::numeric, 2) AS stl,
               ROUND(AVG(s.blk_per_game)::numeric, 2) AS blk,
               ROUND(AVG(s.fg_percent)::numeric, 4) AS fg_pct,
               ROUND(AVG(s.x3p_percent)::numeric, 4) AS fg3_pct,
               ROUND(AVG(s.ft_percent)::numeric, 4) AS ft_pct,
               ROUND(AVG(s.fta_per_game)::numeric, 2) AS fta,
               ROUND(AVG(s.tov_per_game)::numeric, 2) AS tov,
               ROUND(AVG(s.pf_per_game)::numeric, 2) AS pf,
               ROUND(AVG(m.pace)::numeric, 2) AS pace,
               ROUND(AVG(m.x3p_ar)::numeric, 4) AS x3p_ar
        FROM team_stats_per_game s
        LEFT JOIN team_summaries m
            ON s.abbreviation = m.abbreviation
           AND s.season = m.season
           AND s.playoffs = m.playoffs
        WHERE s.season = %s
    """
    rows2 = batch_query(sql2, (season,))
    return dict(rows2[0]) if rows2 and rows2[0]['pts'] is not None else {}
