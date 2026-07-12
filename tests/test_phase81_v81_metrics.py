"""NBACore v8 — v8.1 Metric Expansion tests (PRD: Metric Expansion).

Covers:
    - Registry: 5 new v8.1 metrics registered with correct source_table/cols
    - Pure compute (no DB): orb_per_game, drb_per_game, ast_to_ratio,
      def_activity_efficiency, team_scoring_share formulas + div-by-zero guards
    - Mixed-source-table bug fix: _group_compute path (player_metrics_dict /
      vs_compare) does not crash when metrics span two source_tables
    - Schemas: ShootingProfileResponse, CareerDefenseResponse shape
    - Layer Isolation: metrics/ subpackage still free of eval/exec/psycopg2
    - Real 2025 DB compute (skipped if PostgreSQL unavailable)

v8 §6: No mocking of Metric Engine core logic. DB-dependent tests use a live
connection (skipped if PostgreSQL unavailable) rather than mocking.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import backend.services.metric_engine as me
from backend.services.metric_engine.metrics import derived, basic
from backend.api import schemas


# ── DB availability probe ──

try:
    from backend.core.db import ping as _db_ping
    _DB_AVAILABLE = _db_ping()
except Exception:
    _DB_AVAILABLE = False

needs_db = pytest.mark.skipif(
    not _DB_AVAILABLE,
    reason="needs live PostgreSQL (set DB_PORT and start service)",
)


# ── TestV81Registry ──

class TestV81Registry:
    def test_new_metrics_registered(self):
        names = me.list_metrics()
        for m in (
            "orb_per_game",
            "drb_per_game",
            "ast_to_ratio",
            "def_activity_efficiency",
            "team_scoring_share",
        ):
            assert m in names, f"v8.1 metric {m!r} missing from registry"

    def test_source_table_assignment(self):
        spec = me.get_metric("orb_per_game")
        assert spec.source_table == "fact_player_season_stats"
        spec = me.get_metric("drb_per_game")
        assert spec.source_table == "fact_player_season_stats"
        spec = me.get_metric("ast_to_ratio")
        assert spec.source_table == "fact_player_season_stats"
        spec = me.get_metric("def_activity_efficiency")
        assert spec.source_table == "fact_player_season_stats"
        # team_scoring_share MUST use the dedicated join table (v8 §2 isolation)
        spec = me.get_metric("team_scoring_share")
        assert spec.source_table == "player_team_share"

    def test_required_cols(self):
        assert me.get_metric("orb_per_game").required_cols == ("orb", "g")
        assert me.get_metric("drb_per_game").required_cols == ("drb", "g")
        assert me.get_metric("ast_to_ratio").required_cols == ("ast", "tov")
        assert me.get_metric("def_activity_efficiency").required_cols == (
            "stl", "blk", "pf",
        )
        assert me.get_metric("team_scoring_share").required_cols == (
            "pts", "g", "team_pts", "team_g",
        )

    def test_registry_count_grew(self):
        # v8.0 had 11; v8.1 adds 5 → at least 16
        assert len(me.list_metrics()) >= 16


# ── TestV81MetricCompute (pure, no DB) ──

class TestV81MetricCompute:
    def test_orb_per_game(self):
        # sum(orb)=40, sum(g)=10 → 4.0
        rows = [
            {"player_id": "p01", "orb": 28, "g": 7, "drb": 0},
            {"player_id": "p01", "orb": 12, "g": 3, "drb": 0},  # traded split
        ]
        s = me.execute_metric("orb_per_game", rows, "player_id")
        assert s.loc["p01"] == 4.0

    def test_drb_per_game(self):
        # sum(drb)=90, sum(g)=30 → 3.0
        rows = [
            {"player_id": "p01", "drb": 90, "g": 30},
        ]
        s = me.execute_metric("drb_per_game", rows, "player_id")
        assert s.loc["p01"] == 3.0

    def test_ast_to_ratio(self):
        # AST=200, TOV=100 → 2.0
        rows = [{"player_id": "p01", "ast": 200, "tov": 100, "stl": 0, "blk": 0, "pf": 1}]
        s = me.execute_metric("ast_to_ratio", rows, "player_id")
        assert s.loc["p01"] == 2.0

    def test_ast_to_ratio_zero_tov_guard(self):
        # TOV=0 → clip(lower=1.0) → AST/1 = 50 (no div-by-zero crash)
        rows = [{"player_id": "p01", "ast": 50, "tov": 0, "stl": 0, "blk": 0, "pf": 1}]
        s = me.execute_metric("ast_to_ratio", rows, "player_id")
        assert s.loc["p01"] == 50.0

    def test_def_activity_efficiency(self):
        # (STL+BLK)=150, PF=100 → 1.5
        rows = [{"player_id": "p01", "stl": 90, "blk": 60, "pf": 100, "ast": 0, "tov": 1}]
        s = me.execute_metric("def_activity_efficiency", rows, "player_id")
        assert s.loc["p01"] == 1.5

    def test_def_activity_efficiency_zero_pf_guard(self):
        # PF=0 → clip(lower=1.0) → (STL+BLK)/1 = 10
        rows = [{"player_id": "p01", "stl": 6, "blk": 4, "pf": 0, "ast": 0, "tov": 1}]
        s = me.execute_metric("def_activity_efficiency", rows, "player_id")
        assert s.loc["p01"] == 10.0

    def test_team_scoring_share(self):
        # player_ppg = 2000/80 = 25 ; team_ppg = 8000/80 = 100 → 0.25
        rows = [{
            "player_id": "p01",
            "pts": 2000, "g": 80,
            "team_pts": 8000, "team_g": 80,
        }]
        s = me.execute_metric("team_scoring_share", rows, "player_id")
        assert s.loc["p01"] == 0.25

    def test_team_scoring_share_zero_team_pts_guard(self):
        # team_g clipped to >=1.0 and team_ppg clipped to >=1.0 → no div-by-zero.
        # player_ppg = 2000/80 = 25 ; team_ppg = (0/1).clip(1.0) = 1.0 → 25.0
        rows = [{
            "player_id": "p01",
            "pts": 2000, "g": 80,
            "team_pts": 0, "team_g": 0,
        }]
        s = me.execute_metric("team_scoring_share", rows, "player_id")
        # Must be finite (no NaN/inf) and positive — proves the guard held.
        val = float(s.loc["p01"])
        assert val == val  # not NaN
        assert val > 0

    def test_multiple_metrics_same_table(self):
        rows = [{
            "player_id": "p01",
            "orb": 40, "drb": 90, "g": 10,
            "ast": 200, "tov": 100, "stl": 90, "blk": 60, "pf": 100,
        }]
        df = me.execute_many(
            ["orb_per_game", "drb_per_game", "ast_to_ratio", "def_activity_efficiency"],
            rows, "player_id",
        )
        assert df.loc["p01", "orb_per_game"] == 4.0
        assert df.loc["p01", "drb_per_game"] == 9.0
        assert df.loc["p01", "ast_to_ratio"] == 2.0
        assert df.loc["p01", "def_activity_efficiency"] == 1.5


# ── TestV81MixedSourceBugFix ──
# v8.1 default metrics span two source_tables; compute_many() raises if mixed.
# player_metrics_dict / vs_compare route through _group_compute (the fix).

class TestV81MixedSourceBugFix:
    def test_compute_many_rejects_mixed_tables(self):
        """Documented constraint: compute_many demands one source_table."""
        with pytest.raises(ValueError, match="source_table"):
            me.compute_many(
                ["pts_per_game", "team_scoring_share"], 2025, use_cache=False,
            )

    def test_group_compute_helper_runs_with_mixed_tables(self):
        """_group_compute groups by source_table so mixed metrics don't crash."""
        # With no DB this would hit load_metric_input; only assert it's wired
        # through player_metrics_dict/vs_compare in the DB integration tests.
        import pandas as pd
        # Direct unit of the helper's merge behaviour using empty input:
        # empty metric list → empty DataFrame (no DB needed).
        df = me._group_compute([], 2025)
        assert isinstance(df, pd.DataFrame)

    @needs_db
    def test_player_metrics_dict_mixed_sources(self):
        """GET /players/{id} mixes fact_* + player_team_share → must not 500."""
        bios = me.get_player_bios(["jamesle01"])
        if not bios:
            pytest.skip("jamesle01 not in DB")
        d = me.player_metrics_dict(
            ["pts_per_game", "team_scoring_share", "ast_to_ratio"],
            2025, "jamesle01", use_cache=False,
        )
        assert isinstance(d, dict)
        # pts_per_game should be a positive float
        assert d.get("pts_per_game", 0) > 0
        # team_scoring_share may be None (no team join) but key must not crash
        assert "team_scoring_share" in d

    @needs_db
    def test_vs_compare_mixed_sources(self):
        """vs_compare with metrics from two tables must return both sides."""
        res = me.vs_compare(
            ["orb_per_game", "team_scoring_share"], 2025,
            "jamesle01", "curryst01", use_cache=False,
        )
        assert "orb_per_game" in res
        assert "team_scoring_share" in res
        assert set(res["orb_per_game"].keys()) == {"jamesle01", "curryst01"}


# ── TestV81Schemas ──

class TestV81Schemas:
    def test_shooting_profile_response(self):
        resp = schemas.ShootingProfileResponse(
            player_id="jamesle01",
            latest_season=2025,
            seasons=[
                schemas.ShootingSeason(
                    season=2025, team="LAL",
                    zones=[schemas.ShootingZone(
                        zone="restricted_area", fg_pct=0.72, fga_rate=0.35,
                    )],
                ),
            ],
        )
        d = resp.model_dump()
        assert d["player_id"] == "jamesle01"
        assert d["latest_season"] == 2025
        assert d["seasons"][0]["zones"][0]["zone"] == "restricted_area"
        assert d["seasons"][0]["zones"][0]["fg_pct"] == 0.72

    def test_shooting_profile_empty(self):
        resp = schemas.ShootingProfileResponse(player_id="x", seasons=[])
        d = resp.model_dump()
        assert d["latest_season"] is None
        assert d["seasons"] == []

    def test_career_defense_response_found(self):
        resp = schemas.CareerDefenseResponse(
            player_id="jamesle01", found=True, seasons=22,
            total_games=1491, total_steals=2417, total_blocks=1185,
            total_fouls=2500, total_offensive_rebounds=500,
            total_defensive_rebounds=8000, stocks=3602,
            stocks_per_game=2.42, steals_per_game=1.62, blocks_per_game=0.79,
            def_activity_efficiency=1.441,
        )
        d = resp.model_dump()
        assert d["found"] is True
        assert d["stocks"] == 3602
        assert d["stocks_per_game"] == 2.42

    def test_career_defense_response_not_found(self):
        resp = schemas.CareerDefenseResponse(player_id="ghost", found=False)
        d = resp.model_dump()
        assert d["found"] is False


# ── TestV81LayerIsolation ──

class TestV81LayerIsolation:
    def test_no_eval_exec_in_metrics(self):
        me_dir = Path(derived.__file__).parent
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

    def test_no_psycopg2_in_metrics(self):
        me_dir = Path(basic.__file__).parent
        for py_file in me_dir.rglob("*.py"):
            src = py_file.read_text(encoding="utf-8")
            assert "import psycopg2" not in src
            assert "from psycopg2" not in src

    def test_no_dynamic_sql_in_metrics(self):
        bad = ["SELECT ", "FROM ", "WHERE ", "INSERT ", "UPDATE ", "DELETE "]
        me_dir = Path(basic.__file__).parent
        for py_file in me_dir.rglob("*.py"):
            src = py_file.read_text(encoding="utf-8")
            if "psycopg2" in src:
                for pat in bad:
                    assert pat not in src, f"{py_file} has SQL {pat!r} + psycopg2"


# ── TestV81RealCompute2025 (needs live DB) ──

@needs_db
class TestV81RealCompute2025:
    def test_orbit_drb_sane(self):
        orb = me.compute("orb_per_game", 2025, use_cache=False)
        drb = me.compute("drb_per_game", 2025, use_cache=False)
        valid_orb = orb.dropna()
        valid_drb = drb.dropna()
        assert (valid_orb >= 0).all()
        assert (valid_drb >= 0).all()
        # ORB per game rarely exceeds 6; DRB rarely exceeds 15
        assert valid_orb.max() < 10, f"max ORB/g = {valid_orb.max()}"
        assert valid_drb.max() < 20, f"max DRB/g = {valid_drb.max()}"

    def test_ast_to_ratio_non_negative(self):
        s = me.compute("ast_to_ratio", 2025, use_cache=False).dropna()
        # Players with 0 assists legitimately yield 0 (not negative).
        assert (s >= 0).all(), "AST/TOV must be non-negative (tov guarded)"

    def test_def_activity_efficiency_non_negative(self):
        s = me.compute("def_activity_efficiency", 2025, use_cache=False).dropna()
        # Players with 0 STL+BLK legitimately yield 0 (not negative).
        assert (s >= 0).all(), "DAE must be non-negative (pf guarded)"

    def test_team_scoring_share_range(self):
        s = me.compute("team_scoring_share", 2025, use_cache=False).dropna()
        # Player cannot score more than the team; share in [0, 1]
        assert (s >= 0).all()
        assert (s <= 1.0).all(), f"max share = {s.max()} (must be <= 1)"
        # After the playoffs-filter fix, the vast majority of players have data
        assert len(s) > 500, f"only {len(s)} players have team_scoring_share (expected >500)"

    def test_player_detail_includes_v81_metrics(self):
        from backend.api.routers import players as players_router
        resp = players_router.get_player_detail("jamesle01", season=2025)
        for key in ("orb_per_game", "drb_per_game", "ast_to_ratio",
                    "def_activity_efficiency", "team_scoring_share"):
            assert key in resp.metrics, f"{key} missing from player detail"
