"""NBACore v8 §2 Layer 2 — Matrix Builder.

Converts raw list[dict] (from data_layer) into a pandas DataFrame indexed
by player_id. All vectorized computation in executor.py operates on this.

Guarantees:
    - player_id becomes the index (string-typed for BBR consistency)
    - missing required columns raise early (fail-fast)
    - NaN values preserved (executor handles via fillna where appropriate)
"""
from __future__ import annotations

import pandas as pd


def build_matrix(
    rows: list[dict],
    player_col: str,
    required_cols: tuple[str, ...] = (),
    extra_cols: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Build a player-indexed DataFrame from raw DB rows.

    Args:
        rows: list[dict] from data_layer batch loaders
        player_col: column name holding the player_id (e.g. 'player_id')
        required_cols: columns the metric compute fn will read; missing → ValueError
        extra_cols: optional columns to keep but not require

    Returns:
        pd.DataFrame indexed by player_col (as string for BBR consistency).
        Rows with NULL/None/NaN player_id are dropped (they would aggregate
        multiple players into a single bogus index entry).

    Raises:
        ValueError: empty rows, missing player_col, or missing required_cols.
    """
    if not rows:
        raise ValueError("build_matrix requires at least one row")
    if not player_col:
        raise ValueError("player_col must be non-empty")

    df = pd.DataFrame(rows)

    if player_col not in df.columns:
        raise ValueError(
            f"player_col {player_col!r} not in rows. "
            f"Available: {sorted(df.columns)}"
        )

    # Fail-fast: verify required columns exist
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"required columns missing from rows: {missing}. "
            f"Available: {sorted(df.columns)}"
        )

    # Drop rows with NULL/None/NaN player_id BEFORE coercing to string.
    # Without this, astype(str) turns NaN into the literal string "None",
    # which then aggregates every null-player row into one bogus index entry.
    df = df[df[player_col].notna()]

    # Also reject empty-string player_ids (defensive)
    df = df[df[player_col].astype(str).str.len() > 0]

    if df.empty:
        raise ValueError(
            f"build_matrix: all rows had NULL/empty {player_col!r}; "
            f"nothing to compute"
        )

    # Coerce player_id to string (BBR IDs like 'achiupr01' are string)
    df[player_col] = df[player_col].astype(str)

    # Set index
    df = df.set_index(player_col)

    # Keep only required + extra (drop noise, save memory)
    keep = list(dict.fromkeys(required_cols + extra_cols))  # dedup, preserve order
    if keep:
        df = df[keep]

    return df


def coerce_numeric(df: pd.DataFrame, cols: tuple[str, ...]) -> pd.DataFrame:
    """Coerce specified columns to numeric (non-numeric → NaN).

    Defensive: DB returns Decimal/float/int mixed; pandas usually infers but
    some columns (e.g. 'pos' or 'team') may sneak in as object dtype.
    """
    for c in cols:
        if c in df.columns and df[c].dtype == object:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df
