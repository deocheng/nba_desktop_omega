"""Trend analysis — linear trend + momentum for a single metric across seasons.

All data sourced from Metric Engine (layer 2). No DB access.

Output:
    - slope (per-season change)
    - intercept
    - r-squared (goodness of fit)
    - momentum (recent slope vs overall slope)
    - predicted next season value
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from backend.services.metric_engine import compute


@dataclass
class MetricTrend:
    player_id: str
    metric: str
    seasons: list[int]
    values: list[float | None]
    slope: float | None
    intercept: float | None
    r_squared: float | None
    momentum: float | None  # recent (last 3) vs overall slope ratio
    predicted_next: float | None
    direction: str  # "up" | "down" | "flat" | "insufficient_data"


def _linreg(x: list[float], y: list[float]) -> tuple[float, float, float]:
    """OLS regression: return (slope, intercept, r_squared)."""
    n = len(x)
    if n < 2:
        raise ValueError("Need at least 2 points")

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    ss_xy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    ss_xx = sum((xi - mean_x) ** 2 for xi in x)
    ss_yy = sum((yi - mean_y) ** 2 for yi in y)

    if ss_xx == 0:
        raise ValueError("Zero variance in x")

    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    r_squared = 0.0
    if ss_yy > 0:
        y_pred = [slope * xi + intercept for xi in x]
        ss_res = sum((yi - yp) ** 2 for yi, yp in zip(y, y_pred))
        r_squared = 1 - ss_res / ss_yy

    return slope, intercept, r_squared


def player_trend(
    player_id: str,
    metric: str,
    seasons: list[int],
) -> MetricTrend:
    """Compute linear trend for a single metric across seasons.

    Args:
        player_id: BBR player ID
        metric: registered metric name
        seasons: list of seasons to include (sorted)

    Returns:
        MetricTrend with slope, r_squared, momentum, prediction.
    """
    if not seasons:
        raise ValueError("seasons must not be empty")

    sorted_seasons = sorted(seasons)

    # Collect values per season
    values: list[float | None] = []
    for s in sorted_seasons:
        series = compute(metric, s, player_ids=[player_id])
        if not series.empty and player_id in series.index:
            v = float(series.loc[player_id])
            values.append(v if v == v else None)  # NaN → None
        else:
            values.append(None)

    # Filter to valid (season, value) pairs
    valid_x = [float(s) for s, v in zip(sorted_seasons, values) if v is not None]
    valid_y = [v for v in values if v is not None]

    if len(valid_x) < 2:
        return MetricTrend(
            player_id=player_id,
            metric=metric,
            seasons=sorted_seasons,
            values=values,
            slope=None,
            intercept=None,
            r_squared=None,
            momentum=None,
            predicted_next=None,
            direction="insufficient_data",
        )

    # Overall trend
    slope, intercept, r_squared = _linreg(valid_x, valid_y)

    # Momentum: compare last 3 seasons slope to overall slope
    momentum = None
    if len(valid_x) >= 4:
        recent_x = valid_x[-3:]
        recent_y = valid_y[-3:]
        try:
            recent_slope, _, _ = _linreg(recent_x, recent_y)
            if slope != 0:
                momentum = round(recent_slope / slope, 4)
        except ValueError:
            pass

    # Prediction for next season
    next_season = sorted_seasons[-1] + 1
    predicted_next = round(slope * float(next_season) + intercept, 4)

    # Direction
    direction = "flat"
    if abs(slope) > 1e-9:
        direction = "up" if slope > 0 else "down"

    return MetricTrend(
        player_id=player_id,
        metric=metric,
        seasons=sorted_seasons,
        values=values,
        slope=round(slope, 6),
        intercept=round(intercept, 4),
        r_squared=round(r_squared, 4),
        momentum=momentum,
        predicted_next=predicted_next,
        direction=direction,
    )
