"""NBACore v8.3.2 — Analytics Builder API + workspace flow persistence tests.

Covers:
  - GET  /api/analytics-builder/meta  (envelope + metadata)
  - POST /api/analytics-builder/run   (validation 400, live run 200)
  - Workspace flow CRUD: /api/workspaces/{id}/flows [GET,POST,GET,PUT,DELETE]

v8 §6: DB-dependent tests use a live connection (skipped if unavailable).
"""
from __future__ import annotations

import pytest

try:
    from backend.core.db import ping as _db_ping
    _DB_AVAILABLE = bool(_db_ping())
except Exception:
    _DB_AVAILABLE = False

needs_db = pytest.mark.skipif(not _DB_AVAILABLE, reason="needs live PostgreSQL")


def _sample_flow():
    return {
        "nodes": [
            {"id": "s", "type": "source", "params": {"source_mode": "table", "table": "__AUTO__", "limit": 20}},
            {"id": "v", "type": "visualize", "params": {"viz_type": "table", "title": "t", "x_field": "", "y_fields": []}},
        ],
        "edges": [{"id": "e1", "from": "s", "to": "v"}],
    }


class TestMetaEndpoint:
    def test_meta_envelope(self, app_client):
        resp = app_client.get("/api/analytics-builder/meta")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        for key in ("node_types", "tables", "agg_functions", "viz_types", "filter_ops", "source_modes", "row_limit"):
            assert key in data
        assert "source" in data["node_types"]
        assert "visualize" in data["node_types"]


class TestRunEndpoint:
    def test_cycle_returns_400(self, app_client):
        resp = app_client.post("/api/analytics-builder/run", json={
            "flow": {
                "nodes": [
                    {"id": "a", "type": "transform", "params": {}},
                    {"id": "b", "type": "transform", "params": {}},
                ],
                "edges": [{"id": "e1", "from": "a", "to": "b"}, {"id": "e2", "from": "b", "to": "a"}],
            }
        })
        assert resp.status_code == 400

    def test_visualize_without_upstream_400(self, app_client):
        resp = app_client.post("/api/analytics-builder/run", json={
            "flow": {
                "nodes": [{"id": "v", "type": "visualize",
                           "params": {"viz_type": "table", "y_fields": ["x"]}}],
                "edges": [],
            }
        })
        assert resp.status_code == 400


@needs_db
class TestRunEndpointLive:
    def test_run_real_source(self, app_client):
        from backend.services.analytics_builder_engine import ab_queries as Q
        tables = [t["name"] for t in Q.introspect_tables()]
        assert tables
        flow = _sample_flow()
        flow["nodes"][0]["params"]["table"] = tables[0]
        resp = app_client.post("/api/analytics-builder/run", json={"flow": flow})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["node_status"].get("v") == "ok"
        assert body["data"]["viz_results"]


@needs_db
class TestWorkspaceFlowCRUD:
    def _make_workspace(self, app_client):
        resp = app_client.post("/api/workspaces", json={
            "name": "AB-test-ws", "owner_id": 1, "description": "", "status": "active"
        })
        assert resp.status_code == 201
        return resp.json()["id"]

    def test_flow_create_list_get_update_delete(self, app_client):
        ws_id = self._make_workspace(app_client)
        try:
            # create
            flow = _sample_flow()
            flow["nodes"][0]["params"]["table"] = "fact_player_season"  # may not exist; still stores definition
            resp = app_client.post(f"/api/workspaces/{ws_id}/flows", json={
                "name": "my-flow", "definition": {"version": "1", **flow}
            })
            assert resp.status_code == 201, resp.text
            fid = resp.json()["id"]

            # list
            resp = app_client.get(f"/api/workspaces/{ws_id}/flows")
            assert resp.status_code == 200
            assert any(f["id"] == fid for f in resp.json())

            # get
            resp = app_client.get(f"/api/workspaces/{ws_id}/flows/{fid}")
            assert resp.status_code == 200
            assert resp.json()["name"] == "my-flow"
            assert resp.json()["definition_json"] is not None

            # update
            resp = app_client.put(f"/api/workspaces/{ws_id}/flows/{fid}", json={
                "name": "renamed-flow"
            })
            assert resp.status_code == 200
            assert resp.json()["name"] == "renamed-flow"

            # delete
            resp = app_client.delete(f"/api/workspaces/{ws_id}/flows/{fid}")
            assert resp.status_code == 204
            resp = app_client.get(f"/api/workspaces/{ws_id}/flows/{fid}")
            assert resp.status_code == 404
        finally:
            app_client.delete(f"/api/workspaces/{ws_id}")
