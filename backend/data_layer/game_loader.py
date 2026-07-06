"""NBACore v8 §2 Layer 1 — Game Loader.

Game-related data queries for the v8 data layer.
All functions follow v8 §2 rules:
    - season parameter is REQUIRED (no default) where applicable
    - Only SELECT statements
    - All SQL passes through backend.core.db.batch_query
    - Returns list[dict]
"""
from __future__ import annotations

from backend.core.db import batch_query


def list_games(
    season: int | None,
    page: int,
    per_page: int,
) -> tuple[list[dict], int]:
    """Paginated list of games.

    Args:
        season: NBA season filter. If None, returns all seasons.
        page: Page number (1-based).
        per_page: Items per page (capped at 200).

    Returns:
        tuple[list[dict], int]: (games_list, total_count).
    """
    if page < 1:
        raise ValueError("page must be >= 1")
    if per_page < 1:
        raise ValueError("per_page must be >= 1")
    per_page = min(per_page, 200)
    if season is not None and (not isinstance(season, int) or season < 1900 or season > 2100):
        raise ValueError(f"Invalid season {season!r}")

    offset = (page - 1) * per_page

    where = "WHERE 1=1"
    params: list = []
    if season is not None:
        where += " AND season = %s"
        params.append(season)

    total_sql = f"SELECT count(*) AS cnt FROM games {where}"
    total_rows = batch_query(total_sql, tuple(params))
    total = total_rows[0]["cnt"] if total_rows else 0

    data_sql = f"""
        SELECT game_id, game_date, season, away_team_abbr, home_team_abbr,
               away_pts, home_pts, season_type, game_status
        FROM games {where}
        ORDER BY game_date DESC NULLS LAST
        LIMIT %s OFFSET %s
    """
    rows = batch_query(data_sql, tuple(params + [per_page, offset]))
    return rows, total


def get_quarter_stats(
    team_abbr: str,
    season: int,
    limit: int,
) -> list[dict]:
    """Quarter-by-quarter scoring for a team's recent games.

    Args:
        team_abbr: Team abbreviation (e.g. 'BOS').
        season: NBA season (required, no default).
        limit: Maximum number of recent games to return (capped at 50).

    Returns:
        list[dict]: Quarter stats for each game, sorted by game_date descending.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    if not team_abbr or not isinstance(team_abbr, str):
        raise ValueError("team_abbr must be a non-empty string")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    limit = min(limit, 50)

    sql = """
        SELECT game_date,
               home_team_abbr, away_team_abbr,
               home_pts, away_pts,
               home_q1, home_q2, home_q3, home_q4, home_ot,
               away_q1, away_q2, away_q3, away_q4, away_ot
        FROM games
        WHERE (home_team_abbr = %s OR away_team_abbr = %s)
          AND home_q1 IS NOT NULL
          AND season = %s
        ORDER BY game_date DESC
        LIMIT %s
    """
    return batch_query(sql, (team_abbr.upper(), team_abbr.upper(), season, limit))


def get_game_detail(game_id: str) -> dict:
    """Get full game detail including both teams' stats.

    Args:
        game_id: Game ID (BR numeric format, e.g. '22401189').

    Returns:
        dict: Game info with home/away stats and quarter scores.
            Returns empty dict if game not found.
    """
    if not game_id or not isinstance(game_id, str):
        raise ValueError("game_id must be a non-empty string")

    sql = """
        SELECT game_id, game_date, season, season_type, game_status,
               home_team_abbr, away_team_abbr, home_pts, away_pts,
               home_fg_pct, away_fg_pct, home_fg3_pct, away_fg3_pct, home_ft_pct, away_ft_pct,
               home_fgm, away_fgm, home_fga, away_fga,
               home_fg3m, away_fg3m, home_fga3, away_fga3,
               home_ftm, away_ftm, home_fta, away_fta,
               home_reb, away_reb, home_oreb, away_oreb, home_dreb, away_dreb,
               home_ast, away_ast, home_stl, away_stl, home_blk, away_blk,
               home_tov, away_tov, home_pf, away_pf,
               home_q1, home_q2, home_q3, home_q4, home_ot,
               away_q1, away_q2, away_q3, away_q4, away_ot,
               pbp_saved
        FROM games
        WHERE game_id = %s
        LIMIT 1
    """
    rows = batch_query(sql, (str(game_id),))
    return dict(rows[0]) if rows else {}


def _aggregate_team_stats_from_gamelog(game_id: str) -> dict[str, dict]:
    """Aggregate team-level stats from player_gamelog.

    This is the PRIMARY source for team game stats since games table
    often has NULL or incorrect advanced stats.
    player_gamelog has accurate per-player stats including AST, STL, BLK.

    Uses DISTINCT ON to pick the most recent record per player
    (by created_at) to avoid duplicates from multiple data imports.

    Args:
        game_id: Game ID (BR numeric format, e.g. '22401189').

    Returns:
        dict keyed by team_abbr with stat dict.
    """
    sql = """
        WITH player_rows AS (
            SELECT DISTINCT ON (br_player_id)
                   br_player_id,
                   COALESCE(team_abbreviation, team) AS team,
                   pts, ast,
                   COALESCE(reb, trb) AS reb,
                   COALESCE(oreb, orb) AS oreb,
                   COALESCE(dreb, drb) AS dreb,
                   stl, blk, tov, pf,
                   COALESCE(fgm, fg) AS fgm,
                   COALESCE(fga, fga) AS fga,
                   COALESCE(tpm, fg3) AS fg3m,
                   COALESCE(tpa, fga3) AS fg3a,
                   COALESCE(ftm, ft) AS ftm,
                   fta
            FROM player_gamelog
            WHERE gameid = %s
              AND br_player_id IS NOT NULL
            ORDER BY br_player_id, created_at DESC
        )
        SELECT team,
               SUM(pts)::int AS pts,
               SUM(ast)::int AS ast,
               SUM(reb)::int AS reb,
               SUM(oreb)::int AS oreb,
               SUM(dreb)::int AS dreb,
               SUM(stl)::int AS stl,
               SUM(blk)::int AS blk,
               SUM(tov)::int AS tov,
               SUM(pf)::int AS pf,
               SUM(fgm)::int AS fgm,
               SUM(fga)::int AS fga,
               SUM(fg3m)::int AS fg3m,
               SUM(fg3a)::int AS fg3a,
               SUM(ftm)::int AS ftm,
               SUM(fta)::int AS fta
        FROM player_rows
        GROUP BY team
    """
    rows = batch_query(sql, (str(game_id),))
    result = {}
    for r in rows:
        team = r.get('team') or ''
        d = dict(r)
        d.pop('team', None)
        d['fg_pct'] = round(d['fgm'] / d['fga'], 4) if d['fga'] else 0.0
        d['fg3_pct'] = round(d['fg3m'] / d['fg3a'], 4) if d['fg3a'] else 0.0
        d['ft_pct'] = round(d['ftm'] / d['fta'], 4) if d['fta'] else 0.0
        result[team] = d
    return result


def get_game_radar(game_id: str) -> dict:
    """Get radar chart data for both teams in a single game.

    Returns per-game stats for both home and away teams.
    Primary source is player_gamelog aggregation (accurate AST/STL/BLK/3PT).
    Falls back to games table and pbp aggregation if gamelog unavailable.

    Args:
        game_id: Game ID (BR numeric format).

    Returns:
        dict: {home_team, away_team, home: {pts, reb, ast, ...}, away: {...}}
            Returns empty dict if game not found.
    """
    detail = get_game_detail(game_id)
    if not detail:
        return {}

    home_team = detail.get('home_team_abbr')
    away_team = detail.get('away_team_abbr')

    def _team_stats_from_games(prefix: str) -> dict:
        return {
            'pts': detail.get(f'{prefix}_pts'),
            'reb': detail.get(f'{prefix}_reb'),
            'ast': detail.get(f'{prefix}_ast'),
            'stl': detail.get(f'{prefix}_stl'),
            'blk': detail.get(f'{prefix}_blk'),
            'fg_pct': detail.get(f'{prefix}_fg_pct'),
            'fg3_pct': detail.get(f'{prefix}_fg3_pct'),
            'ft_pct': detail.get(f'{prefix}_ft_pct'),
            'tov': detail.get(f'{prefix}_tov'),
            'pf': detail.get(f'{prefix}_pf'),
            'oreb': detail.get(f'{prefix}_oreb'),
            'dreb': detail.get(f'{prefix}_dreb'),
            'fgm': detail.get(f'{prefix}_fgm'),
            'fga': detail.get(f'{prefix}_fga'),
            'fg3m': detail.get(f'{prefix}_fg3m'),
            'fg3a': detail.get(f'{prefix}_fga3'),
            'ftm': detail.get(f'{prefix}_ftm'),
            'fta': detail.get(f'{prefix}_fta'),
        }

    home_stats = _team_stats_from_games('home')
    away_stats = _team_stats_from_games('away')

    # Primary: player_gamelog aggregation has accurate AST/STL/BLK/3PT
    gamelog_stats = _aggregate_team_stats_from_gamelog(game_id)
    if gamelog_stats:
        for stats, team_abbr in [(home_stats, home_team), (away_stats, away_team)]:
            agg = gamelog_stats.get(team_abbr or '', {})
            if agg:
                for k, v in agg.items():
                    if v is not None:
                        stats[k] = v

    # Fallback: if gamelog unavailable and games table is missing stats,
    # use pbp aggregation
    stats_missing = (
        home_stats['reb'] is None or home_stats['ast'] is None or
        home_stats['tov'] is None or home_stats['pf'] is None or
        away_stats['reb'] is None or away_stats['ast'] is None or
        away_stats['tov'] is None or away_stats['pf'] is None
    )

    if stats_missing and not gamelog_stats:
        pbp_stats = _aggregate_team_stats_from_pbp(game_id, home_team, away_team)
        pbp_fields = {
            'reb', 'ast', 'stl', 'blk', 'tov', 'pf',
            'oreb', 'dreb', 'fg3m', 'fg3a', 'ftm', 'fta',
            'fg3_pct', 'ft_pct',
        }
        for stats, team_abbr in [(home_stats, home_team), (away_stats, away_team)]:
            agg = pbp_stats.get(team_abbr or '', {})
            for k in pbp_fields:
                if k in agg and stats.get(k) is None:
                    stats[k] = agg[k]

    return {
        'home_team': home_team,
        'away_team': away_team,
        'home': home_stats,
        'away': away_stats,
    }


def _aggregate_team_stats_from_pbp(
    game_id: str, home_team: str | None, away_team: str | None
) -> dict[str, dict]:
    """Aggregate team-level stats from play_by_play events.

    Used as a fallback when games table stats are NULL.
    Returns dict keyed by team_abbr with stat dict.
    """
    events = get_play_by_play(game_id)
    teams = {home_team or '': _empty_team_stats(), away_team or '': _empty_team_stats()}

    for ev in events:
        team = ev.get('team') or ''
        if team not in teams:
            continue
        etype = (ev.get('event_type') or '').strip()
        player = ev.get('player') or ''
        desc = (ev.get('description') or ev.get('homedescription') or
                ev.get('visitordescription') or '')
        desc_lower = desc.lower()
        s = teams[team]

        if etype == 'Made Shot':
            is_3pt = '3-pt' in desc_lower or '3pt' in desc_lower
            s['fgm'] += 1
            s['fga'] += 1
            if is_3pt:
                s['fg3m'] += 1
                s['fg3a'] += 1
                s['pts'] += 3
            else:
                s['pts'] += 2
        elif etype == 'Missed Shot':
            is_3pt = '3-pt' in desc_lower or '3pt' in desc_lower
            s['fga'] += 1
            if is_3pt:
                s['fg3a'] += 1
        elif etype == 'Free Throw':
            s['fta'] += 1
            if 'makes' in desc_lower or 'make' in desc_lower:
                s['ftm'] += 1
                s['pts'] += 1
        elif etype == 'Rebound':
            s['reb'] += 1
            if 'offensive' in desc_lower:
                s['oreb'] += 1
            else:
                s['dreb'] += 1
        elif etype == 'Turnover':
            s['tov'] += 1
        elif etype == 'Foul':
            s['pf'] += 1
        elif etype == '' and 'steal by' in desc_lower:
            s['stl'] += 1
        elif etype == '' and 'block by' in desc_lower:
            s['blk'] += 1

    # Compute percentages
    for s in teams.values():
        s['fg_pct'] = round(s['fgm'] / s['fga'], 4) if s['fga'] else 0.0
        s['fg3_pct'] = round(s['fg3m'] / s['fg3a'], 4) if s['fg3a'] else 0.0
        s['ft_pct'] = round(s['ftm'] / s['fta'], 4) if s['fta'] else 0.0

    return teams


def _empty_team_stats() -> dict:
    return {
        'pts': 0, 'reb': 0, 'ast': 0, 'stl': 0, 'blk': 0,
        'fg_pct': 0.0, 'fg3_pct': 0.0, 'ft_pct': 0.0,
        'tov': 0, 'pf': 0, 'oreb': 0, 'dreb': 0,
        'fgm': 0, 'fga': 0, 'fg3m': 0, 'fg3a': 0,
        'ftm': 0, 'fta': 0,
    }


def get_play_by_play(game_id: str) -> list[dict]:
    """Get all play-by-play events for a game.

    Args:
        game_id: Game ID (BR numeric format, e.g. '22401189').

    Returns:
        list[dict]: All events ordered by eventnum. Each dict has:
            period, clock, clock_seconds, event_type, team, player,
            description, scorehome, scorevisitor, scoremargin,
            player1_name, player1_team_abbreviation,
            player2_name, player2_team_abbreviation.
    """
    if not game_id or not isinstance(game_id, str):
        raise ValueError("game_id must be a non-empty string")

    sql = """
        SELECT eventnum, period, clock, clock_seconds,
               event_type, team, player, br_player_id,
               description, homedescription, visitordescription,
               scorehome, scorevisitor, scoremargin,
               player1_name, player1_team_abbreviation,
               player2_name, player2_team_abbreviation,
               player3_name
        FROM play_by_play
        WHERE gameid = %s
        ORDER BY eventnum
    """
    return batch_query(sql, (str(game_id),))


def _get_gamelog_players(game_id: str) -> dict[str, dict]:
    """Get player base stats from player_gamelog for a game.

    Returns dict keyed by br_player_id with full player stats.
    player_gamelog is the authoritative source for PTS/AST/REB etc.
    Uses the most recent record per player (by created_at) to avoid
    duplicates from multiple data imports.
    """
    sql = """
        SELECT DISTINCT ON (br_player_id)
               br_player_id,
               COALESCE(player_name, player) AS player_name,
               COALESCE(team_abbreviation, team) AS team,
               start_position, minutes, seconds_played,
               pts, ast,
               COALESCE(reb, trb) AS reb,
               COALESCE(oreb, orb) AS oreb,
               COALESCE(dreb, drb) AS dreb,
               stl, blk, tov, pf,
               COALESCE(fgm, fg) AS fgm,
               COALESCE(fga, fga) AS fga,
               COALESCE(tpm, fg3) AS fg3m,
               COALESCE(tpa, fga3) AS fg3a,
               COALESCE(ftm, ft) AS ftm,
               fta,
               fg_pct, fg3_pct, ft_pct, plus_minus,
               fbpts, pip, tech_fouls
        FROM player_gamelog
        WHERE gameid = %s
          AND br_player_id IS NOT NULL
        ORDER BY br_player_id, created_at DESC
    """
    rows = batch_query(sql, (str(game_id),))
    result = {}
    for r in rows:
        pid = r.get('br_player_id') or ''
        if pid:
            result[pid] = dict(r)
    return result


def get_game_player_performance(game_id: str) -> list[dict]:
    """Aggregate player performance by period from play-by-play data.

    Walks through every pbp event and groups stats per player per period:
    - Made Shot / Missed Shot → FGM/FGA, 3PM/3PA (if 3-pt), points
    - Free Throw → FTM/FTA, points (made only)
    - Rebound → REB (offensive/defensive)
    - Turnover → TOV
    - Foul → PF
    - Substitution → track time_in / time_out per period
    - Steal (description contains "Steal by") → STL
    - Block (description contains "Block") → BLK
    - Assist (description contains "Assist") → AST

    Args:
        game_id: Game ID (BR numeric format).

    Returns:
        list[dict]: One row per (player, team, period) with aggregated stats:
            player, team, period, time_in, time_out,
            pts, fgm, fga, fg3m, fg3a, ftm, fta,
            oreb, dreb, reb, ast, stl, blk, tov, pf, fouls_detail, tov_detail
    """
    events = get_play_by_play(game_id)
    if not events:
        return []

    # First, identify starting lineups (players on court at start of each period).
    # The first Substitution event in each period indicates the OUT player
    # (i.e., a starter being substituted out).
    # We track each player's time_in/time_out per period via Substitution events.
    #
    # Note: For BR-parsed pbp data, player1_name and player2_name are usually NULL,
    # so we parse the description field: "SUB: <IN> FOR <OUT>".
    # The `player` field of Substitution events holds the OUT player.

    # Aggregate stats per (player, team, period)
    # Key: (player_name, team_abbr, period)
    perf: dict[tuple, dict] = {}

    def _get_or_create(player: str, team: str, period: int) -> dict:
        if not player:
            return None
        key = (player, team or '', period)
        if key not in perf:
            perf[key] = {
                'player': player,
                'team': team or '',
                'period': period,
                'time_in': None,
                'time_out': None,
                'pts': 0,
                'fgm': 0, 'fga': 0,
                'fg3m': 0, 'fg3a': 0,
                'ftm': 0, 'fta': 0,
                'oreb': 0, 'dreb': 0, 'reb': 0,
                'ast': 0, 'stl': 0, 'blk': 0,
                'tov': 0, 'pf': 0,
                'foul_details': [],
                'tov_details': [],
                'made_shots': [],
                'missed_shots': [],
                'ft_details': [],
            }
        return perf[key]

    # Build br_player_id mapping from pbp events
    br_id_map: dict[tuple, str] = {}  # (player, team) -> br_player_id

    for ev in events:
        etype = (ev.get('event_type') or '').strip()
        period = ev.get('period')
        team = ev.get('team') or ''
        player = ev.get('player') or ''
        br_id = ev.get('br_player_id') or ''
        clock = ev.get('clock') or ''
        desc = ev.get('description') or ev.get('homedescription') or ev.get('visitordescription') or ''
        desc_lower = desc.lower()

        # Track br_player_id for each (player, team)
        if player and team and br_id and (player, team) not in br_id_map:
            br_id_map[(player, team)] = br_id

        if period is None or not player:
            if 'steal by' in desc_lower and player:
                p = _get_or_create(player, team, period if period else 1)
                if p:
                    p['stl'] += 1
            if 'block by' in desc_lower and player:
                p = _get_or_create(player, team, period if period else 1)
                if p:
                    p['blk'] += 1
            continue

        # Skip non-statistical events
        if etype in ('period', 'Jump Ball', 'Timeout', 'End of Game', ''):
            if 'steal by' in desc_lower:
                p = _get_or_create(player, team, period)
                if p:
                    p['stl'] += 1
            if 'block by' in desc_lower:
                p = _get_or_create(player, team, period)
                if p:
                    p['blk'] += 1
            continue

        # Substitution: track time
        if etype == 'Substitution':
            # player = OUT player; description = "SUB: <IN> FOR <OUT>"
            # Mark OUT time for `player`
            out_p = _get_or_create(player, team, period)
            if out_p and out_p['time_out'] is None:
                out_p['time_out'] = clock
            # Parse IN player from description
            in_player = _parse_sub_in(desc)
            if in_player:
                in_p = _get_or_create(in_player, team, period)
                if in_p and in_p['time_in'] is None:
                    in_p['time_in'] = clock
            continue

        # Made Shot
        if etype == 'Made Shot':
            p = _get_or_create(player, team, period)
            if not p:
                continue
            is_3pt = '3-pt' in desc_lower or '3pt' in desc_lower
            if is_3pt:
                p['fg3m'] += 1
                p['fg3a'] += 1
                p['pts'] += 3
            else:
                p['pts'] += 2
            p['fgm'] += 1
            p['fga'] += 1
            p['made_shots'].append({
                'clock': clock,
                'desc': desc,
                'pts': 3 if is_3pt else 2,
            })
            # Look for assist in next event or same event description
            if 'assist' in desc_lower:
                # Try to extract assister from description
                assister = _parse_assist_player(desc)
                if assister:
                    a = _get_or_create(assister, team, period)
                    if a:
                        a['ast'] += 1
            continue

        # Missed Shot
        if etype == 'Missed Shot':
            p = _get_or_create(player, team, period)
            if not p:
                continue
            is_3pt = '3-pt' in desc_lower or '3pt' in desc_lower
            if is_3pt:
                p['fg3a'] += 1
            p['fga'] += 1
            p['missed_shots'].append({
                'clock': clock,
                'desc': desc,
            })
            continue

        # Free Throw
        if etype == 'Free Throw':
            p = _get_or_create(player, team, period)
            if not p:
                continue
            p['fta'] += 1
            if 'makes' in desc_lower or 'make' in desc_lower:
                p['ftm'] += 1
                p['pts'] += 1
            p['ft_details'].append({
                'clock': clock,
                'desc': desc,
                'made': 'makes' in desc_lower or 'make' in desc_lower,
            })
            continue

        # Rebound
        if etype == 'Rebound':
            p = _get_or_create(player, team, period)
            if not p:
                continue
            p['reb'] += 1
            if 'offensive' in desc_lower:
                p['oreb'] += 1
            else:
                p['dreb'] += 1
            continue

        # Turnover
        if etype == 'Turnover':
            p = _get_or_create(player, team, period)
            if not p:
                continue
            p['tov'] += 1
            p['tov_details'].append({
                'clock': clock,
                'desc': desc,
            })
            continue

        # Foul
        if etype == 'Foul':
            p = _get_or_create(player, team, period)
            if not p:
                continue
            p['pf'] += 1
            p['foul_details'].append({
                'clock': clock,
                'desc': desc,
            })
            continue

    # Sort by team, player, period
    result = list(perf.values())
    result.sort(key=lambda r: (r['team'], r['player'], r['period']))

    # Merge accurate base stats from player_gamelog (authoritative source)
    # pbp is good for timeline + event details; gamelog has accurate AST/STL/BLK
    gamelog = _get_gamelog_players(game_id)
    if gamelog:
        # Build last-name -> list of br_player_ids mapping for fallback matching
        # pbp may use different br_ids than the best gamelog data source
        last_name_map: dict[str, list[str]] = {}

        def _extract_last_name(full_name: str) -> str:
            """Extract last name from a full player name.

            Handles suffixes like Jr., Sr., III, etc.
            """
            if not full_name:
                return ''
            parts = full_name.strip().split()
            if len(parts) <= 1:
                return parts[0].lower() if parts else ''
            # Check if last part is a suffix (Jr., Sr., II, III, etc.)
            suffixes = {'jr', 'sr', 'jr.', 'sr.', 'ii', 'iii', 'iv', 'v'}
            last_idx = len(parts) - 1
            if parts[last_idx].lower().strip('.') in suffixes:
                last_idx -= 1
            if last_idx >= 0:
                return parts[last_idx].lower()
            return parts[-1].lower()

        for br_id, gl in gamelog.items():
            name = gl.get('player_name') or ''
            last = _extract_last_name(name)
            if last:
                if last not in last_name_map:
                    last_name_map[last] = []
                last_name_map[last].append(br_id)

        def _find_gamelog(player: str, team: str) -> dict | None:
            # First try br_player_id exact match
            br_id = br_id_map.get((player, team), '')
            if br_id and br_id in gamelog:
                return gamelog[br_id]
            # Fallback: try last name match
            last = _extract_last_name(player)
            if last and last in last_name_map:
                candidates = last_name_map[last]
                if len(candidates) == 1:
                    return gamelog[candidates[0]]
                # Multiple candidates: prefer the one with more complete data
                # (ast > 0 is a good signal for high-quality data)
                best = None
                best_score = -1
                for cid in candidates:
                    gl = gamelog[cid]
                    score = 0
                    if gl.get('ast', 0) and gl.get('ast', 0) > 0:
                        score += 10
                    if gl.get('stl', 0) and gl.get('stl', 0) > 0:
                        score += 2
                    if gl.get('blk', 0) and gl.get('blk', 0) > 0:
                        score += 2
                    if gl.get('team', '').upper() == team.upper():
                        score += 1
                    if gl.get('player_name'):
                        score += 1
                    if score > best_score:
                        best_score = score
                        best = gl
                return best
            return None

        for r in result:
            gl = _find_gamelog(r['player'], r['team'])
            if gl:
                r['br_player_id'] = gl.get('br_player_id', '')
                r['player_full_name'] = gl.get('player_name', r['player'])
                r['gamelog'] = gl
                r['game_pts'] = gl.get('pts')
                r['game_ast'] = gl.get('ast')
                r['game_reb'] = gl.get('reb')
                r['game_stl'] = gl.get('stl')
                r['game_blk'] = gl.get('blk')
                r['game_tov'] = gl.get('tov')
                r['game_pf'] = gl.get('pf')

    return result


def _parse_sub_in(desc: str) -> str | None:
    """Parse the IN player name from a substitution description.

    Description format: "SUB: <IN> FOR <OUT>" or "SUB: <IN> for <OUT>"
    Returns the IN player name, or None if not parseable.
    """
    if not desc:
        return None
    d = desc.strip()
    # Remove leading "SUB:" or "SUB "
    if d.upper().startswith('SUB'):
        d = d[3:].lstrip(': ').strip()
    # Split on " FOR " (case-insensitive)
    lower = d.lower()
    idx = lower.find(' for ')
    if idx >= 0:
        return d[:idx].strip()
    return None


def _parse_assist_player(desc: str) -> str | None:
    """Parse the assister name from a description containing 'Assist by'.

    Description format: "... (A. Player)" or "Assist by X" or "Assisted by X"
    Returns the assister name, or None.
    """
    if not desc:
        return None
    lower = desc.lower()
    # Try "Assist by <name>" or "Assisted by <name>"
    for marker in ('assist by ', 'assisted by '):
        idx = lower.find(marker)
        if idx >= 0:
            # Take the rest, trim trailing punctuation
            rest = desc[idx + len(marker):].strip()
            # Truncate at next period or parenthesis
            for stop in ('(', '.', ','):
                si = rest.find(stop)
                if si > 0:
                    rest = rest[:si].strip()
            return rest or None
    return None
