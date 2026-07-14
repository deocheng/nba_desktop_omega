"""NBACore v8 §2 Layer 2 — Vectorized Executor.

The ONLY module that runs metric.compute() on a matrix. Enforces:
    - metric must be in registry
    - required_cols validated by matrix_builder (fail-fast)
    - output rounded to spec.precision (determinism)
    - NaN values preserved (no implicit fill)
    - no eval/exec — compute is a Callable

v8 §6 forbidden list:
    - no eval() / exec()
    - no dynamic SQL
    - no per-player loop (compute must be vectorized)
"""
from __future__ import annotations

import logging

import pandas as pd

from backend.services.metric_engine.matrix_builder import build_matrix, coerce_numeric
from backend.services.metric_engine.registry import MetricSpec, get_registry

logger = logging.getLogger("nbacore.metric.executor")


def execute_metric(
    metric_name: str,
    rows: list[dict],
    player_col: str,
) -> pd.Series:
    """Compute a metric over raw rows. Returns player_id → value Series.

    Args:
        metric_name: registered metric name (KeyError if unknown)
        rows: raw DB rows (list[dict]) from data_layer
        player_col: column name for player_id

    Returns:
        pd.Series indexed by player_col (str), values rounded to spec.precision.
        NaN preserved (callers may filter via RankEngine.min_games).
    """
    spec = get_registry().get(metric_name)
    return execute_spec(spec, rows, player_col)


def execute_spec(
    spec: MetricSpec,
    rows: list[dict],
    player_col: str,
) -> pd.Series:
    """Execute a MetricSpec over rows. Lower-level than execute_metric."""
    matrix = build_matrix(rows, player_col, required_cols=spec.required_cols)
    matrix = coerce_numeric(matrix, spec.required_cols)

    # NOTE: Duplicate player_id rows (e.g. traded players with multiple
    # team stints) are handled INSIDE each metric's compute() function via
    # groupby(df.index). Each metric knows the correct aggregation strategy
    # for its inputs (sum for totals, weighted avg for ratios, etc.).
    # We intentionally do NOT pre-aggregate here because a naive .sum()
    # would corrupt ratio columns like fg_pct, ft_pct, usg_percent.

    series = spec.compute(matrix)

    if not isinstance(series, pd.Series):
        raise TypeError(
            f"metric {spec.name!r} compute() returned {type(series).__name__}, "
            f"expected pd.Series"
        )

    # Determinism: round to fixed precision (NaN stays NaN)
    series = series.round(spec.precision)
    series.name = spec.name
    return series


def execute_many(
    metric_names: list[str],
    rows: list[dict],
    player_col: str,
) -> pd.DataFrame:
    """Compute multiple metrics over the SAME rows. Returns DataFrame.

    Efficient: builds matrix once per unique source_table, then runs each
    metric's compute() on the shared matrix. All metrics must share the
    same source_table (otherwise use execute_metric per metric).
    """
    if not metric_names:
        raise ValueError("execute_many requires at least one metric name")

    registry = get_registry()
    specs = [registry.get(n) for n in metric_names]
    tables = {s.source_table for s in specs}
    if len(tables) > 1:
        raise ValueError(
            f"execute_many requires all metrics share source_table; got {tables}"
        )

    # Union of required cols (matrix_builder keeps them all)
    all_required: tuple[str, ...] = ()
    for s in specs:
        all_required = all_required + s.required_cols
    # Dedup preserving order
    seen: set[str] = set()
    unique_required = tuple(c for c in all_required if not (c in seen or seen.add(c)))

    matrix = build_matrix(rows, player_col, required_cols=unique_required)
    matrix = coerce_numeric(matrix, unique_required)

    # NOTE: Duplicate player_id rows are handled inside each metric's
    # compute() function. We use unique index for the result DataFrame
    # because each compute() returns a Series with unique player_id index.
    unique_index = matrix.index.unique()
    result = pd.DataFrame(index=unique_index)
    for spec in specs:
        col = spec.compute(matrix).round(spec.precision)
        result[spec.name] = col

    return result


def list_available_metrics() -> list[str]:
    """Convenience: list registered metric names."""
    return get_registry().list()
