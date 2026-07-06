"""Role evolution — how a player's statistical profile changed across seasons.

Compares the player's metric vector across multiple seasons to show:
- Which metrics grew / declined / stayed flat
- Overall role shift magnitude
- Key turning points

All data sourced from Metric Engine (layer 2). No DB access.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from backend.services.metric_engine import compute_many


@dataclass
class MetricChange:
    metric: str
    first_value: float | None
    last_value: float | None
    absolute_change: float | None
    pct_change: float | None
    direction: str  # "up" | "down" | "flat"
    trend_slope: float | None  # per-season linear trend slope


@dataclass
class RoleEvolution:
    player_id: str
    seasons: list[int]
    metric_changes: list[MetricChange]
    overall_shift_magnitude: float  # cosine distance between first and last season
    top_growth: list[str] = field(default_factory=list)
    top_decline: list[str] = field(default_factory=list)


def _linreg_slope(x: list[float], y: list[float]) -> float | None:
    """Simple OLS slope. Returns None if insufficient data or zero variance."""
    n = len(x)
    if n < 2:
        return None
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den = sum((xi - mean_x) ** 2 for xi in x)
    if den == 0:
        return None
    return num / den


def player_role_evolution(
    player_id: str,
    seasons: list[int],
    metric_names: list[str],
) -> RoleEvolution:
    """Analyze how a player's role evolved across seasons.

    Args:
        player_id: BBR player ID
        seasons: list of seasons to analyze (sorted ascending)
        metric_names: metrics to include in the profile

    Returns:
        RoleEvolution with per-metric changes and overall shift.
    """
    if not seasons or not metric_names:
        raise ValueError("seasons and metric_names must not be empty")

    sorted_seasons = sorted(seasons)

    # Collect per-season metric values for this player
    # season -> {metric: value}
    season_vals: dict[int, dict[str, float]] = {}
    for s in sorted_seasons:
        df = compute_many(metric_names, s, player_ids=[player_id])
        if df.empty or player_id not in df.index:
            continue
        row = df.loc[player_id]
        season_vals[s] = {m: float(row[m]) if m in row and row[m] == row[m] else None for m in metric_names}

    if len(season_vals) < 2:
        # Not enough seasons with data — return what we have
        return RoleEvolution(
            player_id=player_id,
            seasons=sorted(season_vals.keys()),
            metric_changes=[],
            overall_shift_magnitude=0.0,
        )

    valid_seasons = sorted(season_vals.keys())
    first_s = valid_seasons[0]
    last_s = valid_seasons[-1]

    # Build per-metric change analysis
    changes: list[MetricChange] = []
    first_vec: list[float] = []
    last_vec: list[float] = []

    for m in metric_names:
        first_val = season_vals[first_s].get(m)
        last_val = season_vals[last_s].get(m)

        # Time series for this metric
        series_x: list[float] = []
        series_y: list[float] = []
        for s in valid_seasons:
            v = season_vals[s].get(m)
            if v is not None:
                series_x.append(float(s))
                series_y.append(v)

        slope = _linreg_slope(series_x, series_y) if len(series_x) >= 2 else None

        abs_change = None
        pct_change = None
        direction = "flat"

        if first_val is not None and last_val is not None:
            abs_change = round(last_val - first_val, 4)
            if first_val != 0:
                pct_change = round((last_val - first_val) / abs(first_val) * 100, 2)
            if abs_change > 0:
                direction = "up"
            elif abs_change < 0:
                direction = "down"

        changes.append(MetricChange(
            metric=m,
            first_value=first_val,
            last_value=last_val,
            absolute_change=abs_change,
            pct_change=pct_change,
            direction=direction,
            trend_slope=round(slope, 4) if slope is not None else None,
        ))

        # For overall shift: include metrics with both values present
        if first_val is not None and last_val is not None:
            first_vec.append(first_val)
            last_vec.append(last_val)

    # Overall shift magnitude — cosine distance = 1 - cosine_similarity
    shift = 0.0
    if first_vec and last_vec and len(first_vec) >= 2:
        dot = sum(a * b for a, b in zip(first_vec, last_vec))
        norm_a = math.sqrt(sum(a * a for a in first_vec))
        norm_b = math.sqrt(sum(b * b for b in last_vec))
        if norm_a > 0 and norm_b > 0:
            cos_sim = dot / (norm_a * norm_b)
            shift = round(1 - cos_sim, 4)

    # Top growth / decline (by pct_change, requires non-zero first_val)
    growth = [c for c in changes if c.pct_change is not None and c.direction == "up"]
    decline = [c for c in changes if c.pct_change is not None and c.direction == "down"]
    growth.sort(key=lambda c: c.pct_change or 0, reverse=True)
    decline.sort(key=lambda c: c.pct_change or 0)

    return RoleEvolution(
        player_id=player_id,
        seasons=valid_seasons,
        metric_changes=changes,
        overall_shift_magnitude=shift,
        top_growth=[c.metric for c in growth[:3]],
        top_decline=[c.metric for c in decline[:3]],
    )
