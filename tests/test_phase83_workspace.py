"""NBACore v8.3.1 — Workspace Core tests (PRD v8.3.1 §17).

Covers: create / save / load / delete / validate / duplicate, resource links
(datasets / formulas / charts), serializer round-trips, and the CRUD API.
Live PostgreSQL only (v8 §6 — no mocking of core logic).
"""
from __future__ import annotations

import pytest

from backend.services.workspace_engine import (
    WorkspaceValidationError,
    add_chart,
    add_dataset,
    add_formula,
    create,
    delete,
    duplicate,
    get_chart,
    list_workspaces,
    load,
    models,
    remove_chart,
    remove_dataset,
    remove_formula,
    update_chart,
    update_workspace,
)
from backend.services.workspace_engine import workspace_serializer as ser
from backend.services.workspace_engine.workspace_validator import (
    validate_create,
    validate_update,
)


def _skip_if_no_db(db_available: bool) -> None:
    if not db_available:
        pytest.skip("PostgreSQL not available — set DB_PORT and start service")


# ── Validator (pure) ──

class TestWorkspaceValidator:
    def test_name_required(self):
        with pytest.raises(WorkspaceValidationError):
            validate_create("")

    def test_name_whitespace_invalid(self):
        with pytest.raises(WorkspaceValidationError):
            validate_create("   ")

    def test_invalid_status(self):
        with pytest.raises(WorkspaceValidationError):
            validate_create("X", status="bogus")

    def test_owner_id_positive(self):
        with pytest.raises(WorkspaceValidationError):
            validate_create("X", owner_id=0)

    def test_valid(self):
        clean = validate_create("  OK  ", description="d")
        assert clean["name"] == "OK"
        assert clean["owner_id"] == 1
        assert clean["description"] == "d"

    def test_update_empty_name(self):
        with pytest.raises(WorkspaceValidationError):
            validate_update(name="")

    def test_update_valid(self):
        clean = validate_update(name="A", status="archived", description="x")
        assert clean == {"name": "A", "status": "archived", "description": "x"}


# ── Manager (live DB) ──

class TestWorkspaceManager:
    def test_create_and_load(self, db_available):
        _skip_if_no_db(db_available)
        ws = create("mgr_create_1")
        try:
            assert ws.id is not None
            loaded = load(ws.id)
            assert loaded is not None
            assert loaded.name == "mgr_create_1"
            assert loaded.owner_id == 1
        finally:
            delete(ws.id)

    def test_update(self, db_available):
        _skip_if_no_db(db_available)
        ws = create("mgr_upd_1", description="old", status="active")
        try:
            updated = update_workspace(ws.id, name="mgr_upd_2", description="new", status="archived")
            assert updated.name == "mgr_upd_2"
            assert updated.status == "archived"
            reloaded = load(ws.id)
            assert reloaded.description == "new"
        finally:
            delete(ws.id)

    def test_delete(self, db_available):
        _skip_if_no_db(db_available)
        ws = create("mgr_del_1")
        delete(ws.id)
        assert load(ws.id) is None

    def test_duplicate_copies_links(self, db_available):
        _skip_if_no_db(db_available)
        ws = create("mgr_dup_1")
        try:
            add_dataset(ws.id, 42)
            add_formula(ws.id, 7)
            add_chart(ws.id, "chart_a", {"type": "line"})
            dup = duplicate(ws.id, new_name="mgr_dup_1_copy")
            try:
                assert dup.id != ws.id
                assert dup.name == "mgr_dup_1_copy"
                assert dup.datasets == [42]
                assert dup.formulas == [7]
                assert len(dup.charts) == 1
                assert dup.charts[0].name == "chart_a"
            finally:
                delete(dup.id)
        finally:
            delete(ws.id)

    def test_dataset_link(self, db_available):
        _skip_if_no_db(db_available)
        ws = create("mgr_ds_1")
        try:
            add_dataset(ws.id, 101)
            assert load(ws.id).datasets == [101]
            remove_dataset(ws.id, 101)
            assert load(ws.id).datasets == []
        finally:
            delete(ws.id)

    def test_formula_link(self, db_available):
        _skip_if_no_db(db_available)
        ws = create("mgr_fm_1")
        try:
            add_formula(ws.id, 55)
            assert load(ws.id).formulas == [55]
            remove_formula(ws.id, 55)
            assert load(ws.id).formulas == []
        finally:
            delete(ws.id)

    def test_chart_crud(self, db_available):
        _skip_if_no_db(db_available)
        ws = create("mgr_ch_1")
        try:
            cid = add_chart(ws.id, "c1", {"type": "bar"})
            assert isinstance(cid, int)
            assert get_chart(cid)["name"] == "c1"
            update_chart(cid, name="c2", chart_config={"type": "radar"})
            assert get_chart(cid)["name"] == "c2"
            assert get_chart(cid)["chart_config"]["type"] == "radar"
            assert remove_chart(cid) is True
            assert get_chart(cid) is None
        finally:
            delete(ws.id)

    def test_list_includes_created(self, db_available):
        _skip_if_no_db(db_available)
        ws = create("mgr_list_unique")
        try:
            ids = [w.id for w in list_workspaces()]
            assert ws.id in ids
        finally:
            delete(ws.id)


# ── Serializer (pure + file IO) ──

class TestWorkspaceSerializer:
    def _sample(self) -> models.Workspace:
        return models.Workspace(
            id=None,
            name="SerTest",
            owner_id=1,
            description="d",
            status="active",
            datasets=[1, 2],
            formulas=[3],
            charts=[models.WorkspaceChart(id=None, workspace_id=0, name="c", chart_config={"k": 1})],
        )

    def test_dict_roundtrip(self):
        ws = self._sample()
        ws2 = ser.from_dict(ser.to_dict(ws))
        assert ws2.name == ws.name
        assert ws2.datasets == [1, 2]
        assert ws2.charts[0].chart_config == {"k": 1}

    def test_file_roundtrip(self, tmp_path):
        ws = self._sample()
        path = tmp_path / "sample.nbacore"
        ser.to_file(ws, path)
        assert path.exists()
        ws2 = ser.from_file(path)
        assert ws2.name == ws.name
        assert ws2.charts[0].chart_config == {"k": 1}


# ── API (live DB via TestClient) ──

@pytest.fixture
def api_workspace(app_client, db_available):
    _skip_if_no_db(db_available)
    resp = app_client.post("/api/workspaces", json={"name": "__api_ws__"})
    assert resp.status_code == 201
    wid = resp.json()["id"]
    yield wid
    app_client.delete(f"/api/workspaces/{wid}")


class TestWorkspaceAPI:
    def test_create_201(self, app_client, db_available):
        _skip_if_no_db(db_available)
        resp = app_client.post("/api/workspaces", json={"name": "api_create_1"})
        try:
            assert resp.status_code == 201
            body = resp.json()
            assert body["name"] == "api_create_1"
            assert body["id"] > 0
            assert body["datasets"] == []
        finally:
            app_client.delete(f"/api/workspaces/{body['id']}")

    def test_create_validation_400(self, app_client, db_available):
        _skip_if_no_db(db_available)
        resp = app_client.post("/api/workspaces", json={"name": ""})
        assert resp.status_code == 400

    def test_get_list(self, app_client, api_workspace):
        resp = app_client.get("/api/workspaces")
        assert resp.status_code == 200
        ids = [w["id"] for w in resp.json()]
        assert api_workspace in ids

    def test_get_by_id(self, app_client, api_workspace):
        resp = app_client.get(f"/api/workspaces/{api_workspace}")
        assert resp.status_code == 200
        assert resp.json()["id"] == api_workspace

    def test_get_unknown_404(self, app_client, db_available):
        _skip_if_no_db(db_available)
        resp = app_client.get("/api/workspaces/999999999")
        assert resp.status_code == 404

    def test_update_put(self, app_client, api_workspace):
        resp = app_client.put(
            f"/api/workspaces/{api_workspace}",
            json={"name": "api_renamed", "status": "archived"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "api_renamed"
        assert resp.json()["status"] == "archived"

    def test_delete_204(self, app_client, db_available):
        _skip_if_no_db(db_available)
        created = app_client.post("/api/workspaces", json={"name": "api_del_1"}).json()
        wid = created["id"]
        resp = app_client.delete(f"/api/workspaces/{wid}")
        assert resp.status_code == 204
        assert app_client.get(f"/api/workspaces/{wid}").status_code == 404

    def test_dataset_link(self, app_client, api_workspace):
        resp = app_client.post(
            f"/api/workspaces/{api_workspace}/datasets", json={"dataset_id": 999}
        )
        assert resp.status_code == 200
        assert resp.json()["datasets"] == [999]

    def test_chart_flow(self, app_client, api_workspace):
        created = app_client.post(
            f"/api/workspaces/{api_workspace}/charts",
            json={"name": "line1", "chart_config": {"type": "line"}},
        )
        assert created.status_code == 201
        cid = created.json()["id"]
        upd = app_client.put(
            f"/api/workspaces/{api_workspace}/charts/{cid}",
            json={"name": "line2", "chart_config": {"type": "bar"}},
        )
        assert upd.status_code == 200
        assert upd.json()["name"] == "line2"
        assert app_client.delete(
            f"/api/workspaces/{api_workspace}/charts/{cid}"
        ).status_code == 204

    def test_export(self, app_client, api_workspace):
        resp = app_client.get(f"/api/workspaces/{api_workspace}/export")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == api_workspace
        assert data["name"] == "__api_ws__"
        assert "Content-Disposition" in resp.headers
