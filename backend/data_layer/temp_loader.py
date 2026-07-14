"""NBACore v8 §2 Layer 1 — Temp Table Batch Loaders.

For large ID lists (>500), IN-clauses become slow and hit parameter limits.
These loaders use batch_query_with_temp_ids() which populates a temp table
and JOINs against it — explicitly allowed by v8 §2 ("使用 IN 或临时表").

Use the IN-clause loaders in batch_loader.py for small lists (<500 IDs).
Use these temp table loaders for large batches (500+ IDs).
"""
from __future__ import annotations

from backend.core.db import batch_query_with_temp_ids, temp_table_name
from backend.data_layer.schema import get_schema

# Threshold: above this many IDs, prefer temp table over IN-clause
TEMP_TABLE_THRESHOLD = 500


def load_player_gamelog_by_ids(
    season: int,
    player_ids: list[str],
) -> list[dict]:
    """Batch load player_gamelog via temp table (for 500+ BBR IDs).

    Equivalent to load_player_gamelog(season, player_ids) but uses a temp
    table JOIN instead of an IN-clause. Same result, better performance
    at scale.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    if not player_ids:
        raise ValueError("player_ids required")

    schema = get_schema("player_gamelog")
    tmp = temp_table_name()
    sql = f"""
        SELECT g.*
        FROM {schema.name} g
        INNER JOIN {tmp} t ON g.{schema.player_col} = t.id
        WHERE g.{schema.season_col} = {season}
    """
    # season is embedded as integer literal (safe — validated above, not string interp)
    return batch_query_with_temp_ids(sql, player_ids, id_type="text")


def load_players_by_ids(player_ids: list[str]) -> list[dict]:
    """Batch load dim_players via temp table (for 500+ BBR IDs)."""
    if not player_ids:
        raise ValueError("player_ids required")
    schema = get_schema("dim_players")
    tmp = temp_table_name()
    sql = f"""
        SELECT p.*
        FROM {schema.name} p
        INNER JOIN {tmp} t ON p.{schema.player_col} = t.id
    """
    return batch_query_with_temp_ids(sql, player_ids, id_type="text")


def should_use_temp_table(player_ids: list) -> bool:
    """Decision helper: True if the ID list is large enough to warrant temp table."""
    return len(player_ids) >= TEMP_TABLE_THRESHOLD
