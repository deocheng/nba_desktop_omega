"""NBACore v8 §2 Layer 2 — v8.1 derived metrics.

Implements the v8.1 Metric Expansion PRD §3.1 + §8 derived metrics:
    - ast_to_ratio            (AST / TOV)            — playmaking efficiency
    - def_activity_efficiency ((STL + BLK) / PF)      — defensive discipline
    - team_scoring_share      (player PPG / team PPG) — team scoring impact

Follows the same vectorized, groupby(player_id) pattern as advanced.py.
All denominators are guarded with .clip(lower=1.0) to avoid div-by-zero
(v8 §6 compliant: no eval/exec, pure pandas).

team_scoring_share reads from a dedicated Layer-1 source table
"player_team_share" (player season stats joined with team season points),
keeping the cross-table join in the data layer (v8 §2 isolation).
"""
from __future__ import annotations

import pandas as pd

from backend.services.metric_engine.registry import MetricSpec, register

_BASIC_SOURCE = "fact_player_season_stats"
_SHARE_SOURCE = "player_team_share"


# v8.1 §3.1 — Assist Turnover Ratio = AST / TOV
def _ast_to_ratio(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    ast = grp["ast"].sum()
    tov = grp["tov"].sum().clip(lower=1.0)
    return ast / tov


# v8.1 §3.1 — Defensive Activity Efficiency = (STL + BLK) / PF
def _def_activity_efficiency(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    events = grp["stl"].sum() + grp["blk"].sum()
    pf = grp["pf"].sum().clip(lower=1.0)
    return events / pf


# v8.1 §8 — Team Scoring Share = player PPG / team PPG
# Source rows carry pts, g (player) and team_pts, team_g (team season totals).
def _team_scoring_share(df: pd.DataFrame) -> pd.Series:
    grp = df.groupby(df.index)
    player_pts = grp["pts"].sum()
    player_g = grp["g"].sum().clip(lower=1.0)
    team_pts = grp["team_pts"].sum()
    team_g = grp["team_g"].sum().clip(lower=1.0)
    player_ppg = player_pts / player_g
    team_ppg = (team_pts / team_g).clip(lower=1.0)
    return player_ppg / team_ppg


register(MetricSpec(
    name="ast_to_ratio",
    kind="ratio",
    source_table=_BASIC_SOURCE,
    required_cols=("ast", "tov"),
    compute=_ast_to_ratio,
    description="Assist/Turnover ratio = sum(ast) / sum(tov) (tov>0)",
    min_denominator=1.0,
))

register(MetricSpec(
    name="def_activity_efficiency",
    kind="ratio",
    source_table=_BASIC_SOURCE,
    required_cols=("stl", "blk", "pf"),
    compute=_def_activity_efficiency,
    description="Defensive Activity Efficiency = (sum(stl) + sum(blk)) / sum(pf) (pf>0)",
    min_denominator=1.0,
))

register(MetricSpec(
    name="team_scoring_share",
    kind="ratio",
    source_table=_SHARE_SOURCE,
    required_cols=("pts", "g", "team_pts", "team_g"),
    compute=_team_scoring_share,
    description="Team Scoring Share = (player pts/g) / (team pts/g) for the season",
    min_denominator=1.0,
))
