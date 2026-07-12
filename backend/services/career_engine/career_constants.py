"""NBACore v8.2-C — Career engine shared constants.

Single source of truth for:
    - table names,
    - the metric whitelist (logical name -> SQL expression + direction + label),
    - the unified age grid used by Similar Evolution resampling,
    - the TOT/2TM/3TM/4TM exclusion set (mirrors growth_loader),
    - default thresholds.

NOTE on metric mapping (verified against ``fact_player_season_stats``):
    ``pts_per_game`` is NOT a physical column in that table — only the season
    total ``pts`` exists. It is derived as ``pts / g`` (``g >= min_games``
    guarantees a non-zero denominator). The other five whitelist metrics
    (``per``, ``ws``, ``vorp``, ``ts_percent``, ``bpm``) are real columns.
"""
from __future__ import annotations

# Layer-1 tables (read-only access only).
FACT_TABLE = "fact_player_season_stats"
PLAYERS_TABLE = "dim_players"

# We only use regular-season rows so a traded player or playoff appearance does
# not create duplicate (player, season) points (mirrors growth_loader's
# ROW_NUMBER() ... ORDER BY g DESC dedup, which always keeps the regular row
# with the most games).
SEASON_TYPE = "Regular"

# Metric whitelist: logical name -> SQL expression / direction / label.
# ``expr`` is injected into the SELECT list; it is safe because the name is
# always validated against this dict before use.
METRIC_WHITELIST: dict[str, dict] = {
    "pts_per_game": {
        "expr": "ROUND((pts::numeric / NULLIF(g, 0))::numeric, 2)",
        "higher_is_better": True,
        "label": "得分/场 PPG",
    },
    "per": {"expr": "per", "higher_is_better": True, "label": "PER"},
    "ws": {"expr": "ws", "higher_is_better": True, "label": "胜利贡献 WS"},
    "vorp": {"expr": "vorp", "higher_is_better": True, "label": "胜利替代值 VORP"},
    "ts_percent": {
        "expr": "ts_percent",
        "higher_is_better": True,
        "label": "真实命中率 TS%",
    },
    "bpm": {"expr": "bpm", "higher_is_better": True, "label": "正负值 BPM"},
}

# Regex pattern for FastAPI / validation (matches exactly one whitelist key).
METRIC_PATTERN = "^(?:" + "|".join(METRIC_WHITELIST.keys()) + ")$"

# Unified age grid used by Similar Evolution resampling (18..42 inclusive).
AGE_GRID = list(range(18, 43))

# Teams excluded from all career aggregates (trade-total / multi-team rows).
EXCLUDED_TEAMS = ("TOT", "2TM", "3TM", "4TM")

# Defaults.
DEFAULT_MIN_GAMES = 20
DEFAULT_AGE_CURVE_MIN_GAMES = 1
DEFAULT_LIMIT = 30
DEFAULT_TOP_K = 5
DEFAULT_MIN_SEASONS = 3
DEFAULT_ALGORITHM = "pearson"

# Allowed similarity algorithms.
ALGORITHMS = ("pearson", "cosine", "euclidean")


def metric_expr(metric: str) -> str:
    """Return the validated SQL expression for a whitelist metric."""
    if metric not in METRIC_WHITELIST:
        raise ValueError(f"metric {metric!r} not in whitelist")
    return METRIC_WHITELIST[metric]["expr"]
