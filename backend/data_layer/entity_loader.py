"""NBACore v8 — Entity aggregation loader (Layer 1 data access).

Provides season-coverage discovery and game-grouping aggregation for the
player / team dedicated pages.

Design notes (v8 §2 Layer 1):
  - Everything goes through backend.core.db.batch_query (SELECT-only).
  - Aggregation here is presentation-level shaping (grouping + averaging),
    NOT metric computation, and is permitted in Layer 1 for pre-render
    shaping of the entity pages.
  - dim_games stores BOTH NBA and BR abbr forms for divergent teams
    (BKN+BRK, CHA+CHO, NOP+NOH, PHX+PHO), so team queries match both.

Public API:
  season_label(season) -> "2025-26"
  load_player_seasons(player_id) -> list[int]            (desc)
  load_team_seasons(team_abbr) -> list[int]              (desc)
  load_player_games_aggregated(player_id, season, g) -> dict
  load_team_gamelog_with_game_context(season, team_abbr) -> list[dict]
  load_team_games_aggregated(team_abbr, season, g) -> dict
"""
from __future__ import annotations

import datetime as _dt
import logging

from backend.core.db import batch_query

logger = logging.getLogger("nbacore.data.entity_loader")

# NBA -> BR abbr divergence (mirror of team_loader._NBA_TO_BR_ABBR)
_NBA_TO_BR = {'BKN': 'BRK', 'PHX': 'PHO', 'CHA': 'CHO', 'UTAH': 'UTA', 'WAS': 'WAS'}
_BR_TO_NBA = {v: k for k, v in _NBA_TO_BR.items()}

_GRANULARITIES = {'season', 'month', 'week', 'game'}


def season_label(season: int) -> str:
    """Convert a season integer (ending year) to a 'YYYY-YY' label.

    e.g. 2026 -> '2025-26'. Mirrors the frontend seasonLabel() so the
    backend and frontend agree on season labels.
    """
    start = season - 1
    end = season % 100
    return f"{start}-{end:02d}"


def _candidate_abbrs(team_abbr: str) -> set[str]:
    """Return the NBA + BR abbr forms for a team (dim_games stores both)."""
    a = (team_abbr or '').upper()
    if not a:
        return set()
    return {a, _NBA_TO_BR.get(a, a), _BR_TO_NBA.get(a, a)}


def _num(x):
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _norm_pct(x):
    """Normalize a field that may be 0-1 or 0-100 into a 0-100 percentage."""
    v = _num(x)
    if v is None:
        return None
    if 0 < v <= 1:
        return round(v * 100, 1)
    return round(v, 1)


def _parse_date(d):
    if d is None:
        return None
    if isinstance(d, (_dt.date, _dt.datetime)):
        return d
    try:
        return _dt.datetime.strptime(str(d)[:10], '%Y-%m-%d')
    except ValueError:
        return None


def _iso_week_key(d: _dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def load_player_seasons(player_id: str) -> list[int]:
    """Distinct seasons the player has gamelog rows for (descending)."""
    if not player_id:
        return []
    rows = batch_query(
        "SELECT DISTINCT season FROM player_gamelog "
        "WHERE br_player_id = %s AND season IS NOT NULL ORDER BY season DESC",
        (player_id,),
    )
    return [r["season"] for r in rows]


def load_team_seasons(team_abbr: str) -> list[int]:
    """Distinct seasons the team appears in dim_games (descending)."""
    cand = list(_candidate_abbrs(team_abbr))
    if not cand:
        return []
    rows = batch_query(
        "SELECT DISTINCT season FROM dim_games "
        "WHERE (home_team_abbr = ANY(%s) OR away_team_abbr = ANY(%s)) AND season IS NOT NULL "
        "ORDER BY season DESC",
        (cand, cand),
    )
    return [r["season"] for r in rows]


def load_player_gamelog_with_game_context(season: int, player_id: str) -> list[dict]:
    """Delegate to the joins loader (joins player_gamelog with dim_games)."""
    from backend.data_layer.joins import load_player_gamelog_with_game_context as _join_loader
    return _join_loader(season, player_id)


def load_team_gamelog_with_game_context(season: int, team_abbr: str) -> list[dict]:
    """Team's games for a season from dim_games, with computed W/L + team pts.

    home_wl / away_wl are NULL in dim_games, so W/L is derived from the score.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    cand = list(_candidate_abbrs(team_abbr))
    if not cand:
        raise ValueError("team_abbr must be a non-empty string")
    sql = """
        SELECT game_id, game_date, home_team_abbr, away_team_abbr,
               home_pts, away_pts, home_fg_pct, away_fg_pct, season_type
        FROM dim_games
        WHERE season = %s
          AND (home_team_abbr = ANY(%s) OR away_team_abbr = ANY(%s))
        ORDER BY game_date
    """
    return batch_query(sql, (season, cand, cand))


def _to_game_row(kind: str, raw: dict, team_abbr: str | None = None) -> dict:
    """Normalize a joined row into a GameRow-shaped dict.

    kind='player': uses the player's team + player pts/fg_pct from gamelog.
    kind='team':   uses the team abbr + team pts/fg_pct from dim_games.
    The internal '_fg_pct' key carries the shooting % used only for the
    aggregate and is dropped before the public GameRow is built.
    """
    gd = _parse_date(raw.get('game_date'))

    if kind == 'player':
        team = raw.get('team')
        home = raw.get('home_team_abbr')
        away = raw.get('away_team_abbr')
        is_home = (team == home)
        opp = away if is_home else home
        home_pts = _num(raw.get('home_pts')) or 0.0
        away_pts = _num(raw.get('away_pts')) or 0.0
        team_pts = home_pts if is_home else away_pts
        opp_pts = away_pts if is_home else home_pts
        pts = _num(raw.get('pts'))
        fg = _norm_pct(raw.get('fg_pct'))
        game_id = str(raw.get('gameid'))
    else:
        cand = _candidate_abbrs(team_abbr or '')
        home = raw.get('home_team_abbr')
        away = raw.get('away_team_abbr')
        is_home = home in cand
        opp = away if is_home else home
        home_pts = _num(raw.get('home_pts')) or 0.0
        away_pts = _num(raw.get('away_pts')) or 0.0
        team_pts = home_pts if is_home else away_pts
        opp_pts = away_pts if is_home else home_pts
        pts = team_pts
        fg = _norm_pct(raw.get('home_fg_pct') if is_home else raw.get('away_fg_pct'))
        game_id = str(raw.get('game_id'))

    if team_pts > opp_pts:
        result = 'W'
    elif team_pts < opp_pts:
        result = 'L'
    else:
        result = 'T'

    return {
        'game_id': game_id,
        'game_date': gd.strftime('%Y-%m-%d') if gd else (str(raw.get('game_date')) if raw.get('game_date') else None),
        'opponent': opp,
        'is_home': bool(is_home),
        'result': result,
        'pts': pts,
        '_fg_pct': fg,
    }


def _aggregate_games(game_rows: list[dict], granularity: str, season: int) -> dict:
    """Group game_rows by granularity and compute per-group + total aggregates."""
    groups_map: dict[str, dict] = {}
    for gr in game_rows:
        gd = _parse_date(gr['game_date'])
        if granularity == 'season':
            key = str(season)
            label = season_label(season)
        elif granularity == 'month':
            key = gd.strftime('%Y-%m') if gd else 'unknown'
            label = key
        elif granularity == 'week':
            key = _iso_week_key(gd) if gd else 'unknown'
            label = key
        else:  # game
            key = gr['game_id']
            label = gr['game_date'] or gr['game_id']
        bucket = groups_map.setdefault(key, {'key': key, 'label': label, 'games': [], 'pts': [], 'fg': []})
        bucket['games'].append({k: gr[k] for k in ('game_id', 'game_date', 'opponent', 'is_home', 'result', 'pts')})
        if gr.get('pts') is not None:
            bucket['pts'].append(gr['pts'])
        if gr.get('_fg_pct') is not None:
            bucket['fg'].append(gr['_fg_pct'])

    groups = []
    for g in groups_map.values():
        gp = len(g['games'])
        avg_pts = round(sum(g['pts']) / len(g['pts']), 1) if g['pts'] else None
        avg_fg = round(sum(g['fg']) / len(g['fg']), 1) if g['fg'] else None
        groups.append({
            'key': g['key'],
            'label': g['label'],
            'games': g['games'],
            'aggregate': {'gp': gp, 'pts': avg_pts, 'fg_pct': avg_fg},
        })

    if granularity == 'game':
        groups.sort(key=lambda g: g['games'][0].get('game_date') or '', reverse=True)
    else:
        groups.sort(key=lambda g: g['key'], reverse=True)

    all_pts = [gr['pts'] for gr in game_rows if gr.get('pts') is not None]
    all_fg = [gr['_fg_pct'] for gr in game_rows if gr.get('_fg_pct') is not None]
    totals = {
        'gp': len(game_rows),
        'pts': round(sum(all_pts) / len(all_pts), 1) if all_pts else None,
        'fg_pct': round(sum(all_fg) / len(all_fg), 1) if all_fg else None,
    }
    return {'groups': groups, 'totals': totals}


def load_player_games_aggregated(player_id: str, season: int, granularity: str) -> dict:
    """Player's games for a season, grouped by granularity."""
    if granularity not in _GRANULARITIES:
        raise ValueError(f"Invalid granularity {granularity!r}; expected one of {sorted(_GRANULARITIES)}")
    rows = load_player_gamelog_with_game_context(season, player_id)
    game_rows = [_to_game_row('player', r) for r in rows]
    return _aggregate_games(game_rows, granularity, season)


def load_team_games_aggregated(team_abbr: str, season: int, granularity: str) -> dict:
    """Team's games for a season, grouped by granularity."""
    if granularity not in _GRANULARITIES:
        raise ValueError(f"Invalid granularity {granularity!r}; expected one of {sorted(_GRANULARITIES)}")
    rows = load_team_gamelog_with_game_context(season, team_abbr)
    game_rows = [_to_game_row('team', r, team_abbr) for r in rows]
    return _aggregate_games(game_rows, granularity, season)
