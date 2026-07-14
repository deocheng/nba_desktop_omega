"""NBACore Studio v8.3.2 — Analytics Builder end-to-end verification (smoke test).

Uses fastapi.testclient.TestClient(backend.app) — no live server, no port conflict.
Covers: /meta, /run (valid DAG), negative (cycle), and flows CRUD.

Run:
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
      .venv/Scripts/python.exe verify_v832_e2e.py
"""
from __future__ import annotations

import psycopg2
import backend.core.config as cfg
from fastapi.testclient import TestClient
import backend.app as backend_app

client = TestClient(backend_app.app)
FAILS = []


def check(cond, msg):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {msg}")
    if not cond:
        FAILS.append(msg)


def get_workspace_id() -> int:
    conn = psycopg2.connect(**cfg.DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM workspaces ORDER BY id LIMIT 1")
        row = cur.fetchone()
        if row:
            return int(row[0])
        # create one if none exist
        cur.execute(
            "INSERT INTO workspaces (name, owner_id) VALUES (%s, %s) RETURNING id",
            ("ab_verify_ws", 1),
        )
        wid = int(cur.fetchone()[0])
        conn.commit()
        return wid
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────
print("=" * 70)
print("STEP 1 — GET /api/analytics-builder/meta")
print("=" * 70)
r = client.get("/api/analytics-builder/meta")
check(r.status_code == 200, f"GET /meta HTTP {r.status_code}")
body = r.json()
check(body.get("code") == 0, f"envelope code==0 (got {body.get('code')})")
data = body.get("data", {})
tables = data.get("tables", [])
check(len(tables) > 0, f"data.tables non-empty (n={len(tables)})")
check(bool(data.get("agg_functions")), "agg_functions present")
check(bool(data.get("viz_types")), "viz_types present")
check(bool(data.get("filter_ops")), "filter_ops present")

# pick a table + a numeric column + a text column for the run step
table_name = None
num_col = None
text_col = None
for t in tables:
    cols = t["columns"]
    for c in cols:
        if c["type"] in ("int", "float") and num_col is None:
            num_col = c["name"]
        if c["type"] == "text" and text_col is None:
            text_col = c["name"]
    if num_col and text_col:
        table_name = t["name"]
        break
if table_name is None and tables:
    table_name = tables[0]["name"]
    cols = tables[0]["columns"]
    num_col = cols[1]["name"] if len(cols) > 1 else cols[0]["name"]
    text_col = cols[0]["name"]

print(f"  selected table = {table_name}")
print(f"  columns sample = {[c['name'] + ':' + c['type'] for c in next(t['columns'] for t in tables if t['name'] == table_name)][:8]}")
print(f"  num_col={num_col}  text_col={text_col}")


# ─────────────────────────────────────────────────────────────────────────
print("=" * 70)
print("STEP 2 — POST /api/analytics-builder/run  (valid DAG)")
print("=" * 70)
flow = {
    "version": "1",
    "nodes": [
        {"id": "n1", "type": "source", "title": "src", "x": 0, "y": 0,
         "params": {"source_mode": "table", "table": table_name, "limit": 5000}},
        {"id": "n2", "type": "filter", "title": "filt", "x": 200, "y": 0,
         "params": {"logic": "AND", "conditions": [
             {"field": num_col, "op": ">", "value": 0}]}},
        {"id": "n3", "type": "aggregate", "title": "agg", "x": 400, "y": 0,
         "params": {"group_by": [text_col],
                    "measures": [{"field": num_col, "agg": "count", "alias": "cnt"}]}},
        {"id": "n4", "type": "visualize", "title": "viz", "x": 600, "y": 0,
         "params": {"viz_type": "bar", "x_field": text_col,
                    "y_fields": ["cnt"], "title": "test"}},
    ],
    "edges": [
        {"id": "e1", "from": "n1", "to": "n2"},
        {"id": "e2", "from": "n2", "to": "n3"},
        {"id": "e3", "from": "n3", "to": "n4"},
    ],
}
workspace_id = get_workspace_id()
r = client.post("/api/analytics-builder/run",
                json={"flow": flow, "workspace_id": workspace_id})
check(r.status_code == 200, f"POST /run HTTP {r.status_code}")
body = r.json()
check(body.get("code") == 0, f"envelope code==0 (got {body.get('code')})")
data = body.get("data", {})
viz_results = data.get("viz_results", [])
check(len(viz_results) > 0, f"viz_results non-empty (n={len(viz_results)})")
node_status = data.get("node_status", {})
check(all(v == "ok" for v in node_status.values()) and node_status,
      f"all node_status ok ({node_status})")
check(len(data.get("errors", [])) == 0, "errors empty")
if viz_results:
    v = viz_results[0]
    cols = v.get("columns", [])
    rows = v.get("rows", [])
    print(f"  viz_type={v.get('viz_type')} row_count={v.get('row_count')}")
    print(f"  columns = {[c['name'] for c in cols]}")
    print(f"  sample rows = {rows[:3]}")


# ─────────────────────────────────────────────────────────────────────────
print("=" * 70)
print("STEP 3 — NEGATIVE: POST /run with a cycle (expect code!=0 / 400)")
print("=" * 70)
cycle_flow = dict(flow)
cycle_flow["edges"] = [
    {"id": "e1", "from": "n1", "to": "n2"},
    {"id": "e2", "from": "n2", "to": "n3"},
    {"id": "e3", "from": "n3", "to": "n2"},  # cycle
]
r = client.post("/api/analytics-builder/run",
                json={"flow": cycle_flow, "workspace_id": workspace_id})
check(r.status_code != 200, f"cycle rejected with HTTP {r.status_code}")
j = r.json()
check(j.get("code", 0) != 0 or "code" not in j,
      f"negative envelope not success (code={j.get('code')})")


# ─────────────────────────────────────────────────────────────────────────
print("=" * 70)
print("STEP 4 — FLOWS CRUD  (/api/workspaces/{ws}/flows)")
print("=" * 70)
base = f"/api/workspaces/{workspace_id}/flows"
definition = {"version": "1", "nodes": flow["nodes"], "edges": flow["edges"]}

# POST
r = client.post(base, json={"name": "v832_verify_flow", "definition": definition})
check(r.status_code == 201, f"POST /flows HTTP {r.status_code}")
j = r.json()
check(j.get("code") == 0, f"POST envelope code==0 (got {j.get('code')})")
flow_id = j["data"]["id"]
check(isinstance(flow_id, int), f"returned flow id = {flow_id}")

# GET single
r = client.get(f"{base}/{flow_id}")
check(r.status_code == 200 and r.json().get("code") == 0,
      f"GET /flows/{flow_id} ok (HTTP {r.status_code})")
check("definition_json" in r.json().get("data", {}) or "definition" in r.json().get("data", {}) or "definition" in r.json().get("data", {}),
      "GET single returns definition")

# PUT update name
r = client.put(f"{base}/{flow_id}", json={"name": "v832_verify_flow_renamed"})
check(r.status_code == 200 and r.json().get("code") == 0,
      f"PUT /flows/{flow_id} ok (HTTP {r.status_code})")
check(r.json()["data"]["name"] == "v832_verify_flow_renamed",
      f"PUT updated name -> {r.json()['data']['name']}")

# GET list
r = client.get(base)
check(r.status_code == 200 and r.json().get("code") == 0,
      f"GET /flows list ok (HTTP {r.status_code})")
check(any(f["id"] == flow_id for f in r.json().get("data", [])),
      "GET list contains our flow")

# DELETE
r = client.delete(f"{base}/{flow_id}")
check(r.status_code == 200 and r.json().get("code") == 0,
      f"DELETE /flows/{flow_id} ok (HTTP {r.status_code})")
check(r.json().get("data", {}).get("deleted") is True, "DELETE returns deleted=true")

# confirm gone
r = client.get(f"{base}/{flow_id}")
check(r.status_code == 404, f"GET deleted flow returns 404 (HTTP {r.status_code})")


print("=" * 70)
print("SUMMARY")
print("=" * 70)
if FAILS:
    print(f"RESULT: {len(FAILS)} FAILURE(S)")
    for f in FAILS:
        print("  - " + f)
    raise SystemExit(1)
print("RESULT: ALL CHECKS PASSED")
