"""NBACore v8 §2 Layer 2 — Advanced ratio metrics (TS% / eFG% / USG%).

All ratio metrics use the same pattern: sum(numerator) / sum(denominator)
with clip(lower=1.0) guard to prevent div-by-zero. NaN preserved where
denominator is 0.
"""
from __future__ import annotations

import pandas as pd

from backend.services.metric_engine.registry import MetricSpec, register

_SOURCE = "fact_player_season_stats"


# True Shooting % = pts / (2 * (fga + 0.44 * fta))
def _ts_pct(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    pts = grp["pts"].sum()
    fga = grp["fga"].sum()
    fta = grp["fta"].sum()
    denom = (2 * (fga + 0.44 * fta)).clip(lower=1.0)
    return pts / denom


# Effective FG % = (fg + 0.5 * x3p) / fga
def _efg_pct(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    fg = grp["fg"].sum()
    x3p = grp["x3p"].sum()
    fga = grp["fga"].sum()
    denom = fga.clip(lower=1.0)
    return (fg + 0.5 * x3p) / denom


# FT Rate = fta / fga
def _ft_rate(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    fta = grp["fta"].sum()
    fga = grp["fga"].sum()
    denom = fga.clip(lower=1.0)
    return fta / denom


# USG% is already a column in fact_player_season_stats — pass-through
def _usg_passthrough(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    return grp["usg_percent"].mean()  # mean across multi-row players


register(MetricSpec(
    name="true_shooting_pct",
    kind="ratio",
    source_table=_SOURCE,
    required_cols=("pts", "fga", "fta"),
    compute=_ts_pct,
    description="True Shooting % = pts / (2 * (fga + 0.44 * fta))",
    min_denominator=1.0,
))

register(MetricSpec(
    name="effective_fg_pct",
    kind="ratio",
    source_table=_SOURCE,
    required_cols=("fg", "x3p", "fga"),
    compute=_efg_pct,
    description="Effective FG % = (fg + 0.5 * x3p) / fga",
    min_denominator=1.0,
))

register(MetricSpec(
    name="ft_rate",
    kind="ratio",
    source_table=_SOURCE,
    required_cols=("fta", "fga"),
    compute=_ft_rate,
    description="FT Rate = fta / fga",
    min_denominator=1.0,
))

register(MetricSpec(
    name="usage_percent",
    kind="expression",
    source_table=_SOURCE,
    required_cols=("usg_percent",),
    compute=_usg_passthrough,
    description="Usage % (pass-through from fact_player_season_stats.usg_percent)",
))
