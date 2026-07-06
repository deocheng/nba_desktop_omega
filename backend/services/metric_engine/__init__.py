"""NBACore v8 §2 Layer 2 — Metric Engine (SOLE compute layer).

This package is the ONLY place where metric computation happens.
API layer (Phase 3) may only call public functions here; it must not
implement any computation itself (v8 §2 layer isolation).

Public API:
    - list_metrics()                      → list[str]
    - get_metric(name)                    → MetricSpec
    - compute(metric_name, season, ...)   → pd.Series
    - compute_many(names, season, ...)    → pd.DataFrame
    - rank(metric_name, season, ...)      → list[Ranking]

Architecture (v8 §2 Layer 2):
    registry.py        — MetricSpec dataclass + singleton MetricRegistry
    matrix_builder.py  — list[dict] → player-indexed DataFrame
    executor.py        — runs metric.compute() vectorized
    cache.py           — diskcache wrapper (SHA256 key, deterministic)
    batch_loader.py    — pulls rows from Layer 1 via data_layer
    rank.py            — Ranking dataclass + rank_players()
    metrics/           — built-in metric definitions (auto-registered on import)

v8 §6 forbidden list (enforced by tests):
    - no eval() / exec()
    - no dynamic SQL (no psycopg2 imports in this package)
    - no per-player loop (compute fns are vectorized pandas)
"""
from __future__ import annotations

# Importing metrics package triggers register() calls for built-in metrics.
# This MUST happen before any public API is called.
from backend.services.metric_engine import metrics  # noqa: F401  (side-effect import)
from backend.services.metric_engine.batch_loader import (
    available_source_tables,
    get_available_seasons,
    get_player_bios,
    load_metric_input,
    search_players_by_name,
)
from backend.services.metric_engine.cache import (
    CacheEngine,
    get_engine,
    make_cache_key,
    reset_engine,
)
from backend.services.metric_engine.executor import (
    execute_many,
    execute_metric,
    execute_spec,
    list_available_metrics,
)
from backend.services.metric_engine.rank import Ranking, rank_players, to_dataframe
from backend.services.metric_engine.registry import (
    MetricRegistry,
    MetricSpec,
    REGISTRY,
    get_registry,
    register,
)

__phase_status__ = "phase2-built"

__all__ = [
    # Registry
    "MetricSpec",
    "MetricRegistry",
    "REGISTRY",
    "get_registry",
    "register",
    # Executor
    "execute_metric",
    "execute_spec",
    "execute_many",
    "list_available_metrics",
    # Loader
    "load_metric_input",
    "available_source_tables",
    "get_player_bios",
    "search_players_by_name",
    # Cache
    "CacheEngine",
    "get_engine",
    "make_cache_key",
    "reset_engine",
    # Rank
    "Ranking",
    "rank_players",
    "to_dataframe",
    # High-level API
    "list_metrics",
    "get_metric",
    "compute",
    "compute_many",
    "rank",
    "player_metrics_dict",
    "vs_compare",
    "compute_as_dict",
    "compute_many_as_dict",
]


# ── High-level convenience API (used by Phase 3 API layer) ──

def list_metrics() -> list[str]:
    """List all registered metric names."""
    return list_available_metrics()


def get_metric(name: str) -> MetricSpec:
    """Fetch a MetricSpec by name."""
    return get_registry().get(name)


def compute(
    metric_name: str,
    season: int,
    player_ids: list[str] | None = None,
    use_cache: bool = True,
) -> "pd.Series":
    """Compute a single metric for a season (optionally filtered by player_ids).

    Args:
        metric_name: registered metric name
        season: NBA season (required, v8 §2)
        player_ids: optional BBR ID filter
        use_cache: if True, consult CacheEngine (default on)

    Returns: pd.Series indexed by player_id, values rounded to spec.precision.
    """
    import pandas as pd  # local import to avoid module-level dep at import time

    spec = get_metric(metric_name)
    cache_key = make_cache_key(metric_name, season, player_ids)

    if use_cache:
        engine = get_engine()
        cached = engine.get(cache_key)
        if cached is not None:
            return cached

    rows, player_col = load_metric_input(spec, season, player_ids)
    if not rows:
        # No data for requested players — return empty Series (not an error).
        import pandas as pd
        return pd.Series(name=metric_name, dtype=float)
    series = execute_spec(spec, rows, player_col)

    if use_cache:
        get_engine().set(cache_key, series)

    return series


def compute_many(
    metric_names: list[str],
    season: int,
    player_ids: list[str] | None = None,
    use_cache: bool = True,
) -> "pd.DataFrame":
    """Compute multiple metrics (must share source_table) for a season.

    Returns: pd.DataFrame indexed by player_id, columns = metric_names.
    """
    import pandas as pd

    if not metric_names:
        raise ValueError("compute_many requires at least one metric name")

    registry = get_registry()
    specs = [registry.get(n) for n in metric_names]
    tables = {s.source_table for s in specs}
    if len(tables) > 1:
        raise ValueError(
            f"compute_many requires all metrics share source_table; got {tables}"
        )

    # Cache key includes all metric names (sorted for stability)
    cache_key = make_cache_key(
        "+".join(sorted(metric_names)),
        season,
        player_ids,
    )

    if use_cache:
        engine = get_engine()
        cached = engine.get(cache_key)
        if cached is not None:
            return cached

    # All specs share source_table, so any spec's loader works
    rows, player_col = load_metric_input(specs[0], season, player_ids)
    if not rows:
        # No data for requested players — return empty DataFrame.
        import pandas as pd
        return pd.DataFrame(columns=metric_names)
    df = execute_many(metric_names, rows, player_col)

    if use_cache:
        get_engine().set(cache_key, df)

    return df


def rank(
    metric_name: str,
    season: int,
    player_ids: list[str] | None = None,
    ascending: bool = False,
    min_value: float | None = None,
    use_cache: bool = True,
) -> list[Ranking]:
    """Compute a metric and return ranked results.

    Args:
        metric_name: registered metric name
        season: NBA season
        player_ids: optional BBR ID filter
        ascending: False = highest first (default)
        min_value: optional minimum value filter (e.g. min games played)
        use_cache: cache the underlying metric computation

    Returns: list[Ranking] sorted by rank.
    """
    series = compute(metric_name, season, player_ids, use_cache=use_cache)
    return rank_players(series, ascending=ascending, min_value=min_value)


def player_metrics_dict(
    metric_names: list[str],
    season: int,
    player_id: str,
    use_cache: bool = True,
) -> dict[str, float]:
    """Compute multiple metrics for a single player, return as {metric: value}.

    Convenience for API layer: avoids exposing pandas DataFrame to Layer 3.
    NaN values are skipped (not included in the returned dict).

    Args:
        metric_names: list of registered metric names (must share source_table)
        season: NBA season
        player_id: BBR player_id
        use_cache: cache the underlying compute_many call
    """
    df = compute_many(metric_names, season, player_ids=[player_id], use_cache=use_cache)
    result: dict[str, float] = {}
    if player_id not in df.index:
        return result
    row = df.loc[player_id]
    for m in metric_names:
        if m not in row:
            continue
        val = row[m]
        # Skip NaN (player has no data for this metric)
        if val == val and val is not None:  # NaN check: NaN != NaN
            result[m] = float(val)
    return result


def vs_compare(
    metric_names: list[str],
    season: int,
    player_id_1: str,
    player_id_2: str,
    use_cache: bool = True,
) -> dict[str, dict[str, float]]:
    """Compute multiple metrics for two players, return side-by-side dict.

    Returns: {metric_name: {player_id_1: x, player_id_2: y}}
    NaN values are preserved as-is (callers can handle None).
    """
    df = compute_many(
        metric_names,
        season,
        player_ids=[player_id_1, player_id_2],
        use_cache=use_cache,
    )
    result: dict[str, dict[str, float]] = {}
    for m in metric_names:
        if m not in df.columns:
            continue
        v1 = df.loc[player_id_1, m] if player_id_1 in df.index else None
        v2 = df.loc[player_id_2, m] if player_id_2 in df.index else None
        # Convert NaN to None for JSON-friendliness
        v1 = float(v1) if (v1 is not None and v1 == v1) else None  # type: ignore[assignment]
        v2 = float(v2) if (v2 is not None and v2 == v2) else None  # type: ignore[assignment]
        result[m] = {player_id_1: v1, player_id_2: v2}  # type: ignore[dict-item]
    return result


def compute_as_dict(
    metric_name: str,
    season: int,
    player_ids: list[str] | None = None,
    use_cache: bool = True,
) -> dict[str, float]:
    """Compute a single metric, return as {player_id: value} dict.

    Convenience for API layer: no pandas objects leak to Layer 3.
    NaN values are skipped (not included in the returned dict).
    """
    series = compute(metric_name, season, player_ids, use_cache=use_cache)
    return {
        str(pid): float(v)
        for pid, v in series.items()
        if v == v  # skip NaN
    }


def compute_many_as_dict(
    metric_names: list[str],
    season: int,
    player_ids: list[str] | None = None,
    use_cache: bool = True,
) -> dict[str, dict[str, float]]:
    """Compute multiple metrics, return as {player_id: {metric: value}} dict.

    Convenience for API layer: no pandas objects leak to Layer 3.
    NaN values are skipped per (player, metric).
    """
    df = compute_many(metric_names, season, player_ids=player_ids, use_cache=use_cache)
    result: dict[str, dict[str, float]] = {}
    for pid in df.index:
        row = df.loc[pid]
        pid_str = str(pid)
        result[pid_str] = {}
        for m in metric_names:
            if m not in row:
                continue
            v = row[m]
            if v == v and v is not None:  # skip NaN
                result[pid_str][m] = float(v)
    return result
