"""NBACore v8.2 §5 — Pace Adjustment.

Era/pace contexts differ wildly (1990s low-pace vs modern high-pace). Raw
per-game stats are not comparable across paces. We adjust a player's stat to a
common pace using:

    Adjusted Stat = Player Stat × (League Avg Pace / Team Pace)

Pace (possessions per 48 team-minutes) is derived from team totals:

    Possessions = FGA - ORB + TOV + 0.44 × FTA
    Pace        = 240 × TotalPossessions / TotalTeamMinutes

(the factor 240 = 5 players × 48 minutes normalizes team-minutes to a
per-48 scale). League pace is the minutes-weighted average of all 30 team
paces for the season.

All functions are vectorized pandas — no per-player loops, no SQL.
"""
from __future__ import annotations

import math

import pandas as pd

from backend.services.intelligence_engine.common import safe_div, to_df
from backend.services.intelligence_engine.loader import (
    load_player_intel,
    load_team_intel,
)

PACE_COEF_FTA = 0.44


# ── Pure helpers (unit-testable without DB) ──

def team_possessions(team_row) -> float:
    """Team possessions for a season from box-score totals."""
    fga = float(team_row["fga"])
    orb = float(team_row["orb"])
    tov = float(team_row["tov"])
    fta = float(team_row["fta"])
    return fga - orb + tov + PACE_COEF_FTA * fta


def team_pace(team_row) -> float:
    """Team pace (possessions per 48 team-minutes)."""
    mp = float(team_row["mp"])
    if mp <= 0:
        return 0.0
    return 240.0 * team_possessions(team_row) / mp


def league_pace(team_rows) -> float:
    """Minutes-weighted league-average pace across team rows.

    Accepts either a list[dict] or a DataFrame of team season rows.
    """
    if isinstance(team_rows, pd.DataFrame):
        df = team_rows
    else:
        df = to_df(team_rows)
    if df.empty or "mp" not in df:
        return 0.0
    poss = (df["fga"] - df["orb"] + df["tov"] + PACE_COEF_FTA * df["fta"]).sum()
    mp = df["mp"].sum()
    if mp <= 0:
        return 0.0
    return 240.0 * float(poss) / float(mp)


def pace_adjust(value: float, league_pace_: float, team_pace_: float) -> float:
    """Adjust a single stat value to league pace.

    If team_pace is unknown/zero, returns the original value unchanged
    (cannot safely rescale).
    """
    if team_pace_ is None or team_pace_ <= 0:
        return float(value)
    return float(value) * (league_pace_ / team_pace_)


# ── DB-backed wrappers (used by API / tests) ──

def compute_team_paces(season: int) -> dict[str, float]:
    """Return {abbreviation: pace} for every team in a season."""
    teams = load_team_intel(season)
    df = to_df(teams)
    if df.empty:
        return {}
    df["pace"] = (240.0 * (df["fga"] - df["orb"] + df["tov"] + PACE_COEF_FTA * df["fta"])
                  / df["mp"].replace(0, pd.NA)).fillna(0.0)
    return dict(zip(df["abbreviation"].astype(str), df["pace"].round(4)))


def compute_league_pace(season: int) -> float:
    """Minutes-weighted league-average pace for a season."""
    return round(league_pace(load_team_intel(season)), 4)


def pace_adjust_player_stats(
    season: int,
    player_ids: list[str] | None = None,
    season_type: str = "Regular",
) -> dict[str, dict]:
    """Pace-adjust the 4 core per-game/rate stats for players in a season.

    Returns:
        {player_id: {
            "team", "league_pace", "team_pace",
            "adjusted_points", "adjusted_assists",
            "adjusted_rebounds", "adjusted_usage"
        }}

    adjusted_* are rounded to 6 decimals; None where the source per-game
    value is undefined (e.g. 0 games). Team pace falls back to league pace if
    the player's team is somehow missing from the team fact table.
    """
    players = load_player_intel(season, season_type, player_ids)
    df = to_df(players)
    if df.empty:
        return {}

    team_paces = compute_team_paces(season)
    lg = compute_league_pace(season)
    df["team_pace"] = df["team"].astype(str).map(team_paces).fillna(lg)
    ratio = lg / df["team_pace"].replace(0, pd.NA)

    df["adjusted_points"] = (safe_div(df["pts"], df["g"]) * ratio).round(6)
    df["adjusted_assists"] = (safe_div(df["ast"], df["g"]) * ratio).round(6)
    df["adjusted_rebounds"] = (safe_div(df["trb"], df["g"]) * ratio).round(6)
    df["adjusted_usage"] = (df["usg_percent"] * ratio).round(6)

    df["league_pace"] = round(lg, 4)
    df["team_pace"] = df["team_pace"].round(4)

    cols = ["player_id", "team", "league_pace", "team_pace",
            "adjusted_points", "adjusted_assists", "adjusted_rebounds", "adjusted_usage"]
    result: dict[str, dict] = {}
    for rec in df[cols].to_dict("records"):
        pid = rec.pop("player_id")
        clean = {}
        for k, v in rec.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                clean[k] = None
            else:
                clean[k] = v
        result[pid] = clean
    return result
