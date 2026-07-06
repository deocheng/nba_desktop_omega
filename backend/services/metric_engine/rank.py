"""NBACore v8 §2 Layer 2 — Rank Engine.

Converts a metric Series (player_id → value) into ranked output with
percentiles and stable tie-breaking.

Determinism (v8 §5.3):
    - Ties broken by player_id ascending (stable, deterministic)
    - Percentiles rounded to 4 decimals
    - NaN values excluded from ranking (returned with rank=None)
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Ranking:
    """Single player's ranking record."""
    rank: int                    # 1-based; ties share the same rank
    player_id: str
    value: float
    percentile: float            # 100.0 = top, 0.0 = bottom
    sample_size: int             # total players in this ranking


def rank_players(
    series: pd.Series,
    ascending: bool = False,
    min_value: float | None = None,
) -> list[Ranking]:
    """Rank players by metric value.

    Args:
        series: pd.Series indexed by player_id (str), values = metric output.
        ascending: False = highest first (default for most metrics).
        min_value: optional minimum value filter (e.g. min games played).
                   Players below this threshold are excluded entirely.

    Returns:
        list[Ranking] sorted by rank (1-based). Ties share the same rank;
        subsequent ranks skip (standard competition ranking: 1,1,3,4,...).

    Determinism:
        - Ties broken by player_id ascending (lexicographic on str).
        - NaN values excluded from ranking.
    """
    if series.empty:
        return []

    # Filter NaN values (don't rank missing data)
    s = series.dropna()

    # Apply min_value threshold
    if min_value is not None:
        s = s[s >= min_value]

    if s.empty:
        return []

    # Deterministic sort: primary by value, secondary by player_id asc (tie-break).
    # Build a temp DataFrame to use multi-key sort with mixed ascending flags.
    tmp = pd.DataFrame({"value": s.values, "player_id": s.index.astype(str)})
    tmp = tmp.sort_values(
        by=["value", "player_id"],
        ascending=[ascending, True],
        kind="mergesort",
    )
    tmp = tmp.reset_index(drop=True)

    n = len(tmp)
    values = tmp["value"].tolist()
    ids = tmp["player_id"].tolist()

    rankings: list[Ranking] = []
    i = 0
    while i < n:
        # Find run of equal values (ties)
        j = i + 1
        while j < n and values[j] == values[i]:
            j += 1
        # All entries i..j-1 share rank (i+1) — standard competition ranking
        rank = i + 1
        # Percentile: top performer = 100.0, bottom = 0.0
        # Use rank position: pct = 100 * (n - rank) / (n - 1) for n > 1
        if n > 1:
            pct = round(100.0 * (n - rank) / (n - 1), 4)
        else:
            pct = 100.0
        for k in range(i, j):
            rankings.append(Ranking(
                rank=rank,
                player_id=str(ids[k]),
                value=round(float(values[k]), 6),
                percentile=pct,
                sample_size=n,
            ))
        i = j

    return rankings


def to_dataframe(rankings: list[Ranking]) -> pd.DataFrame:
    """Convert rankings to DataFrame for API serialization."""
    if not rankings:
        return pd.DataFrame(columns=["rank", "player_id", "value", "percentile", "sample_size"])
    return pd.DataFrame([
        {
            "rank": r.rank,
            "player_id": r.player_id,
            "value": r.value,
            "percentile": r.percentile,
            "sample_size": r.sample_size,
        }
        for r in rankings
    ])
