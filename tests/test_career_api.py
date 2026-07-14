"""NBACore v8.2-C — Career API integration + §6 layer-isolation tests.

Covers the three /api/career endpoints:
    - envelope shape {code, data, message}
    - validation (422 on whitelist / required-arg violations)
    - real integration against live data (skipped if PostgreSQL unavailable)
    - Layer Isolation (no SQL strings / no pandas-numpy / no eval-exec / <200 lines)
      for the career router specifically.

v8 §6: DB-dependent tests use a live connection (skipped if unavailable).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

try:
    from backend.core.db import ping as _db_ping

    _DB_AVAILABLE = bool(_db_ping())
except Exception:
    _DB_AVAILABLE = False

needs_db = pytest.mark.skipif(not _DB_AVAILABLE, reason="needs live PostgreSQL")


# ── Envelope / validation ──
class TestCareerEnvelope:
    def test_peak_envelope_shape(self, app_client):
        resp = app_client.get("/api/career/peak?metric=pts_per_game&limit=1")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"code", "data", "message"}
        assert body["code"] == 0
        assert isinstance(body["data"], list)

    def test_peak_invalid_metric_422(self, app_client):
        resp = app_client.get("/api/career/peak?metric=bogus")
        assert resp.status_code == 422

    def test_age_curve_missing_ids_422(self, app_client):
        resp = app_client.get("/api/career/age-curve")
        assert resp.status_code == 422

    def test_similar_missing_player_422(self, app_client):
        resp = app_client.get("/api/career/similar-evolution")
        assert resp.status_code == 422

    def test_similar_invalid_algorithm_422(self, app_client):
        resp = app_client.get("/api/career/similar-evolution?player_id=x&algorithm=bogus")
        assert resp.status_code == 422


# ── Real integration (needs DB) ──
@needs_db
class TestCareerIntegration:
    def _find_player(self, app_client, name):
        s = app_client.get(f"/players?name={name}&limit=1").json()
        if not s.get("players"):
            return None
        return s["players"][0]["player_id"]

    def test_peak_real_descending(self, app_client):
        resp = app_client.get("/api/career/peak?metric=pts_per_game&limit=5")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert 1 <= len(data) <= 5
        assert data[0]["rank"] == 1
        vals = [d["peak_value"] for d in data]
        assert all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1))
        # fields present
        for d in data:
            assert d["player_id"] and d["peak_value"] is not None

    def test_age_curve_real_sorted(self, app_client):
        pid = self._find_player(app_client, "lebron")
        if not pid:
            pytest.skip("no lebron in DB")
        resp = app_client.get(f"/api/career/age-curve?player_ids={pid}&metric=per")
        assert resp.status_code == 200
        players = resp.json()["data"]["players"]
        assert players and players[0]["curve"]
        ages = [c["age"] for c in players[0]["curve"]]
        assert ages == sorted(ages)

    def test_age_curve_multi_player(self, app_client):
        p1 = self._find_player(app_client, "lebron")
        p2 = self._find_player(app_client, "durant")
        if not (p1 and p2):
            pytest.skip("missing player")
        resp = app_client.get(
            f"/api/career/age-curve?player_ids={p1},{p2}&metric=per"
        )
        assert resp.status_code == 200
        players = resp.json()["data"]["players"]
        assert len(players) == 2

    def test_similar_real(self, app_client):
        pid = self._find_player(app_client, "lebron")
        if not pid:
            pytest.skip("no lebron in DB")
        resp = app_client.get(
            f"/api/career/similar-evolution?player_id={pid}&metric=per&top_k=3"
        )
        assert resp.status_code == 200
        d = resp.json()["data"]
        assert d["target"]["player_id"] == pid
        assert len(d["similar"]) <= 3
        sims = [c["similarity"] for c in d["similar"]]
        assert sims == sorted(sims, reverse=True)
        assert pid not in [c["player_id"] for c in d["similar"]]

    def test_similar_cosine_and_euclidean(self, app_client):
        pid = self._find_player(app_client, "lebron")
        if not pid:
            pytest.skip("no lebron in DB")
        for algo in ("cosine", "euclidean"):
            resp = app_client.get(
                f"/api/career/similar-evolution?player_id={pid}&metric=per&top_k=2&algorithm={algo}"
            )
            assert resp.status_code == 200
            sims = [c["similarity"] for c in resp.json()["data"]["similar"]]
            assert all(0.0 <= s <= 1.0 for s in sims)


# ── §6 Layer Isolation (career router) ──
class TestCareerLayerIsolation:
    """v8 §6: career router must not contain SQL / pandas / numpy / eval / exec
    and must stay under 200 lines (pure orchestration)."""

    def _src(self) -> str:
        p = (
            Path(__file__).resolve().parent.parent
            / "backend" / "api" / "routers" / "career.py"
        )
        return p.read_text(encoding="utf-8")

    def test_no_sql_strings(self):
        upper = self._src().upper()
        for kw in ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE"):
            assert kw not in upper, f"career.py contains SQL keyword {kw!r}"

    def test_no_pandas_numpy_import(self):
        tree = ast.parse(self._src())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in ("pandas", "numpy")
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in ("pandas", "numpy")

    def test_no_eval_exec(self):
        tree = ast.parse(self._src())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("eval", "exec")

    def test_under_200_lines(self):
        lines = self._src().splitlines()
        assert len(lines) < 200, f"career.py is {len(lines)} lines (expected < 200)"
