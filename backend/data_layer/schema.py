"""NBACore v8 §2 — Schema Registry for Layer 1.

Documents the physical tables the data_layer is allowed to read, their
season column (for mandatory v8 §2 season filter), and the player key
column (for IN-clause batch fetches).

Introspected from PostgreSQL `nba` database on 2026-07-06 (Phase 0.5).
Only key tables for the metric engine are registered here; the full 38-table
catalog lives in the DB and is queryable via information_schema.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableSchema:
    """Schema contract for a Layer 1 accessible table."""
    name: str
    season_col: str | None        # mandatory filter column (None = dimension table)
    player_col: str | None        # BBR player_id column (None = no player dimension)
    row_count_approx: int         # approximate row count at Phase 0.5 introspection
    description: str


# ── Registered Tables (sole source of truth for batch_loader) ──
REGISTRY: dict[str, TableSchema] = {
    "player_gamelog": TableSchema(
        name="player_gamelog",
        season_col="season",
        player_col="br_player_id",   # BBR string ID (96% coverage); player_id is NBA.com numeric (47%)
        row_count_approx=1_912_415,
        description="Player single-game logs (br_player_id is BBR key, 54 cols incl. advanced)",
    ),
    "fact_player_season_stats": TableSchema(
        name="fact_player_season_stats",
        season_col="season",
        player_col="player_id",
        row_count_approx=45_073,
        description="Player season wide table (totals + advanced + per_100, 74 cols)",
    ),
    "fact_team_season_stats": TableSchema(
        name="fact_team_season_stats",
        season_col="season",
        player_col=None,
        row_count_approx=900,
        description="Team season totals",
    ),
    "dim_games": TableSchema(
        name="dim_games",
        season_col="season",
        player_col=None,
        row_count_approx=99_227,
        description="Game dimension (99 cols, season + season_type filter)",
    ),
    "dim_players": TableSchema(
        name="dim_players",
        season_col=None,        # dimension table — no season filter
        player_col="player_id",
        row_count_approx=5_476,
        description="Player bio dimension (24 cols)",
    ),
    "dim_teams": TableSchema(
        name="dim_teams",
        season_col=None,
        player_col=None,
        row_count_approx=30,
        description="Team dimension (6 cols)",
    ),
    "player_season_splits": TableSchema(
        name="player_season_splits",
        season_col="season",
        player_col=None,            # only has player_name (no stable player_id)
        row_count_approx=1_020_609,
        description="Player season split stats (vs team / location / outcome)",
    ),
    "player_shooting": TableSchema(
        name="player_shooting",
        season_col="season",
        player_col="player_id",
        row_count_approx=24_353,
        description="Player shooting breakdowns by distance/zone",
    ),
}


def get_schema(table_name: str) -> TableSchema:
    """Fetch a registered table schema. Raises KeyError if unregistered."""
    if table_name not in REGISTRY:
        raise KeyError(
            f"Table {table_name!r} not in Layer 1 registry. "
            f"Registered: {sorted(REGISTRY)}"
        )
    return REGISTRY[table_name]


def season_required(table_name: str) -> bool:
    """True if the table mandates a season filter (v8 §2)."""
    return get_schema(table_name).season_col is not None
