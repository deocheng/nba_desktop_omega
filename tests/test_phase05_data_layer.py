"""Phase 0.5 — Data Layer validation tests.

Covers v8 §4 Phase 0.5 acceptance:
    - Schema registry correct (key tables registered)
    - Batch loader enforces season filter (v8 §2)
    - No per-player loop (all fetches are batch via IN-clause)
    - Real batch query succeeds (at least one season loaded)

NO mocks for Metric Engine (v8 §6). DB tests skip if PostgreSQL down.
"""
from __future__ import annotations

import pytest

from backend.data_layer.schema import (
    REGISTRY,
    TableSchema,
    get_schema,
    season_required,
)


# ── §4 Phase 0.5: Schema Registry ──

class TestSchemaRegistry:

    def test_key_tables_registered(self):
        """v8 §4 Phase 0.5: player_gamelog, fact_player_season_stats, dims."""
        required = {
            "player_gamelog",
            "fact_player_season_stats",
            "fact_team_season_stats",
            "dim_games",
            "dim_players",
            "dim_teams",
        }
        assert required.issubset(REGISTRY.keys()), \
            f"Missing: {required - set(REGISTRY.keys())}"

    def test_fact_tables_have_season_col(self):
        """v8 §2: fact tables must declare a season filter column."""
        for name in ("player_gamelog", "fact_player_season_stats", "dim_games"):
            assert season_required(name), f"{name} must require season filter"

    def test_dim_tables_skip_season_filter(self):
        """v8 §2: dimension tables are exempt from season filter."""
        assert not season_required("dim_players")
        assert not season_required("dim_teams")

    def test_player_gamelog_schema_fields(self):
        s = get_schema("player_gamelog")
        assert s.season_col == "season"
        assert s.player_col == "br_player_id"  # BBR string ID (96% coverage)
        assert s.row_count_approx > 1_000_000  # 1.91M at introspection

    def test_get_schema_raises_on_unregistered(self):
        with pytest.raises(KeyError, match="not in Layer 1 registry"):
            get_schema("nonexistent_table")

    def test_table_schema_is_frozen(self):
        """Schema entries must be immutable (frozen dataclass)."""
        s = get_schema("dim_teams")
        with pytest.raises(Exception):
            s.name = "mutated"  # type: ignore[misc]


# ── §2 Layer 1: season filter enforcement ──

class TestSeasonEnforcement:

    def test_assert_season_rejects_non_int(self):
        from backend.data_layer.batch_loader import _assert_season
        with pytest.raises(ValueError, match="Invalid season"):
            _assert_season("player_gamelog", "2025")  # type: ignore[arg-type]

    def test_assert_season_rejects_out_of_range(self):
        from backend.data_layer.batch_loader import _assert_season
        for bad in (0, 1800, 2200):
            with pytest.raises(ValueError, match="Invalid season"):
                _assert_season("player_gamelog", bad)

    def test_assert_season_accepts_valid(self):
        from backend.data_layer.batch_loader import _assert_season
        for good in (2017, 2025, 2026):
            _assert_season("player_gamelog", good)  # no raise

    def test_dim_tables_skip_season_check(self):
        from backend.data_layer.batch_loader import _assert_season
        # dim_players has no season_col → should not raise regardless
        _assert_season("dim_players", 0)


# ── §2 Layer 1: IN-clause batch helper ──

class TestInClause:

    def test_single_value(self):
        from backend.data_layer.batch_loader import _build_in_clause
        clause, params = _build_in_clause(["a"])
        assert clause == "(%s)"
        assert params == ("a",)

    def test_multi_values(self):
        from backend.data_layer.batch_loader import _build_in_clause
        clause, params = _build_in_clause(["a", "b", "c"])
        assert clause == "(%s,%s,%s)"
        assert params == ("a", "b", "c")

    def test_empty_rejected(self):
        from backend.data_layer.batch_loader import _build_in_clause
        with pytest.raises(ValueError, match="at least one value"):
            _build_in_clause([])


# ── §2 Layer 1: no per-player loop (AST check) ──

class TestNoPerPlayerLoop:

    def test_batch_loader_has_no_for_loop_with_db_call(self):
        """v8 §2: data_layer must not contain per-player query loops.

        Uses ast.parse to detect any `for` statement whose body calls
        batch_query (which would mean a per-player DB round-trip).
        """
        import ast
        from backend.data_layer import batch_loader as bl
        src = open(bl.__file__, encoding="utf-8").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.For):
                continue
            # Walk the for-loop body for any batch_query() call
            for child in ast.walk(node):
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Name)
                        and child.func.id == "batch_query"):
                    raise AssertionError(
                        f"Per-player DB loop detected: for-loop at line "
                        f"{node.lineno} calls batch_query at line {child.lineno}"
                    )


# ── §4 Phase 0.5: real batch query (DB required) ──

class TestRealBatchQuery:

    def test_load_seasons_available(self, db_available):
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer import load_seasons_available
        seasons = load_seasons_available()
        assert isinstance(seasons, list)
        assert len(seasons) >= 5
        assert 2025 in seasons or 2026 in seasons

    def test_load_player_season_stats_2025(self, db_available):
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer import load_player_season_stats
        rows = load_player_season_stats(2025)
        assert len(rows) > 100  # ~600 players expected
        assert "player_id" in rows[0]
        assert "pts" in rows[0]

    def test_load_player_gamelog_2025(self, db_available):
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer import load_player_gamelog
        rows = load_player_gamelog(2025)
        assert len(rows) > 1000  # ~93K expected
        assert "player_id" in rows[0]
        assert "season" in rows[0]

    def test_load_player_gamelog_with_player_filter(self, db_available):
        """v8 §2: IN-clause batch filter by br_player_id."""
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer import load_player_gamelog, load_player_season_stats
        # Get BBR player_ids from fact_player_season_stats (guaranteed non-null)
        stats = load_player_season_stats(2025)
        sample_bbr_ids = [r["player_id"] for r in stats[:3] if r.get("player_id")]
        assert len(sample_bbr_ids) == 3, "Need 3 BBR player_ids for filter test"
        # player_gamelog uses br_player_id column for BBR IDs
        filtered = load_player_gamelog(2025, player_ids=sample_bbr_ids)
        assert len(filtered) > 0
        assert all(r["br_player_id"] in sample_bbr_ids for r in filtered)

    def test_load_games_2025(self, db_available):
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer import load_games
        rows = load_games(2025)
        assert len(rows) > 100
        assert "game_id" in rows[0]

    def test_load_players_batch(self, db_available):
        """v8 §2: dimension load via IN-clause (no season)."""
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer import load_players
        # Pull 3 player_ids from season stats first
        from backend.data_layer import load_player_season_stats
        stats = load_player_season_stats(2025)
        ids = [r["player_id"] for r in stats[:3]]
        players = load_players(ids)
        assert len(players) == 3
        assert all("player_id" in p for p in players)
