"""NBACore v8.2 §16 — Historical Percentile Ranking.

Answers "how does this player's number rank historically?" by placing a
player's metric value against the league-wide distribution for the same
season + season_type.

Supported metrics (all present as columns in fact_player_season_stats):
    ppg        -> pts / g        (points per game)
    ts_percent -> ts_percent     (true shooting %)
    ast        -> ast / g        (assists per game)
    reb        -> trb / g        (rebounds per game)
    bpm        -> bpm            (box plus/minus)
    vorp       -> vorp           (value over replacement player)

Percentile uses the "mean" rank convention:
    pct = (below + 0.5 * equal) / n * 100
so a player better than 98.5% of peers reports 98.5 (matches PRD example).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from backend.services.intelligence_engine.common import safe_div, to_df
from backend.services.intelligence_engine.loader import load_player_intel

# metric -> (source_column, is_per_game)
METRIC_COLUMNS: dict[str, tuple[str, bool]] = {
    "ppg": ("pts", True),
    "ts_percent": ("ts_percent", False),
    "ast": ("ast", True),
    "reb": ("trb", True),
    "bpm": ("bpm", False),
    "vorp": ("vorp", False),
}


# ── Pure helper (unit-testable without DB) ──

def percentile_rank(value: float, distribution: "np.ndarray | pd.Series") -> float:
    """Percentile rank of `value` within `distribution` (mean convention)."""
    arr = np.asarray(distribution, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return 0.0
    v = float(value)
    if math.isnan(v):
        return 0.0
    below = int((arr < v).sum())
    equal = int((arr == v).sum())
    return round(float((below + 0.5 * equal) / arr.size * 100), 1)


# ── DB-backed wrapper (used by API / tests) ──

def historical_percentile(
    season: int,
    metric: str,
    player_ids: list[str] | None = None,
    season_type: str = "Regular",
) -> dict[str, dict]:
    """Compute historical percentile for players against the league distribution.

    Args:
        season: required NBA season (v8 §2).
        metric: one of METRIC_COLUMNS keys.
        player_ids: players to score. If None, scores every player that season.
        season_type: 'Regular' | 'Playoffs' | 'PlayIn'.

    Returns:
        {player_id: {"value": float, "percentile": float}}
        Players with undefined metrics are omitted.
    """
    if metric not in METRIC_COLUMNS:
        raise ValueError(
            f"Unsupported metric {metric!r}; supported: {sorted(METRIC_COLUMNS)}"
        )
    col, per_game = METRIC_COLUMNS[metric]

    all_rows = load_player_intel(season, season_type)
    adf = to_df(all_rows)
    if adf.empty or col not in adf:
        return {}

    dist = adf[col].astype(float)
    if per_game:
        dist = safe_div(dist, adf["g"].astype(float))
    dist = dist.replace([np.inf, -np.inf], np.nan).dropna()
    distribution = dist.to_numpy()

    if player_ids is None:
        players = all_rows
    else:
        players = load_player_intel(season, season_type, player_ids)
    pdf = to_df(players)
    if pdf.empty:
        return {}

    result: dict[str, dict] = {}
    for rec in pdf[["player_id", col, "g"]].to_dict("records"):
        raw = rec[col]
        if raw is None or (isinstance(raw, float) and math.isnan(raw)):
            continue
        val = float(raw)
        if per_game:
            g = rec.get("g")
            g = float(g) if g is not None else 0.0
            val = val / g if g > 0 else float("nan")
        if math.isnan(val):
            continue
        result[rec["player_id"]] = {
            "value": round(val, 6),
            "percentile": percentile_rank(val, distribution),
        }
    return result
