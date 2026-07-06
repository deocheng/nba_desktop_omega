"""NBACore v8 §2 Layer 2 — Composite weighted-sum metrics.

Fantasy points and efficiency rating are linear combinations of box score
totals. All fns are vectorized pandas operations.
"""
from __future__ import annotations

import pandas as pd

from backend.services.metric_engine.registry import MetricSpec, register

_SOURCE = "fact_player_season_stats"


# Fantasy points (standard fantasy basketball weights):
#   1.0*pts + 1.2*trb + 1.5*ast + 3.0*stl + 3.0*blk - 1.0*tov
# Plus bonus for 3pm (1.0 per x3p) to reward floor spacing.
def _fantasy_points(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    return (
        1.0 * grp["pts"].sum()
        + 1.2 * grp["trb"].sum()
        + 1.5 * grp["ast"].sum()
        + 3.0 * grp["stl"].sum()
        + 3.0 * grp["blk"].sum()
        - 1.0 * grp["tov"].sum()
        + 1.0 * grp["x3p"].sum()
    )


# Efficiency Rating (PER-inspired, simplified):
#   (pts + trb + ast + stl + blk) - (fga - fg) - (fta - ft) - tov
# Positive contributions minus missed shots and turnovers.
def _efficiency_rating(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    pts = grp["pts"].sum()
    trb = grp["trb"].sum()
    ast = grp["ast"].sum()
    stl = grp["stl"].sum()
    blk = grp["blk"].sum()
    fga = grp["fga"].sum()
    fg = grp["fg"].sum()
    fta = grp["fta"].sum()
    ft = grp["ft"].sum()
    tov = grp["tov"].sum()
    positives = pts + trb + ast + stl + blk
    negatives = (fga - fg) + (fta - ft) + tov
    return positives - negatives


register(MetricSpec(
    name="fantasy_points",
    kind="weighted_sum",
    source_table=_SOURCE,
    required_cols=("pts", "trb", "ast", "stl", "blk", "tov", "x3p"),
    compute=_fantasy_points,
    description="Fantasy points = 1.0*pts + 1.2*trb + 1.5*ast + 3.0*stl + 3.0*blk - 1.0*tov + 1.0*x3p",
))

register(MetricSpec(
    name="efficiency_rating",
    kind="expression",
    source_table=_SOURCE,
    required_cols=("pts", "trb", "ast", "stl", "blk", "fga", "fg", "fta", "ft", "tov"),
    compute=_efficiency_rating,
    description="Efficiency = (pts+trb+ast+stl+blk) - (fga-fg) - (fta-ft) - tov",
))
