"""NBACore v8 §2 Layer 3→1 — Player Profile Service (v8.1 expansion).

Wraps Layer-1 growth_loader functions for the v8.1 Metric Expansion PRD:
    - §7 Shot Profile Evolution    → get_shooting_profile()
    - §9 Career Defensive Summary  → get_career_defense()

The API router (Layer 3) calls THIS service, never data_layer directly,
preserving v8 §2 isolation (API → service → data_layer). No computation
happens here beyond reshaping raw rows into the contract shape.
"""
from __future__ import annotations

import logging

from backend.data_layer.growth_loader import (
    get_player_career_summary,
    get_player_shooting_career,
)

logger = logging.getLogger("nbacore.player_profile")

# Map Basketball-Reference player_shooting columns → v8.1 §7.1 zone names.
# NOTE: BR splits FGA into 0-3 / 3-10 / 10-16 / 16-3p / 3pt. The PRD asks for
# "Corner 3" vs "Above Break 3", which BR does NOT separate in this summary
# table, so the 3pt band is returned as a single "three_point" zone (documented
# in change-log). This keeps the output faithful to source granularity.
_ZONE_MAP = [
    ("restricted_area", "percent_fga_from_x0_3_range", "fg_percent_from_x0_3_range"),
    ("paint", "percent_fga_from_x3_10_range", "fg_percent_from_x3_10_range"),
    ("mid_range", "percent_fga_from_x10_16_range", "fg_percent_from_x10_16_range"),
    ("long_two", "percent_fga_from_x16_3p_range", "fg_percent_from_x16_3p_range"),
    ("three_point", "percent_fga_from_x3p_range", "fg_percent_from_x3p_range"),
]


def get_shooting_profile(player_id: str) -> dict:
    """v8.1 §7/§10.2 — per-season shooting zone profile.

    Args:
        player_id: BBR player ID.

    Returns:
        dict with:
            player_id, latest_season,
            seasons: list of {season, team, zones:[{zone, fg_pct, fga_rate}]}
        Returns {'player_id':..., 'seasons':[]} if no shooting data.
    """
    if not player_id:
        raise ValueError("player_id required")

    rows = get_player_shooting_career(player_id)
    if not rows:
        return {"player_id": player_id, "latest_season": None, "seasons": []}

    seasons_out = []
    for r in rows:  # rows already ordered season ASC by loader
        zones = []
        for zone, fga_col, fg_col in _ZONE_MAP:
            fga_rate = r.get(fga_col)
            fg_pct = r.get(fg_col)
            zones.append({
                "zone": zone,
                "fg_pct": round(float(fg_pct), 2) if fg_pct is not None else None,
                "fga_rate": round(float(fga_rate), 2) if fga_rate is not None else None,
            })
        seasons_out.append({
            "season": r.get("season"),
            "team": r.get("team"),
            "zones": zones,
        })

    return {
        "player_id": player_id,
        "latest_season": seasons_out[-1]["season"] if seasons_out else None,
        "seasons": seasons_out,
    }


def get_career_defense(player_id: str) -> dict:
    """v8.1 §9 — career defensive summary.

    Args:
        player_id: BBR player ID.

    Returns:
        dict with career defensive totals + per-game averages.
        Returns {'player_id':..., 'found': False} if player missing.
    """
    if not player_id:
        raise ValueError("player_id required")

    bio = get_player_career_summary(player_id)
    if not bio:
        return {"player_id": player_id, "found": False}

    seasons = bio.get("seasons") or 0
    total_games = bio.get("total_games") or 0
    stl = bio.get("total_steals") or 0
    blk = bio.get("total_blocks") or 0
    pf = bio.get("total_fouls") or 0
    orb = bio.get("total_offensive_rebounds") or 0
    drb = bio.get("total_defensive_rebounds") or 0

    def _pg(val: int) -> float:
        return round(val / total_games, 2) if total_games else 0.0

    return {
        "player_id": player_id,
        "found": True,
        "seasons": seasons,
        "total_games": total_games,
        "total_steals": stl,
        "total_blocks": blk,
        "total_fouls": pf,
        "total_offensive_rebounds": orb,
        "total_defensive_rebounds": drb,
        "stocks": stl + blk,
        "stocks_per_game": _pg(stl + blk),
        "steals_per_game": _pg(stl),
        "blocks_per_game": _pg(blk),
        "def_activity_efficiency": round((stl + blk) / pf, 3) if pf else None,
    }
