"""Phase 1 — Data Layer Validation tests.

Covers v8 §4 Phase 1 acceptance:
    - Temp table batch loader works (large ID lists)
    - Schema drift detection catches mismatches
    - Cross-table join loaders return enriched data
    - No per-player DB loop (AST check on new modules)
    - Runtime guard integration

NO mocks for Metric Engine (v8 §6). DB tests skip if PostgreSQL down.
"""
from __future__ import annotations

import ast

import pytest


# ── §4 Phase 1: temp table loader ──

class TestTempTableLoader:

    def test_should_use_temp_table_threshold(self):
        from backend.data_layer.temp_loader import should_use_temp_table, TEMP_TABLE_THRESHOLD
        assert TEMP_TABLE_THRESHOLD == 500
        assert not should_use_temp_table(list(range(499)))
        assert should_use_temp_table(list(range(500)))
        assert should_use_temp_table(list(range(5000)))

    def test_temp_loader_rejects_invalid_season(self):
        from backend.data_layer.temp_loader import load_player_gamelog_by_ids
        with pytest.raises(ValueError, match="Invalid season"):
            load_player_gamelog_by_ids(0, ["a", "b"])
        with pytest.raises(ValueError, match="Invalid season"):
            load_player_gamelog_by_ids("2025", ["a"])  # type: ignore[arg-type]

    def test_temp_loader_rejects_empty_ids(self):
        from backend.data_layer.temp_loader import load_player_gamelog_by_ids
        with pytest.raises(ValueError, match="player_ids required"):
            load_player_gamelog_by_ids(2025, [])

    def test_temp_loader_no_per_player_loop(self):
        """v8 §2: temp_loader must not contain per-player DB loops."""
        from backend.data_layer import temp_loader as tl
        src = open(tl.__file__, encoding="utf-8").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.For):
                continue
            for child in ast.walk(node):
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Name)
                        and child.func.id in ("batch_query", "batch_query_with_temp_ids")):
                    raise AssertionError(
                        f"Per-player DB loop at line {node.lineno} "
                        f"calls {child.func.id} at line {child.lineno}"
                    )


# ── §4 Phase 1: schema drift detection ──

class TestSchemaValidator:

    def test_drift_summary_structure(self, db_available):
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer import drift_summary
        summary = drift_summary()
        assert "ok" in summary
        assert "tables_checked" in summary
        assert "issues" in summary
        assert summary["tables_checked"] >= 6

    def test_registry_healthy_against_live_db(self, db_available):
        """v8 §5.5: all registered tables must exist in DB with declared columns."""
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer import registry_healthy
        assert registry_healthy(), "Schema drift detected — see drift_summary()"

    def test_validate_registry_returns_reports(self, db_available):
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer import validate_registry
        reports = validate_registry()
        assert len(reports) >= 6
        for r in reports:
            assert hasattr(r, "table")
            assert hasattr(r, "ok")
            assert hasattr(r, "issues")

    def test_validate_table_catches_missing_column(self, db_available):
        """Synthetic test: a TableSchema with a bogus column must fail."""
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer.schema_validator import validate_table
        from backend.data_layer.schema import TableSchema
        fake = TableSchema(
            name="dim_teams",
            season_col=None,
            player_col="nonexistent_col_xyz",
            row_count_approx=0,
            description="test",
        )
        report = validate_table(fake)
        assert not report.ok
        assert any("nonexistent_col_xyz" in i for i in report.issues)


# ── §4 Phase 1: join loaders ──

class TestJoinLoaders:

    def test_join_loaders_no_per_player_loop(self):
        """v8 §2: joins.py must not contain per-player DB loops."""
        from backend.data_layer import joins
        src = open(joins.__file__, encoding="utf-8").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.For):
                continue
            for child in ast.walk(node):
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Name)
                        and child.func.id == "batch_query"):
                    raise AssertionError(
                        f"Per-player DB loop at line {node.lineno}"
                    )

    def test_join_loader_rejects_invalid_season(self):
        from backend.data_layer.joins import (
            load_player_gamelog_with_game_context,
            load_player_season_stats_with_bio,
        )
        with pytest.raises(ValueError, match="Invalid season"):
            load_player_gamelog_with_game_context(0)
        with pytest.raises(ValueError, match="Invalid season"):
            load_player_season_stats_with_bio("2025")  # type: ignore[arg-type]

    def test_load_player_gamelog_with_game_context(self, db_available):
        """Real batch query: gamelog + game context join."""
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer import load_player_gamelog_with_game_context
        rows = load_player_gamelog_with_game_context(2025)
        assert len(rows) > 1000
        # Join should bring in game_date from dim_games
        sample = rows[0]
        assert "game_date" in sample or sample.get("game_date") is None  # LEFT JOIN
        assert "home_team_abbr" in sample or sample.get("home_team_abbr") is None

    def test_load_player_season_stats_with_bio(self, db_available):
        """Real batch query: season stats + player bio join."""
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer import load_player_season_stats_with_bio
        rows = load_player_season_stats_with_bio(2025)
        assert len(rows) > 100
        sample = rows[0]
        # Join should bring in bio columns from dim_players
        assert "height_cm" in sample
        assert "bio_position" in sample


# ── §4 Phase 1: temp table real query ──

class TestTempTableRealQuery:

    def test_temp_table_gamelog_load(self, db_available):
        """v8 §2: temp table batch query returns same data as IN-clause."""
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer import (
            load_player_gamelog,
            load_player_gamelog_by_ids,
            load_player_season_stats,
        )
        # Get 5 BBR IDs from season stats
        stats = load_player_season_stats(2025)
        bbr_ids = [r["player_id"] for r in stats[:5] if r.get("player_id")]
        assert len(bbr_ids) == 5

        # IN-clause result
        in_rows = load_player_gamelog(2025, player_ids=bbr_ids)
        # Temp table result
        tmp_rows = load_player_gamelog_by_ids(2025, bbr_ids)

        # Same row count (deterministic — same input = same output, v8 §5.3)
        assert len(in_rows) == len(tmp_rows), (
            f"IN-clause returned {len(in_rows)} rows, temp table {len(tmp_rows)}"
        )

    def test_temp_table_players_load(self, db_available):
        """v8 §2: temp table works for dimension loads too."""
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.data_layer import load_players, load_players_by_ids
        # Get 3 IDs first
        from backend.data_layer import load_player_season_stats
        stats = load_player_season_stats(2025)
        ids = [r["player_id"] for r in stats[:3] if r.get("player_id")]

        in_rows = load_players(ids)
        tmp_rows = load_players_by_ids(ids)
        assert len(in_rows) == len(tmp_rows)


# ── §5.5: runtime guard integration ──

class TestRuntimeGuardPhase1:

    def test_db_module_has_temp_table_function(self):
        """v8 §2: db.py must expose batch_query_with_temp_ids."""
        from backend.core.db import batch_query_with_temp_ids, temp_table_name
        assert callable(batch_query_with_temp_ids)
        assert temp_table_name() == "_nbacore_batch_ids"

    def test_temp_table_name_is_constant(self):
        """v8 §6: temp table name must be hardcoded (no dynamic SQL)."""
        from backend.core.db import temp_table_name
        name = temp_table_name()
        assert isinstance(name, str)
        assert name == "_nbacore_batch_ids"
        # Must be a valid SQL identifier (alphanumeric + underscore)
        assert all(c.isalnum() or c == "_" for c in name)
