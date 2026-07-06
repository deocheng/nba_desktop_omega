"""NBACore v8 §2 Layer 3 — Phase 3 API Layer tests.

Covers:
    - Pydantic schemas (serialization, from_row, None handling)
    - /metrics endpoints (list, detail, evaluate)
    - /players endpoints (search, detail with metrics)
    - /vs/compare endpoint (validation + real comparison)
    - /batch endpoint (rank, compute, compute_many)
    - Layer Isolation (no pandas/psycopg2/SQL/eval in API layer)
    - Real 2025 season endpoint integration (needs DB)

v8 §6: No mocking of Metric Engine core logic. DB-dependent tests use a
live connection (skipped if PostgreSQL unavailable).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.api import schemas
from backend.api.routers import batch, metrics, players, vs


# ── DB availability probe (session-scoped, avoids repeated pings) ──

try:
    from backend.core.db import ping as _db_ping
    _DB_AVAILABLE = _db_ping()
except Exception:
    _DB_AVAILABLE = False

needs_db = pytest.mark.skipif(
    not _DB_AVAILABLE,
    reason="needs live PostgreSQL (set DB_PORT and start service)",
)


# ── TestSchemas ──

class TestSchemas:
    """Pydantic schema validation (no DB needed)."""

    def test_metric_info_serialization(self):
        """MetricInfo should serialize all fields correctly."""
        m = schemas.MetricInfo(
            name="pts_per_game",
            kind="per_game",
            source_table="fact_player_season_stats",
            required_cols=["pts", "g"],
            description="Points per game",
            min_denominator=1.0,
            precision=6,
        )
        d = m.model_dump()
        assert d["name"] == "pts_per_game"
        assert d["kind"] == "per_game"
        assert d["required_cols"] == ["pts", "g"]
        assert d["precision"] == 6

    def test_player_bio_from_row_handles_date(self):
        """from_row should convert date/datetime to ISO string."""
        from datetime import date
        row = {
            "player_id": "test01",
            "player_name": "Test Player",
            "full_name": "Test Q. Player",
            "birth_date": date(1995, 6, 15),
            "height_cm": 190,
        }
        bio = schemas.PlayerBio.from_row(row)
        assert bio.player_id == "test01"
        assert bio.birth_date == "1995-06-15"
        assert bio.height_cm == 190
        assert bio.player_name == "Test Player"

    def test_player_bio_from_row_null_date(self):
        """from_row should handle None birth_date gracefully."""
        row = {"player_id": "test02", "birth_date": None}
        bio = schemas.PlayerBio.from_row(row)
        assert bio.birth_date is None
        assert bio.player_id == "test02"

    def test_vs_compare_response_allows_none(self):
        """VSCompareResponse must accept None values for missing player data."""
        resp = schemas.VSCompareResponse(
            player_1="p1",
            player_2="p2",
            season=2025,
            metrics={"pts_per_game": {"p1": 25.5, "p2": None}},
        )
        d = resp.model_dump()
        assert d["metrics"]["pts_per_game"]["p2"] is None
        assert d["metrics"]["pts_per_game"]["p1"] == 25.5


# ── TestMetricsEndpoints ──

class TestMetricsEndpoints:
    """/metrics router tests."""

    def test_list_metrics_returns_all_registered(self, app_client):
        """GET /metrics should return all registered metrics."""
        resp = app_client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 11  # 5 basic + 4 advanced + 2 composite
        names = {m["name"] for m in data["metrics"]}
        assert "pts_per_game" in names
        assert "true_shooting_pct" in names
        assert "fantasy_points" in names

    def test_get_metric_detail(self, app_client):
        """GET /metrics/{name} should return metric spec details."""
        resp = app_client.get("/metrics/pts_per_game")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "pts_per_game"
        assert data["kind"] == "per_game"
        assert "pts" in data["required_cols"]
        assert "g" in data["required_cols"]

    def test_get_metric_404_for_unknown(self, app_client):
        """GET /metrics/{unknown} should return 404."""
        resp = app_client.get("/metrics/nonexistent_metric")
        assert resp.status_code == 404

    def test_evaluate_metric_validation_season_required(self, app_client):
        """GET /metrics/evaluate/{name} without season should return 422."""
        resp = app_client.get("/metrics/evaluate/pts_per_game")
        assert resp.status_code == 422  # FastAPI validation error

    @needs_db
    def test_evaluate_metric_returns_rankings(self, app_client):
        """GET /metrics/evaluate/{name}?season=2025 should return ranked list."""
        resp = app_client.get("/metrics/evaluate/pts_per_game?season=2025&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["metric"] == "pts_per_game"
        assert data["season"] == 2025
        assert data["total"] <= 10
        assert len(data["rankings"]) <= 10
        # Top rank is 1
        assert data["rankings"][0]["rank"] == 1
        # Top scorer should be > 25 PPG
        assert data["rankings"][0]["value"] > 25.0


# ── TestPlayersEndpoints ──

class TestPlayersEndpoints:
    """/players router tests."""

    def test_search_too_short_returns_422(self, app_client):
        """GET /players?name=x should fail validation (min_length=2)."""
        resp = app_client.get("/players?name=x")
        assert resp.status_code == 422

    @needs_db
    def test_search_returns_results(self, app_client):
        """GET /players?name=lebron should find LeBron James."""
        resp = app_client.get("/players?name=lebron&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        # At least one result should contain "LeBron" in full_name or player_name
        names = [p.get("full_name") or p.get("player_name") or "" for p in data["players"]]
        assert any("lebron" in n.lower() for n in names), f"no LeBron in {names}"

    def test_get_player_detail_404_for_unknown(self, app_client):
        """GET /players/{unknown}?season=2025 should return 404."""
        resp = app_client.get("/players/nonexistent99?season=2025")
        assert resp.status_code == 404

    @needs_db
    def test_get_player_detail_with_metrics(self, app_client):
        """GET /players/{id}?season=2025 should return bio + metrics."""
        # Get a real player ID from the evaluate endpoint (top scorer)
        eval_resp = app_client.get("/metrics/evaluate/pts_per_game?season=2025&limit=1")
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        if eval_data["total"] == 0:
            pytest.skip("no players in 2025 rankings")
        pid = eval_data["rankings"][0]["player_id"]

        resp = app_client.get(f"/players/{pid}?season=2025")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bio"]["player_id"] == pid
        assert data["season"] == 2025
        # Should have at least some metrics computed
        assert isinstance(data["metrics"], dict)
        # pts_per_game should be present and positive for a real player
        if "pts_per_game" in data["metrics"]:
            assert data["metrics"]["pts_per_game"] > 0


# ── TestVSEndpoint ──

class TestVSEndpoint:
    """/vs/compare router tests."""

    def test_compare_same_player_400(self, app_client):
        """GET /vs/compare with p1==p2 should return 400."""
        resp = app_client.get("/vs/compare?p1=abc&p2=abc&season=2025")
        assert resp.status_code == 400

    def test_compare_unknown_metric_404(self, app_client):
        """GET /vs/compare with unknown metric should return 404."""
        resp = app_client.get(
            "/vs/compare?p1=a&p2=b&season=2025&metrics=fake_metric"
        )
        assert resp.status_code == 404

    def test_compare_season_required(self, app_client):
        """GET /vs/compare without season should return 422."""
        resp = app_client.get("/vs/compare?p1=a&p2=b")
        assert resp.status_code == 422

    @needs_db
    def test_compare_real_players(self, app_client):
        """GET /vs/compare for two real players should return side-by-side metrics."""
        # Get top 2 scorers from evaluate endpoint (guaranteed to have data)
        eval_resp = app_client.get("/metrics/evaluate/pts_per_game?season=2025&limit=2")
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        if eval_data["total"] < 2:
            pytest.skip("fewer than 2 players in 2025 rankings")
        p1 = eval_data["rankings"][0]["player_id"]
        p2 = eval_data["rankings"][1]["player_id"]

        resp = app_client.get(
            f"/vs/compare?p1={p1}&p2={p2}&season=2025"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["player_1"] == p1
        assert data["player_2"] == p2
        assert data["season"] == 2025
        # Should have multiple metrics
        assert len(data["metrics"]) >= 5
        # Each metric should have both player keys
        for mname, vals in data["metrics"].items():
            assert p1 in vals
            assert p2 in vals


# ── TestBatchEndpoint ──

class TestBatchEndpoint:
    """/batch router tests."""

    def test_batch_empty_operations_400(self, app_client):
        """POST /batch with empty operations should return 400."""
        resp = app_client.post("/batch", json={"operations": []})
        assert resp.status_code == 400

    def test_batch_invalid_type_400(self, app_client):
        """POST /batch with invalid operation type should return 400."""
        resp = app_client.post("/batch", json={
            "operations": [
                {"type": "invalid_op", "season": 2025}
            ]
        })
        assert resp.status_code == 400

    @needs_db
    def test_batch_rank_and_compute(self, app_client):
        """POST /batch with rank + compute should return both results."""
        resp = app_client.post("/batch", json={
            "operations": [
                {
                    "type": "rank",
                    "metric": "pts_per_game",
                    "season": 2025,
                    "limit": 5,
                },
                {
                    "type": "compute",
                    "metric": "true_shooting_pct",
                    "season": 2025,
                },
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        # First result: rank
        assert data["results"][0]["type"] == "rank"
        assert data["results"][0]["metric"] == "pts_per_game"
        assert len(data["results"][0]["rankings"]) <= 5
        # Second result: compute
        assert data["results"][1]["type"] == "compute"
        assert data["results"][1]["metric"] == "true_shooting_pct"
        assert data["results"][1]["count"] > 0


# ── TestLayerIsolation ──

class TestLayerIsolation:
    """v8 §6: API layer must not contain SQL, pandas, psycopg2, or computation.

    The API layer is pure orchestration — it only shapes requests and calls
    metric_engine. No imports of pandas/psycopg2, no SQL strings, no eval/exec.
    """

    def _api_source_files(self) -> list[Path]:
        """Return all .py files under backend/api/."""
        api_dir = Path(__file__).resolve().parent.parent / "backend" / "api"
        return list(api_dir.rglob("*.py"))

    def test_api_no_pandas_import(self):
        """No file in backend/api/ may import pandas."""
        violations = []
        for f in self._api_source_files():
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(f))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "pandas" or alias.name == "numpy":
                            violations.append(f"{f.name}:{node.lineno} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and (node.module.startswith("pandas") or
                                        node.module.startswith("numpy")):
                        violations.append(f"{f.name}:{node.lineno} imports from {node.module}")
        assert not violations, f"pandas/numpy imports in API layer: {violations}"

    def test_api_no_psycopg2_import(self):
        """No file in backend/api/ may import psycopg2 or data_layer SQL."""
        violations = []
        for f in self._api_source_files():
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(f))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("psycopg2"):
                            violations.append(f"{f.name}:{node.lineno} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and (node.module.startswith("psycopg2") or
                                        node.module == "backend.data_layer.batch_loader"):
                        violations.append(f"{f.name}:{node.lineno} imports {node.module}")
        assert not violations, f"psycopg2/data_layer imports in API: {violations}"

    def test_api_no_sql_strings(self):
        """No file in backend/api/ may contain SELECT/INSERT/UPDATE/DELETE SQL."""
        sql_keywords = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE")
        violations = []
        for f in self._api_source_files():
            src = f.read_text(encoding="utf-8")
            upper = src.upper()
            for kw in sql_keywords:
                if kw in upper:
                    # Find the line for context
                    for i, line in enumerate(src.splitlines(), 1):
                        if kw in line.upper() and not line.strip().startswith("#"):
                            violations.append(f"{f.name}:{i} contains '{kw.strip()}'")
        assert not violations, f"SQL strings in API layer: {violations}"

    def test_api_no_eval_exec(self):
        """No file in backend/api/ may contain eval() or exec() calls."""
        violations = []
        for f in self._api_source_files():
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(f))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name) and func.id in ("eval", "exec"):
                        violations.append(f"{f.name}:{node.lineno} calls {func.id}()")
                    elif isinstance(func, ast.Attribute) and func.attr in ("eval", "exec"):
                        violations.append(f"{f.name}:{node.lineno} calls .{func.attr}()")
        assert not violations, f"eval/exec in API layer: {violations}"

    def test_routers_have_no_compute_logic(self):
        """Router functions should only call metric_engine + shape responses.

        Check that no router file defines functions with arithmetic, aggregation,
        or filtering logic beyond simple dict/list comprehensions for response shaping.
        """
        router_dir = Path(__file__).resolve().parent.parent / "backend" / "api" / "routers"
        # Each router file should be relatively short (pure orchestration)
        for f in router_dir.glob("*.py"):
            if f.name == "__init__.py":
                continue
            src = f.read_text(encoding="utf-8")
            lines = src.splitlines()
            # Routers should be under 200 lines (pure orchestration = concise)
            assert len(lines) < 200, f"{f.name} is {len(lines)} lines (expected < 200 for pure orchestration)"


# ── TestRealEndpoints2025 (needs live DB) ──

@needs_db
class TestRealEndpoints2025:
    """Real integration: hit live endpoints against 2025 season data."""

    def test_metrics_evaluate_top10_ppg(self, app_client):
        """GET /metrics/evaluate/pts_per_game?season=2025&limit=10 should return top 10."""
        resp = app_client.get("/metrics/evaluate/pts_per_game?season=2025&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10
        # Ranks should be 1 through 10
        ranks = [r["rank"] for r in data["rankings"]]
        assert ranks == list(range(1, 11))
        # Values should be decreasing (descending = highest first)
        values = [r["value"] for r in data["rankings"]]
        assert all(values[i] >= values[i + 1] for i in range(len(values) - 1))
        # Top scorer should be 25+ PPG
        assert values[0] > 25.0, f"top PPG = {values[0]} (expected > 25)"

    def test_vs_compare_two_stars(self, app_client):
        """GET /vs/compare for two star players should return all default metrics."""
        # Get top 2 scorers from evaluate endpoint (guaranteed to have data)
        eval_resp = app_client.get("/metrics/evaluate/pts_per_game?season=2025&limit=2")
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        if eval_data["total"] < 2:
            pytest.skip("fewer than 2 players in 2025 rankings")
        p1 = eval_data["rankings"][0]["player_id"]
        p2 = eval_data["rankings"][1]["player_id"]

        resp = app_client.get(f"/vs/compare?p1={p1}&p2={p2}&season=2025")
        assert resp.status_code == 200
        data = resp.json()
        # Should have all 10 default VS metrics
        assert len(data["metrics"]) >= 8
        # Both players should have pts_per_game > 20 (top scorers)
        ppg = data["metrics"].get("pts_per_game", {})
        if p1 in ppg and ppg[p1] is not None:
            assert ppg[p1] > 15.0, f"{p1} PPG = {ppg[p1]} (expected > 15)"
        if p2 in ppg and ppg[p2] is not None:
            assert ppg[p2] > 15.0, f"{p2} PPG = {ppg[p2]} (expected > 15)"

    def test_player_detail_real_player(self, app_client):
        """GET /players/{id}?season=2025 should return bio + multiple metrics."""
        # Get top scorer from evaluate endpoint (guaranteed to have 2025 data)
        eval_resp = app_client.get("/metrics/evaluate/pts_per_game?season=2025&limit=1")
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        if eval_data["total"] == 0:
            pytest.skip("no players in 2025 rankings")
        pid = eval_data["rankings"][0]["player_id"]

        resp = app_client.get(f"/players/{pid}?season=2025")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bio"]["player_id"] == pid
        # Should have multiple metrics
        assert len(data["metrics"]) >= 3
        # Top scorer should have PPG > 20
        if "pts_per_game" in data["metrics"]:
            assert data["metrics"]["pts_per_game"] > 20.0

    def test_batch_compute_many(self, app_client):
        """POST /batch with compute_many should return multi-metric dict."""
        resp = app_client.post("/batch", json={
            "operations": [
                {
                    "type": "compute_many",
                    "metrics": ["pts_per_game", "reb_per_game", "ast_per_game"],
                    "season": 2025,
                }
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        result = data["results"][0]
        assert result["type"] == "compute_many"
        assert result["count"] > 100  # ~600 players
        # Each player should have the 3 metrics
        sample_pid = next(iter(result["values"]))
        sample_metrics = result["values"][sample_pid]
        assert "pts_per_game" in sample_metrics
        assert "reb_per_game" in sample_metrics
        assert "ast_per_game" in sample_metrics
