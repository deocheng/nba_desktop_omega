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
    @pytest.mark.needs_data
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


@pytest.mark.needs_data
@needs_db
class TestRunEndpointLive:
    def test_run_real_source(self, app_client):
        from backend.services.analytics_builder_engine import ab_queries as Q
        tables = Q.introspect_tables()
        assert tables
        tbl = tables[0]
        # 🔴 可视化节点要求 y_fields 非空 + x_field 为真实列（引擎契约，
        #    见 ab_validation.validate_flow）。旧样本 flow 的 y_fields=[] 是
        #    为「校验失败」用例准备的，这里按实际表结构自适应填列名。
        num_cols = [c["name"] for c in tbl["columns"] if c["type"] in ("int", "float")]
        assert num_cols, f"table {tbl['name']} has no numeric column to visualize"
        flow = _sample_flow()
        flow["nodes"][0]["params"]["table"] = tbl["name"]
        flow["nodes"][1]["params"]["x_field"] = tbl["columns"][0]["name"]
        flow["nodes"][1]["params"]["y_fields"] = [num_cols[0]]
        resp = app_client.post("/api/analytics-builder/run", json={"flow": flow})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["node_status"].get("v") == "ok"
        assert body["data"]["viz_results"]


@pytest.mark.needs_data
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
            # create —— flows 端点走 envelope 契约 {code, data, message}，
            # 业务字段在 data 下（与 backend/tests 旧副本一致）
            flow = _sample_flow()
            flow["nodes"][0]["params"]["table"] = "fact_player_season"  # may not exist; still stores definition
            resp = app_client.post(f"/api/workspaces/{ws_id}/flows", json={
                "name": "my-flow", "definition": {"version": "1", **flow}
            })
            assert resp.status_code == 201, resp.text
            assert resp.json()["code"] == 0
            fid = resp.json()["data"]["id"]

            # list
            resp = app_client.get(f"/api/workspaces/{ws_id}/flows")
            assert resp.status_code == 200
            assert resp.json()["code"] == 0
            assert any(f["id"] == fid for f in resp.json()["data"])

            # get
            resp = app_client.get(f"/api/workspaces/{ws_id}/flows/{fid}")
            assert resp.status_code == 200
            assert resp.json()["code"] == 0
            assert resp.json()["data"]["name"] == "my-flow"
            assert resp.json()["data"]["definition"] is not None

            # update
            resp = app_client.put(f"/api/workspaces/{ws_id}/flows/{fid}", json={
                "name": "renamed-flow"
            })
            assert resp.status_code == 200
            assert resp.json()["code"] == 0
            assert resp.json()["data"]["name"] == "renamed-flow"

            # delete
            resp = app_client.delete(f"/api/workspaces/{ws_id}/flows/{fid}")
            assert resp.status_code == 200
            assert resp.json()["code"] == 0
            assert resp.json()["data"]["deleted"] is True
            resp = app_client.get(f"/api/workspaces/{ws_id}/flows/{fid}")
            assert resp.status_code == 404
        finally:
            app_client.delete(f"/api/workspaces/{ws_id}")
