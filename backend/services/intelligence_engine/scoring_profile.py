"""NBACore v8.2 §10 — Scoring Profile.

Groups a player's shot attempts by location and reports frequency + efficiency
per zone. Source: `player_shooting` (BR shot-zone splits), which carries
per-range `percent_fga_from_*` (frequency) and `fg_percent_from_*` (efficiency)
for 5 distance bands.

NOTE (data honesty): the PRD §10 lists 7 *play-type* categories (At Rim, Post
Up, Isolation, PnR, Spot Up, Transition, Pull Up). This dataset only has
*location* bands, not event-tagged play types. We therefore expose the
location-based profile (the data that actually exists) and group the 5 BR
bands into 4 canonical zones. Play-type scoring requires event-level
play-by-play tagging not present here — documented as a known limitation, not
silently faked.
"""
from __future__ import annotations

import math

import pandas as pd

from backend.services.intelligence_engine.common import to_df
from backend.services.intelligence_engine.loader import load_player_shooting

# BR distance band -> canonical zone
_ZONE_MAP = {
    "percent_fga_from_x0_3_range": "At Rim",
    "percent_fga_from_x3_10_range": "Paint",
    "percent_fga_from_x10_16_range": "Mid-Range",
    "percent_fga_from_x16_3p_range": "Mid-Range",
    "percent_fga_from_x3p_range": "Three Point",
}
_FREQ_COLS = list(_ZONE_MAP.keys())
_EFF_COLS = [c.replace("percent_fga", "fg_percent") for c in _FREQ_COLS]


def scoring_profile(
    player_id: str,
    season: int,
    season_type: str = "Regular",
) -> dict:
    """Return {zone: {frequency, efficiency}} for a player's shooting.

    frequency = share of FGA from that zone (0-1), summed across bands.
    efficiency = FGA-weighted FG% for that zone (0-1).
    """
    rows = load_player_shooting(player_id, season, season_type)
    df = to_df(rows)
    if df.empty:
        return {}

    # Aggregate the 5 BR bands into canonical zones.
    zones: dict[str, dict] = {}
    for freq_col, zone in _ZONE_MAP.items():
        eff_col = freq_col.replace("percent_fga", "fg_percent")
        if freq_col not in df or eff_col not in df:
            continue
        freq = float(df[freq_col].fillna(0.0).iloc[0])
        eff = float(df[eff_col].fillna(0.0).iloc[0])
        if zone not in zones:
            zones[zone] = {"freq": 0.0, "_wsum": 0.0}
        # Weight efficiency by frequency (defensive: ignore zero-freq bands).
        if freq > 0:
            zones[zone]["_wsum"] += eff * freq
        zones[zone]["freq"] += freq

    result: dict[str, dict] = {}
    for zone, agg in zones.items():
        freq = agg["freq"]
        eff = (agg["_wsum"] / freq) if freq > 0 else 0.0
        result[zone] = {
            "frequency": round(freq, 4),
            "efficiency": round(eff, 4),
        }
    return result
