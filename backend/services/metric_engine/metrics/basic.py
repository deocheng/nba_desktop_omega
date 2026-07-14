"""NBACore v8 §2 Layer 2 — Basic per-game metrics (PPG / RPG / APG / SPG / BPG).

All compute fns are vectorized pandas operations on a player-indexed DataFrame.
fact_player_season_stats has season totals, so per-game = total / games.
"""
from __future__ import annotations

import pandas as pd

from backend.services.metric_engine.registry import MetricFn, MetricSpec, register

_SOURCE = "fact_player_season_stats"


def _per_game(numerator_col: str) -> MetricFn:
    """Build a vectorized compute fn: sum(numerator) / sum(games)."""
    def _compute(df: pd.DataFrame) -> pd.Series:
        # df is indexed by player_id; for fact_player_season_stats each row IS
        # one player-season (no groupby needed). Sum is defensive in case of
        # multi-row players (e.g. traded mid-season produces 2 rows).
        g = df.groupby(df.index)[numerator_col].sum()
        games = df.groupby(df.index)["g"].sum().clip(lower=1)
        return g / games
    return _compute


register(MetricSpec(
    name="pts_per_game",
    kind="per_game",
    source_table=_SOURCE,
    required_cols=("pts", "g"),
    compute=_per_game("pts"),
    description="Points per game = sum(pts) / sum(g)",
))

register(MetricSpec(
    name="reb_per_game",
    kind="per_game",
    source_table=_SOURCE,
    required_cols=("trb", "g"),
    compute=_per_game("trb"),
    description="Total rebounds per game = sum(trb) / sum(g)",
))

register(MetricSpec(
    name="ast_per_game",
    kind="per_game",
    source_table=_SOURCE,
    required_cols=("ast", "g"),
    compute=_per_game("ast"),
    description="Assists per game = sum(ast) / sum(g)",
))

register(MetricSpec(
    name="stl_per_game",
    kind="per_game",
    source_table=_SOURCE,
    required_cols=("stl", "g"),
    compute=_per_game("stl"),
    description="Steals per game = sum(stl) / sum(g)",
))

register(MetricSpec(
    name="blk_per_game",
    kind="per_game",
    source_table=_SOURCE,
    required_cols=("blk", "g"),
    compute=_per_game("blk"),
    description="Blocks per game = sum(blk) / sum(g)",
))

# ── v8.1 §3.1 Rebounding split metrics ──
register(MetricSpec(
    name="orb_per_game",
    kind="per_game",
    source_table=_SOURCE,
    required_cols=("orb", "g"),
    compute=_per_game("orb"),
    description="Offensive rebounds per game = sum(orb) / sum(g)",
))

register(MetricSpec(
    name="drb_per_game",
    kind="per_game",
    source_table=_SOURCE,
    required_cols=("drb", "g"),
    compute=_per_game("drb"),
    description="Defensive rebounds per game = sum(drb) / sum(g)",
))
