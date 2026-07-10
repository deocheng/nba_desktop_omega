"""NBACore v8 §2 Layer 2 — Metric Engine Batch Loader.

Thin wrapper that pulls data from Layer 1 (data_layer) based on a MetricSpec.
This is the ONLY module in Layer 2 that talks to Layer 1.

v8 §2 mandates:
    - All data fetches go through data_layer (no direct SQL in metric_engine)
    - season filter is mandatory (enforced by data_layer)
    - player filtering uses IN-clause or temp table (decided by data_layer)
"""
from __future__ import annotations

import logging

from backend.data_layer import (
    load_player_gamelog,
    load_player_gamelog_by_ids,
    load_player_season_stats,
    load_player_team_share,
    load_players,
    load_seasons_available,
    search_players,
    should_use_temp_table,
)
from backend.services.metric_engine.registry import MetricSpec

logger = logging.getLogger("nbacore.metric.loader")


# Map source_table → data_layer loader function + player_col
_SOURCE_TABLE_LOADERS = {
    "fact_player_season_stats": {
        "all": load_player_season_stats,
        "by_ids": None,  # no dedicated by_ids loader; load all + filter in-process
        "player_col": "player_id",
    },
    "player_team_share": {
        "all": load_player_team_share,         # v8.1 §8 — player+team joined season stats
        "by_ids": None,  # load all + filter in-process (small player sets)
        "player_col": "player_id",
    },
    "player_gamelog": {
        "all": load_player_gamelog,           # supports optional player_ids (IN-clause)
        "by_ids": load_player_gamelog_by_ids,  # temp table for large batches
        "player_col": "br_player_id",
    },
}


def load_metric_input(
    spec: MetricSpec,
    season: int,
    player_ids: list[str] | None = None,
) -> tuple[list[dict], str]:
    """Load raw rows for a metric from Layer 1.

    Args:
        spec: MetricSpec (provides source_table)
        season: required NBA season
        player_ids: optional BBR ID filter; None = all players that season

    Returns:
        (rows, player_col) — player_col is the column name to use as index.

    Raises:
        ValueError: if source_table is not registered with a loader.
    """
    if spec.source_table not in _SOURCE_TABLE_LOADERS:
        raise ValueError(
            f"source_table {spec.source_table!r} has no Layer 1 loader mapped. "
            f"Available: {sorted(_SOURCE_TABLE_LOADERS)}"
        )

    cfg = _SOURCE_TABLE_LOADERS[spec.source_table]
    player_col = cfg["player_col"]

    if player_ids:
        by_ids_fn = cfg["by_ids"]
        if by_ids_fn is None:
            # fact_player_season_stats: ~600 rows/season, just load all + filter in-process
            rows = cfg["all"](season)
            id_set = set(player_ids)
            rows = [r for r in rows if r.get(player_col) in id_set]
            logger.info(
                "metric input | spec=%s | season=%d | filter_in_proc | rows=%d",
                spec.name, season, len(rows),
            )
        else:
            # player_gamelog: large table, use IN-clause for small batches, temp table for large
            if should_use_temp_table(player_ids):
                rows = by_ids_fn(season, player_ids)
                logger.info(
                    "metric input | spec=%s | season=%d | temp_table | ids=%d | rows=%d",
                    spec.name, season, len(player_ids), len(rows),
                )
            else:
                # IN-clause via the all-loader's optional player_ids param
                rows = cfg["all"](season, player_ids=player_ids)
                logger.info(
                    "metric input | spec=%s | season=%d | in_clause | ids=%d | rows=%d",
                    spec.name, season, len(player_ids), len(rows),
                )
    else:
        rows = cfg["all"](season)
        logger.info(
            "metric input | spec=%s | season=%d | all_players | rows=%d",
            spec.name, season, len(rows),
        )

    return rows, player_col


def available_source_tables() -> list[str]:
    """List source tables that have Layer 1 loaders mapped."""
    return sorted(_SOURCE_TABLE_LOADERS)


# ── Player bio / search wrappers (for Phase 3 API layer) ──
# API layer must NOT import data_layer directly — it goes through metric_engine.
# These wrappers keep the v8 §2 layer isolation: API → metric_engine → data_layer → db.

def get_player_bios(player_ids: list[str]) -> list[dict]:
    """Fetch dim_players rows for a list of BBR player_ids.

    Args:
        player_ids: list of BBR IDs (e.g. ['gilgesh01', 'antetgi01'])

    Returns: list[dict] with dim_players columns (player_name, position, etc.)
    """
    if not player_ids:
        return []
    return load_players(player_ids)


def search_players_by_name(name: str, limit: int = 20) -> list[dict]:
    """Search dim_players by name (case-insensitive ILIKE).

    Args:
        name: search string (>= 2 chars)
        limit: max results (1-100, default 20)

    Returns: list[dict] with dim_players columns.
    """
    return search_players(name, limit=limit)


def get_available_seasons(table_name: str = "fact_player_season_stats") -> list[int]:
    """Return distinct seasons available in a table (descending).

    Thin wrapper around data_layer.load_seasons_available to maintain
    v8 §2 layer isolation (API → metric_engine → data_layer).

    Args:
        table_name: table to query (default: fact_player_season_stats)

    Returns: list of season integers, sorted descending.
    """
    return load_seasons_available(table_name)
