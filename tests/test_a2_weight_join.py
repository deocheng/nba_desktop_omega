"""A2 — weight JOIN-at-read helper + consumers (v8 §6 parameterized)."""
from __future__ import annotations

import pytest
from psycopg2 import sql as psql

from backend.data_layer.joins import (
    join_player_weight,
    load_player_gamelog_with_game_context,
    load_player_season_stats_with_bio,
    select_weight_cols,
)
from backend.data_layer import batch_loader


def test_join_player_weight_rejects_unknown_key():
    with pytest.raises(ValueError):
        join_player_weight("not_a_key")


def test_join_player_weight_returns_composed_with_dim_players(db_available):
    """The helper must yield a Composed LEFT JOIN onto dim_players (alias p_w).

    psycopg2 requires a real cursor/connection to *render* Identifier quotes,
    so we render against a live connection (skipped when no DB is available).
    """
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    import psycopg2
    from backend.core import config

    frag = join_player_weight("player_id")
    assert isinstance(frag, psql.Composed)
    with psycopg2.connect(**config.DB_CONFIG) as conn:
        rendered = frag.as_string(conn.cursor())
    assert "dim_players" in rendered
    assert "p_w" in rendered
    # §6 red line: identifier is quoted, not string-concatenated raw
    assert "LEFT JOIN dim_players p_w" in rendered


def test_select_weight_cols_aliased(db_available):
    """select_weight_cols must surface weight_lbs / weight_kg via alias p_w."""
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    import psycopg2
    from backend.core import config

    frag = select_weight_cols("p_w")
    assert isinstance(frag, psql.Composed)
    with psycopg2.connect(**config.DB_CONFIG) as conn:
        rendered = frag.as_string(conn.cursor())
    assert "weight_lbs" in rendered and "weight_kg" in rendered


@pytest.mark.needs_db
def test_season_stats_with_bio_exposes_weight_kg(db_available):
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    seasons = batch_loader.load_seasons_available("fact_player_season_stats")
    assert seasons, "no seasons available"
    season = seasons[0]
    rows = load_player_season_stats_with_bio(season)
    assert rows, f"no rows for season {season}"
    assert "weight_kg" in rows[0], "weight_kg missing from season-stats+bio"
    assert any(r.get("weight_kg") is not None for r in rows), "weight_kg all null"


@pytest.mark.needs_db
def test_gamelog_context_exposes_weight(db_available):
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    # A player we know has gamelog rows (LeBron). Pick any season he played.
    try:
        from backend.data_layer.entity_loader import load_player_seasons
        seasons = load_player_seasons("jamesle01")
    except Exception:
        seasons = []
    if not seasons:
        pytest.skip("jamesle01 has no local gamelog seasons")
    season = seasons[0]
    rows = load_player_gamelog_with_game_context(season, "jamesle01")
    assert rows, f"no gamelog rows for jamesle01 s{season}"
    assert "weight_lbs" in rows[0], "weight_lbs missing from gamelog context"
