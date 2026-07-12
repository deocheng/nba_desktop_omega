"""A3 — weight_kg derivation is idempotent and complete (v8 §6 writer)."""
from __future__ import annotations

import pytest

from backend.data_layer import weight_writer

LBS_KG = weight_writer.LBS_TO_KG


def test_conversion_factor():
    # BR lbs->kg factor (rounded to integer kg downstream)
    assert round(200 * LBS_KG) == 91


@pytest.mark.needs_db
def test_derive_weight_kg_idempotent_and_complete(db_available):
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    weight_writer.init_pool()
    try:
        # First run may fill remaining NULLs; second run must be a no-op.
        first = weight_writer.derive_weight_kg("player_weight_history")
        second = weight_writer.derive_weight_kg("player_weight_history")
        assert second == 0, "derive_weight_kg must be idempotent (0 on rerun)"
        cov = weight_writer.weight_coverage("player_weight_history")
        assert cov["with_kg"] == cov["total"], "weight_kg should now cover all rows"
        assert cov["with_lbs"] == cov["total"], "weight_lbs should be complete"
    finally:
        weight_writer.close_pool()


@pytest.mark.needs_db
def test_dim_players_weight_complete(db_available):
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    weight_writer.init_pool()
    try:
        cov = weight_writer.weight_coverage("dim_players")
        # 3 historical NULL weight rows are allowed to stay NULL (no BR page).
        assert cov["with_lbs"] >= cov["total"] - 3
        assert cov["with_kg"] >= cov["total"] - 3
    finally:
        weight_writer.close_pool()
