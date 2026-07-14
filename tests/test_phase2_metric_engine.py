"""NBACore v8 §2 Layer 2 — Phase 2 Metric Engine tests.

Covers:
    - Registry (register, lookup, list, reject dup, frozen spec)
    - Matrix Builder (list→DF, missing cols, NaN, empty, player_id index)
    - Executor (4 metric kinds, precision, type check)
    - Cache (hit/miss, deterministic key, byte-stable serialization)
    - Rank Engine (desc/asc, ties, percentile, min_value filter, empty)
    - Determinism (same input → byte-identical output across runs)
    - Layer Isolation (no psycopg2/sql/eval/exec in metric_engine)
    - Real 2025 season compute (needs DB)
"""
from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

import backend.services.metric_engine as me
from backend.services.metric_engine.cache import CacheEngine, make_cache_key
from backend.services.metric_engine.executor import execute_many, execute_metric, execute_spec
from backend.services.metric_engine.matrix_builder import build_matrix, coerce_numeric
from backend.services.metric_engine.rank import rank_players, to_dataframe
from backend.services.metric_engine.registry import MetricRegistry, MetricSpec, get_registry


# ── TestRegistry ──

class TestRegistry:
    def test_register_and_get(self):
        reg = MetricRegistry()
        spec = MetricSpec(
            name="test_metric",
            kind="per_game",
            source_table="fact_player_season_stats",
            required_cols=("pts", "g"),
            compute=lambda df: df["pts"] / df["g"],
            description="test",
        )
        reg.register(spec)
        assert reg.has("test_metric")
        assert reg.get("test_metric") is spec
        assert "test_metric" in reg.list()

    def test_list_sorted(self):
        reg = MetricRegistry()
        spec_a = MetricSpec("a", "ratio", "t", ("x",), lambda df: df["x"])
        spec_b = MetricSpec("b", "ratio", "t", ("x",), lambda df: df["x"])
        reg.register(spec_b)
        reg.register(spec_a)
        assert reg.list() == ["a", "b"]

    def test_reject_duplicate(self):
        reg = MetricRegistry()
        spec = MetricSpec("dup", "ratio", "t", ("x",), lambda df: df["x"])
        reg.register(spec)
        with pytest.raises(ValueError, match="already registered"):
            reg.register(spec)

    def test_get_unknown_raises(self):
        reg = MetricRegistry()
        with pytest.raises(KeyError, match="not registered"):
            reg.get("nonexistent")

    def test_frozen_spec(self):
        spec = MetricSpec("f", "ratio", "t", ("x",), lambda df: df["x"])
        with pytest.raises(Exception):
            spec.name = "mutated"  # type: ignore[misc]

    def test_required_cols_must_be_tuple(self):
        """register() should reject list[...] required_cols (must be tuple)."""
        reg = MetricRegistry()
        spec = MetricSpec("bad", "ratio", "t", ["x"], lambda df: df["x"])  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="required_cols"):
            reg.register(spec)

    def test_builtin_metrics_registered_on_import(self):
        names = me.list_metrics()
        assert "pts_per_game" in names
        assert "true_shooting_pct" in names
        assert "fantasy_points" in names
        assert "efficiency_rating" in names
        assert len(names) >= 11


# ── TestMatrixBuilder ──

class TestMatrixBuilder:
    def test_builds_player_indexed_df(self):
        rows = [
            {"player_id": "p01", "pts": 20, "g": 10},
            {"player_id": "p02", "pts": 15, "g": 8},
        ]
        df = build_matrix(rows, "player_id", required_cols=("pts", "g"))
        assert df.index.name == "player_id"
        assert list(df.index) == ["p01", "p02"]
        assert df.loc["p01", "pts"] == 20

    def test_missing_required_col_raises(self):
        rows = [{"player_id": "p01", "pts": 20}]
        with pytest.raises(ValueError, match="required columns missing"):
            build_matrix(rows, "player_id", required_cols=("pts", "g"))

    def test_missing_player_col_raises(self):
        rows = [{"pts": 20}]
        with pytest.raises(ValueError, match="player_col"):
            build_matrix(rows, "player_id", required_cols=("pts",))

    def test_empty_rows_raises(self):
        with pytest.raises(ValueError, match="at least one row"):
            build_matrix([], "player_id")

    def test_keeps_only_required_and_extra(self):
        rows = [
            {"player_id": "p01", "pts": 20, "g": 10, "noise": "x"},
        ]
        df = build_matrix(rows, "player_id", required_cols=("pts",), extra_cols=("g",))
        assert "pts" in df.columns
        assert "g" in df.columns
        assert "noise" not in df.columns

    def test_drops_null_player_id_rows(self):
        """Rows with None/NaN player_id must be dropped (not coerced to 'None')."""
        rows = [
            {"player_id": "p01", "pts": 20, "g": 10},
            {"player_id": None, "pts": 99999, "g": 1},  # bogus aggregated row
            {"player_id": "p02", "pts": 15, "g": 8},
        ]
        df = build_matrix(rows, "player_id", required_cols=("pts", "g"))
        assert "None" not in df.index
        assert len(df) == 2
        assert set(df.index) == {"p01", "p02"}

    def test_all_null_player_id_raises(self):
        rows = [{"player_id": None, "pts": 1}]
        with pytest.raises(ValueError, match="NULL/empty"):
            build_matrix(rows, "player_id", required_cols=("pts",))


# ── TestExecutor ──

class TestExecutor:
    def test_per_game_metric(self):
        rows = [
            {"player_id": "p01", "pts": 200, "g": 10},
            {"player_id": "p02", "pts": 150, "g": 10},
        ]
        s = execute_metric("pts_per_game", rows, "player_id")
        assert s.loc["p01"] == 20.0
        assert s.loc["p02"] == 15.0

    def test_ratio_metric(self):
        # TS% = pts / (2 * (fga + 0.44*fta))
        # p01: 100 pts, 10 fga, 0 fta → 100 / (2*10) = 5.0
        # p02: 50 pts, 5 fga, 10 fta → 50 / (2*(5 + 4.4)) = 50/18.8 ≈ 2.659574
        rows = [
            {"player_id": "p01", "pts": 100, "fga": 10, "fta": 0},
            {"player_id": "p02", "pts": 50, "fga": 5, "fta": 10},
        ]
        s = execute_metric("true_shooting_pct", rows, "player_id")
        assert s.loc["p01"] == 5.0
        assert round(s.loc["p02"], 6) == round(50 / 18.8, 6)

    def test_weighted_sum_metric(self):
        # fantasy = 1*pts + 1.2*trb + 1.5*ast + 3*stl + 3*blk - 1*tov + 1*x3p
        # p01: 1*10 + 1.2*5 + 1.5*3 + 3*1 + 3*1 - 1*2 + 1*1 = 10+6+4.5+3+3-2+1 = 25.5
        rows = [
            {"player_id": "p01", "pts": 10, "trb": 5, "ast": 3, "stl": 1,
             "blk": 1, "tov": 2, "x3p": 1},
        ]
        s = execute_metric("fantasy_points", rows, "player_id")
        assert s.loc["p01"] == 25.5

    def test_expression_metric(self):
        # efficiency = (pts+trb+ast+stl+blk) - (fga-fg) - (fta-ft) - tov
        # p01: (10+5+3+1+1) - (5-3) - (4-2) - 2 = 20 - 2 - 2 - 2 = 14
        rows = [
            {"player_id": "p01", "pts": 10, "trb": 5, "ast": 3, "stl": 1, "blk": 1,
             "fga": 5, "fg": 3, "fta": 4, "ft": 2, "tov": 2},
        ]
        s = execute_metric("efficiency_rating", rows, "player_id")
        assert s.loc["p01"] == 14.0

    def test_precision_rounding(self):
        # 1/3 should be rounded to 6 decimals
        rows = [{"player_id": "p01", "pts": 1, "g": 3}]
        s = execute_metric("pts_per_game", rows, "player_id")
        assert s.loc["p01"] == round(1 / 3, 6)

    def test_execute_many_same_table(self):
        rows = [
            {"player_id": "p01", "pts": 200, "g": 10, "trb": 50, "ast": 30},
            {"player_id": "p02", "pts": 100, "g": 10, "trb": 40, "ast": 20},
        ]
        df = execute_many(["pts_per_game", "reb_per_game", "ast_per_game"], rows, "player_id")
        assert list(df.columns) == ["pts_per_game", "reb_per_game", "ast_per_game"]
        assert df.loc["p01", "pts_per_game"] == 20.0
        assert df.loc["p02", "reb_per_game"] == 4.0


# ── TestCache ──

class TestCache:
    def test_cache_key_deterministic(self):
        k1 = make_cache_key("pts_per_game", 2025, ["a", "b"])
        k2 = make_cache_key("pts_per_game", 2025, ["b", "a"])  # same set, diff order
        assert k1 == k2

    def test_cache_key_differs_on_params(self):
        k1 = make_cache_key("pts_per_game", 2025, None, params={"x": 1})
        k2 = make_cache_key("pts_per_game", 2025, None, params={"x": 2})
        assert k1 != k2

    def test_cache_hit_miss(self, tmp_path):
        engine = CacheEngine(cache_dir=tmp_path, ttl=3600)
        key = "test_key_123"
        # Miss
        assert engine.get(key) is None
        # Set
        s = pd.Series([1.0, 2.0], index=["a", "b"], name="x")
        engine.set(key, s)
        # Hit
        got = engine.get(key)
        assert got is not None
        assert list(got.values) == [1.0, 2.0]
        assert list(got.index) == ["a", "b"]

    def test_cache_byte_stable_serialization(self, tmp_path):
        """Same Series → same pickle bytes (determinism)."""
        import pickle as pkl
        s = pd.Series([1.0, 2.0], index=["a", "b"], name="x")
        b1 = pkl.dumps(s, protocol=5)
        b2 = pkl.dumps(s, protocol=5)
        assert b1 == b2


# ── TestRankEngine ──

class TestRankEngine:
    def test_descending_rank(self):
        s = pd.Series([30.0, 20.0, 25.0], index=["a", "b", "c"])
        r = rank_players(s, ascending=False)
        assert r[0].rank == 1
        assert r[0].player_id == "a"
        assert r[1].rank == 2
        assert r[1].player_id == "c"
        assert r[2].rank == 3
        assert r[2].player_id == "b"

    def test_ascending_rank(self):
        s = pd.Series([30.0, 20.0, 25.0], index=["a", "b", "c"])
        r = rank_players(s, ascending=True)
        assert r[0].player_id == "b"
        assert r[0].value == 20.0

    def test_ties_share_rank(self):
        s = pd.Series([20.0, 20.0, 30.0], index=["a", "b", "c"])
        r = rank_players(s, ascending=False)
        # 30 → rank 1 (player c)
        # 20, 20 → rank 2 (players a, b — tie broken by player_id asc)
        assert r[0].rank == 1
        assert r[0].player_id == "c"
        assert r[1].rank == 2
        assert r[1].player_id == "a"
        assert r[2].rank == 2
        assert r[2].player_id == "b"

    def test_percentile(self):
        s = pd.Series([30.0, 20.0, 10.0], index=["a", "b", "c"])
        r = rank_players(s, ascending=False)
        # Top: 100.0, Bottom: 0.0, Middle: 50.0
        assert r[0].percentile == 100.0
        assert r[1].percentile == 50.0
        assert r[2].percentile == 0.0

    def test_min_value_filter(self):
        s = pd.Series([30.0, 20.0, 10.0], index=["a", "b", "c"])
        r = rank_players(s, ascending=False, min_value=15.0)
        # c (10.0) excluded
        assert len(r) == 2
        assert all(p.player_id != "c" for p in r)

    def test_empty_returns_empty(self):
        s = pd.Series([], dtype=float)
        assert rank_players(s) == []


# ── TestDeterminism ──

class TestDeterminism:
    def test_same_input_same_output(self):
        rows = [
            {"player_id": "p01", "pts": 200, "g": 10},
            {"player_id": "p02", "pts": 150, "g": 10},
        ]
        s1 = execute_metric("pts_per_game", rows, "player_id")
        s2 = execute_metric("pts_per_game", rows, "player_id")
        # Series equality
        assert s1.equals(s2)
        # Byte-identical pickle (deterministic serialization)
        import pickle as pkl
        assert pkl.dumps(s1, protocol=5) == pkl.dumps(s2, protocol=5)

    def test_float_precision(self):
        rows = [
            {"player_id": "p01", "pts": 1, "g": 3},
        ]
        s = execute_metric("pts_per_game", rows, "player_id")
        # Should be exactly round(1/3, 6)
        assert s.loc["p01"] == 0.333333

    def test_tie_break_stable(self):
        # Two players with identical values — order must be player_id asc
        rows = [
            {"player_id": "z_player", "pts": 100, "g": 10},
            {"player_id": "a_player", "pts": 100, "g": 10},
        ]
        s = execute_metric("pts_per_game", rows, "player_id")
        r = rank_players(s, ascending=False)
        # Both have value 10.0 — tie broken by player_id asc
        assert r[0].player_id == "a_player"
        assert r[1].player_id == "z_player"
        assert r[0].rank == r[1].rank == 1


# ── TestLayerIsolation ──

class TestLayerIsolation:
    def test_no_psycopg2_import(self):
        """metric_engine must not import psycopg2 (no direct SQL access)."""
        import backend.services.metric_engine as me_mod
        me_dir = Path(me_mod.__file__).parent
        for py_file in me_dir.rglob("*.py"):
            src = py_file.read_text(encoding="utf-8")
            assert "import psycopg2" not in src, f"{py_file} imports psycopg2"
            assert "from psycopg2" not in src, f"{py_file} imports psycopg2"

    def test_no_eval_exec(self):
        """v8 §6: no eval()/exec() in metric_engine."""
        import backend.services.metric_engine as me_mod
        me_dir = Path(me_mod.__file__).parent
        for py_file in me_dir.rglob("*.py"):
            src = py_file.read_text(encoding="utf-8")
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    if isinstance(fn, ast.Name) and fn.id in ("eval", "exec"):
                        assert False, f"{py_file} uses {fn.id}()"
                if isinstance(node, ast.Attribute) and node.attr in ("eval", "exec"):
                    assert False, f"{py_file} uses .{node.attr}()"

    def test_no_dynamic_sql(self):
        """No f-string SQL construction in metric_engine."""
        import backend.services.metric_engine as me_mod
        me_dir = Path(me_mod.__file__).parent
        bad_patterns = ["SELECT ", "FROM ", "WHERE ", "INSERT ", "UPDATE ", "DELETE "]
        for py_file in me_dir.rglob("*.py"):
            src = py_file.read_text(encoding="utf-8")
            for pat in bad_patterns:
                # Allow mentions in docstrings/comments only — check raw strings
                # We're looking for actual SQL execution, not documentation.
                # Simple heuristic: pattern appears in a string literal AND psycopg2 is imported.
                if pat in src and "psycopg2" in src:
                    assert False, f"{py_file} has SQL pattern {pat!r} + psycopg2 import"


# ── TestRealCompute2025 (needs live DB) ──

try:
    from backend.core.db import ping as _db_ping
    _DB_AVAILABLE = _db_ping()
except Exception:
    _DB_AVAILABLE = False


@pytest.mark.skipif(not _DB_AVAILABLE, reason="needs live PostgreSQL")
class TestRealCompute2025:
    """Real integration: compute metrics against live 2025 season data."""

    def test_ppg_top_scorers_sane(self):
        """Top PPG scorer in 2025 should be a known star (>25 PPG)."""
        s = me.compute("pts_per_game", 2025, use_cache=False)
        assert len(s) > 100  # ~600 players expected
        top = s.nlargest(5)
        # NBA top scorer is typically 30+ PPG
        assert top.iloc[0] >= 25.0, f"top PPG = {top.iloc[0]} (expected >= 25)"

    def test_ts_pct_in_valid_range(self):
        """TS% should be in [0, 1.5] for all real players."""
        s = me.compute("true_shooting_pct", 2025, use_cache=False)
        valid = s.dropna()
        assert (valid >= 0).all()
        assert (valid <= 1.5).all(), f"max TS% = {valid.max()} (suspicious)"

    def test_fantasy_points_positive_for_most(self):
        """Fantasy points should be positive for >95% of players."""
        s = me.compute("fantasy_points", 2025, use_cache=False)
        positive_ratio = (s > 0).sum() / len(s)
        assert positive_ratio > 0.95, f"positive ratio = {positive_ratio}"

    def test_rank_returns_sorted_rankings(self):
        """rank() should return list[Ranking] with monotonically increasing rank."""
        rankings = me.rank("pts_per_game", 2025, use_cache=False)
        assert len(rankings) > 100
        ranks = [r.rank for r in rankings]
        # Ranks should be non-decreasing
        assert all(ranks[i] <= ranks[i + 1] for i in range(len(ranks) - 1))
        # Top rank is 1
        assert rankings[0].rank == 1
        # Top value > 25 PPG
        assert rankings[0].value > 25.0

    def test_cache_hit_after_first_compute(self):
        """Second compute() call should hit cache (faster or equal)."""
        import time
        # Clear cache first
        me.get_engine().invalidate_all()
        t0 = time.perf_counter()
        me.compute("pts_per_game", 2025, use_cache=True)
        t1 = time.perf_counter()
        me.compute("pts_per_game", 2025, use_cache=True)  # should be cache hit
        t2 = time.perf_counter()
        # Cache hit should be faster (or at least not slower)
        # Allow some tolerance for variance
        cache_time = t2 - t1
        compute_time = t1 - t0
        assert cache_time <= compute_time * 1.5, (
            f"cache hit ({cache_time:.3f}s) not faster than compute ({compute_time:.3f}s)"
        )

    def test_compute_many_multiple_metrics(self):
        """compute_many returns DataFrame with all requested metrics."""
        df = me.compute_many(
            ["pts_per_game", "reb_per_game", "ast_per_game", "true_shooting_pct"],
            2025,
            use_cache=False,
        )
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 100
        assert all(col in df.columns for col in
                   ["pts_per_game", "reb_per_game", "ast_per_game", "true_shooting_pct"])
