"""NBACore v8 §3 Phase 7 — Testing & Monitoring.

Covers:
- Context Engine (Phase 5): similar players, role evolution, trend analysis
- Export Service (Phase 6): JSON/CSV exports, determinism
- Monitor (Phase 7): stats endpoint
- Benchmark script: importable without side effects
"""
from __future__ import annotations

import hashlib

import pytest


# ── §1 Phase 5: Context Engine ──

@pytest.mark.usefixtures("db_available")
class TestContextEngine:
    """Context engine: similarity + evolution + trend."""

    def test_similar_players_basic(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/context/similar?player_id=jamesle01&season=2025&limit=5"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["target_player_id"] == "jamesle01"
        assert body["season"] == 2025
        assert len(body["similar_players"]) <= 5
        for p in body["similar_players"]:
            assert "player_id" in p
            assert "similarity" in p
            assert -1.0 <= p["similarity"] <= 1.0

    def test_similar_players_excludes_self(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/context/similar?player_id=jamesle01&season=2025&limit=50"
        )
        assert resp.status_code == 200
        body = resp.json()
        ids = [p["player_id"] for p in body["similar_players"]]
        assert "jamesle01" not in ids

    def test_similar_players_sorted_descending(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/context/similar?player_id=jamesle01&season=2025&limit=20"
        )
        assert resp.status_code == 200
        body = resp.json()
        sims = [p["similarity"] for p in body["similar_players"]]
        assert sims == sorted(sims, reverse=True)

    def test_similar_players_invalid_metric_404(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/context/similar?player_id=jamesle01&season=2025&metrics=fake_metric"
        )
        assert resp.status_code == 404

    def test_role_evolution_basic(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/context/evolution?player_id=jamesle01&seasons=2023,2024,2025"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["player_id"] == "jamesle01"
        assert len(body["seasons"]) == 3
        assert len(body["metric_changes"]) > 0
        for mc in body["metric_changes"]:
            assert "metric" in mc
            assert "direction" in mc

    def test_trend_analysis_basic(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/context/trend?player_id=jamesle01&metric=pts_per_game&seasons=2022,2023,2024,2025"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["player_id"] == "jamesle01"
        assert body["metric"] == "pts_per_game"
        assert "slope" in body
        assert "intercept" in body
        assert "r_squared" in body
        assert 0.0 <= body["r_squared"] <= 1.0

    def test_trend_invalid_metric_404(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/context/trend?player_id=jamesle01&metric=fake_metric&seasons=2023,2024"
        )
        assert resp.status_code == 404


# ── §2 Phase 6: Export Service ──

@pytest.mark.usefixtures("db_available")
class TestExportService:
    """Export endpoints: JSON + CSV."""

    def test_export_rankings_json(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/export/rankings?metric=pts_per_game&season=2025&format=json&limit=10"
        )
        assert resp.status_code == 200
        assert "json" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]
        data = resp.json()
        assert data["export_type"] == "rankings"
        assert data["metric"] == "pts_per_game"
        assert data["season"] == 2025
        assert len(data["rankings"]) <= 10

    def test_export_rankings_csv(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/export/rankings?metric=ast_per_game&season=2025&format=csv&limit=10"
        )
        assert resp.status_code == 200
        assert "csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]
        lines = resp.text.strip().split("\n")
        assert lines[0].startswith("rank,player_id")
        assert len(lines) == 11

    def test_export_rankings_invalid_metric_404(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/export/rankings?metric=fake_metric&season=2025"
        )
        assert resp.status_code == 404

    def test_export_vs_json(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/export/vs?p1=jamesle01&p2=antetgi01&season=2025&format=json"
            "&metrics=pts_per_game,reb_per_game"
        )
        assert resp.status_code == 200
        assert "json" in resp.headers["content-type"]
        data = resp.json()
        assert data["export_type"] == "vs_comparison"
        assert data["player_1"] == "jamesle01"
        assert data["player_2"] == "antetgi01"
        assert len(data["metrics"]) == 2
        assert "pts_per_game" in data["results"]

    def test_export_vs_csv(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/export/vs?p1=jamesle01&p2=antetgi01&season=2025&format=csv"
            "&metrics=pts_per_game,reb_per_game,ast_per_game"
        )
        assert resp.status_code == 200
        assert "csv" in resp.headers["content-type"]
        lines = resp.text.strip().split("\n")
        assert lines[0].startswith("metric,")
        assert "jamesle01" in lines[0]
        assert "antetgi01" in lines[0]
        assert len(lines) == 4

    def test_export_vs_invalid_format_400(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/export/vs?p1=jamesle01&p2=antetgi01&season=2025&format=xml"
        )
        assert resp.status_code == 400

    def test_export_player_json(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get(
            "/export/player?player_id=jamesle01&season=2025&format=json"
            "&metrics=pts_per_game,reb_per_game"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["export_type"] == "player_metrics"
        assert data["player_id"] == "jamesle01"
        assert data["metric_count"] == 2

    def test_export_determinism_rankings_json(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        r1 = app_client.get(
            "/export/rankings?metric=pts_per_game&season=2025&format=json&limit=20"
        )
        r2 = app_client.get(
            "/export/rankings?metric=pts_per_game&season=2025&format=json&limit=20"
        )
        h1 = hashlib.sha256(r1.content).hexdigest()
        h2 = hashlib.sha256(r2.content).hexdigest()
        assert h1 == h2

    def test_export_determinism_rankings_csv(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        r1 = app_client.get(
            "/export/rankings?metric=reb_per_game&season=2025&format=csv&limit=20"
        )
        r2 = app_client.get(
            "/export/rankings?metric=reb_per_game&season=2025&format=csv&limit=20"
        )
        h1 = hashlib.sha256(r1.content).hexdigest()
        h2 = hashlib.sha256(r2.content).hexdigest()
        assert h1 == h2


# ── §3 Phase 7: Monitoring ──

@pytest.mark.usefixtures("db_available")
class TestMonitorEndpoints:
    """Monitoring and stats endpoints."""

    def test_monitor_stats(self, app_client, db_available):
        if not db_available:
            pytest.skip("DB not available")
        resp = app_client.get("/monitor/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "uptime_seconds" in body
        assert "uptime_display" in body
        assert body["database"]["connected"] is True
        assert body["metrics_registered"] > 0
        assert len(body["layers"]) >= 6
        assert "endpoints" in body

    def test_health_endpoint(self, app_client):
        resp = app_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    def test_docs_available(self, app_client):
        resp = app_client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_json(self, app_client):
        resp = app_client.get("/openapi.json")
        assert resp.status_code == 200
        body = resp.json()
        assert "paths" in body
        assert "info" in body


# ── §4 Benchmark Script ──

class TestBenchmarkScript:
    """Benchmark script: importable without side effects."""

    def test_benchmark_module_importable(self):
        import importlib.util
        import sys
        from pathlib import Path

        script_path = Path(__file__).resolve().parent.parent / "scripts" / "benchmark.py"
        spec = importlib.util.spec_from_file_location("benchmark", script_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["benchmark"] = mod
        spec.loader.exec_module(mod)
        assert hasattr(mod, "BenchmarkResult")
        assert hasattr(mod, "run_all_benchmarks")
        assert hasattr(mod, "print_benchmark_report")
