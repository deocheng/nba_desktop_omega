"""NBACore v8.2 — Intelligence Engine shared helpers.

Pure utilities only (no DB, no pandas business logic). Safe to import from any
sub-module without creating import cycles.
"""
from __future__ import annotations

import pandas as pd


def to_df(rows: list[dict] | None) -> pd.DataFrame:
    """Convert a list[dict] (Layer-1 loader output) to a DataFrame.

    Returns an empty DataFrame (not None) when there is no data so downstream
    vectorized code can run uniformly without None-guards.
    """
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Element-wise divide that yields NaN (not Inf/error) on zero denom."""
    denom = denominator.replace(0, pd.NA)
    return numerator / denom
