"""NBACore v8.2 §7 — Availability Intelligence.

Player value depends on availability. Two signals:

    Availability Score = Games Played / Team Games
    Minutes Share      = Player Minutes / Team Minutes

Both are clipped to [0, 1]. Team games/minutes come from the team fact table;
for playoff season_type the team fact carries only regular-season totals, so
playoff availability uses the regular-season team games as a denominator proxy
(this is a documented dataset limitation, not a computation error).
"""
from __future__ import annotations

import math

import pandas as pd

from backend.services.intelligence_engine.common import to_df
from backend.services.intelligence_engine.loader import (
    load_player_intel,
    load_team_intel,
)


# ── Pure helpers (unit-testable without DB) ──

def availability_score(player_games: float, team_games: float) -> float:
    """Games played / team games, clipped to [0, 1]."""
    pg = float(player_games)
    tg = float(team_games)
    if tg <= 0:
        return 0.0
    return min(1.0, pg / tg)


def minutes_share(player_minutes: float, team_minutes: float) -> float:
    """Player minutes / team minutes, clipped to [0, 1]."""
    pm = float(player_minutes)
    tm = float(team_minutes)
    if tm <= 0:
        return 0.0
    return min(1.0, pm / tm)


# ── DB-backed wrappers (used by API / tests) ──

def compute_availability(
    season: int,
    player_ids: list[str] | None = None,
    season_type: str = "Regular",
) -> dict[str, dict]:
    """Compute availability signals for players in a season.

    Returns:
        {player_id: {
            "team", "games", "team_games", "availability",
            "minutes", "team_minutes", "minutes_share"
        }}
    """
    players = load_player_intel(season, season_type, player_ids)
    df = to_df(players)
    if df.empty:
        return {}

    teams = load_team_intel(season)
    tdf = to_df(teams)
    if not tdf.empty:
        team_games = dict(zip(tdf["abbreviation"].astype(str), tdf["g"]))
        team_minutes = dict(zip(tdf["abbreviation"].astype(str), tdf["mp"]))
    else:
        team_games, team_minutes = {}, {}

    # Fallback denominators: 82 team games, 82*240 team minutes.
    df["team_games"] = df["team"].astype(str).map(team_games).fillna(82.0)
    df["team_minutes"] = (
        df["team"].astype(str).map(team_minutes).fillna(df["g"] * 240.0)
    )

    df["availability"] = (df["g"] / df["team_games"]).clip(0, 1).round(4)
    df["minutes_share"] = (df["mp"] / df["team_minutes"]).clip(0, 1).round(4)

    cols = ["player_id", "team", "g", "team_games", "availability",
            "mp", "team_minutes", "minutes_share"]
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
