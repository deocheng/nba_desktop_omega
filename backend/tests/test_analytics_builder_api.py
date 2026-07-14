"""NBACore v8.3.2 — Analytics Builder API integration tests (DB required).

Exercises:
  - POST /api/analytics-builder/run  (success + validation failures)
  - GET  /api/analytics-builder/meta
  - /api/workspaces/{id}/flows  CRUD + envelope shape

The PostgreSQL DB is expected to be reachable (localhost:5433/nba). If it is
not, the DB-dependent tests fail loudly — they are NOT silently skipped.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services.workspace_engine import create as create_workspace
from backend.services.workspace_engine import delete as delete_workspace

pytestmark = pytest.mark.needs_db

# A whitelisted fact_* table known to exist in the dev DB.
TABLE = "fact_player_season_stats"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def workspace_id():
    ws = create_workspace(name="ab-test-ws", owner_id=1)
    wid = ws.id
    yield wid
    try:
        delete_workspace(wid)
    except Exception:
        pass


def _run_payload():
    return {
        "flow": {
            "version": "1",
            "nodes": [
                {"id": "n1", "type": "source",
                 "params": {"source_mode": "table", "table": TABLE, "limit": 50}},
                {"id": "n2", "type": "filter",
                 "params": {"logic": "AND",
                            "conditions": [{"field": "pts", "op": ">", "value": -1}]}},
                {"id": "n3", "type": "visualize",
                 "params": {"viz_type": "table", "x_field": "season",
                            "y_fields": ["pts"], "title": "t"}},
            ],
            "edges": [
                {"id": "e1", "from": "n1", "to": "n2"},
                {"id": "e2", "from": "n2", "to": "n3"},
            ],
        },
        "workspace_id": 1,
    }


# ── /run ──
def test_run_success(client):
    r = client.post("/api/analytics-builder/run", json=_run_payload())
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert len(body["data"]["viz_results"]) >= 1
    assert body["data"]["node_status"]["n1"] == "ok"
    assert body["data"]["node_status"]["n3"] == "ok"


def test_run_cycle_failure(client):
    payload = _run_payload()
    payload["flow"]["edges"].append({"id": "e3", "from": "n2", "to": "n1"})
    r = client.post("/api/analytics-builder/run", json=payload)
    assert r.status_code == 400  # validation error -> non-zero code


def test_run_visualize_without_upstream(client):
    payload = {
        "flow": {
            "version": "1",
            "nodes": [{"id": "n1", "type": "visualize",
                       "params": {"viz_type": "table", "x_field": "season",
                                  "y_fields": ["pts"]}}],
            "edges": [],
        },
        "workspace_id": 1,
    }
    r = client.post("/api/analytics-builder/run", json=payload)
    assert r.status_code == 400


def test_run_bad_param(client):
    payload = _run_payload()
    payload["flow"]["nodes"][1]["params"]["conditions"] = [
        {"field": "pts", "op": "bogus", "value": 1}
    ]
    r = client.post("/api/analytics-builder/run", json=payload)
    assert r.status_code == 400


# ── /meta ──
def test_meta(client):
    r = client.get("/api/analytics-builder/meta")
    assert r.status_code == 200
    d = r.json()["data"]
    assert isinstance(d["tables"], list)
    assert "sum" in d["agg_functions"]
    assert "table" in d["viz_types"]
    assert any(op["op"] == "=" for op in d["filter_ops"])


# ── flows CRUD (envelope shape) ──
def test_flows_crud(client, workspace_id):
    definition = {
        "version": "1",
        "nodes": [{"id": "n1", "type": "source",
                   "params": {"source_mode": "table", "table": TABLE, "limit": 10}}],
        "edges": [],
    }

    # create
    r = client.post(f"/api/workspaces/{workspace_id}/flows",
                    json={"name": "flow1", "definition": definition})
    assert r.status_code == 201
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["name"] == "flow1"
    fid = body["data"]["id"]

    # get
    r = client.get(f"/api/workspaces/{workspace_id}/flows/{fid}")
    assert r.status_code == 200 and r.json()["code"] == 0
    assert r.json()["data"]["definition"]["nodes"][0]["id"] == "n1"

    # update
    r = client.put(f"/api/workspaces/{workspace_id}/flows/{fid}",
                   json={"name": "flow1-upd"})
    assert r.status_code == 200 and r.json()["code"] == 0
    assert r.json()["data"]["name"] == "flow1-upd"

    # list
    r = client.get(f"/api/workspaces/{workspace_id}/flows")
    assert r.status_code == 200
    ids = [f["id"] for f in r.json()["data"]]
    assert fid in ids

    # delete
    r = client.delete(f"/api/workspaces/{workspace_id}/flows/{fid}")
    assert r.status_code == 200 and r.json()["code"] == 0
    assert r.json()["data"]["deleted"] is True

    # confirm gone
    r = client.get(f"/api/workspaces/{workspace_id}/flows/{fid}")
    assert r.status_code == 404
