"""NBACore v8.3.1 — Workspace repository (Data-Layer orchestration).

Translates DB rows into `Workspace` domain objects and back. The only writer
of workspace tables; delegates raw SQL to `workspace_db`. No business rules
live here — validation is the validator's job, orchestration the manager's.
"""
from __future__ import annotations

from backend.services.workspace_engine import models, workspace_db
from backend.services.workspace_engine.workspace_validator import (
    WorkspaceValidationError,
    validate_create,
    validate_update,
)


def _row_to_workspace(row: dict) -> models.Workspace:
    datasets = workspace_db.select_dataset_ids(row["id"])
    formulas = workspace_db.select_formula_ids(row["id"])
    charts = [
        models.WorkspaceChart(
            id=c["id"],
            workspace_id=c["workspace_id"],
            name=c["name"],
            chart_config=c["chart_config"],
            created_at=c.get("created_at"),
        )
        for c in workspace_db.select_charts(row["id"])
    ]
    return models.Workspace(
        id=row["id"],
        name=row["name"],
        owner_id=row["owner_id"],
        description=row.get("description") or "",
        status=row["status"],
        datasets=datasets,
        formulas=formulas,
        charts=charts,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


# ── Workspace CRUD ──

def create_workspace(
    name: str,
    owner_id: int = models.LOCAL_OWNER_ID,
    description: str = "",
    status: str = "active",
) -> models.Workspace:
    clean = validate_create(name, owner_id, description, status)
    meta = workspace_db.insert_workspace(
        clean["name"], clean["owner_id"], clean["description"], clean["status"]
    )
    return get_workspace(meta["id"])


def get_workspace(workspace_id: int) -> models.Workspace | None:
    row = workspace_db.select_workspace(workspace_id)
    if row is None:
        return None
    return _row_to_workspace(row)


def list_workspaces(
    owner_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[models.Workspace]:
    rows = workspace_db.select_workspaces(owner_id, status, limit, offset)
    return [_row_to_workspace(r) for r in rows]


def update_workspace(
    workspace_id: int,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> models.Workspace | None:
    validate_update(name, description, status)  # raises on bad input
    meta = workspace_db.update_workspace(workspace_id, name, description, status)
    if meta is None:
        return None
    return get_workspace(workspace_id)


def delete_workspace(workspace_id: int) -> bool:
    return workspace_db.delete_workspace(workspace_id)


def duplicate_workspace(workspace_id: int, new_name: str | None = None) -> models.Workspace:
    src = get_workspace(workspace_id)
    if src is None:
        raise ValueError(f"Workspace {workspace_id} not found")
    name = new_name or f"{src.name} (copy)"
    meta = workspace_db.insert_workspace(
        name, src.owner_id, src.description, src.status
    )
    new_id = meta["id"]
    workspace_db.copy_links(new_id, workspace_id)
    return get_workspace(new_id)


# ── Dataset links ──

def add_dataset(workspace_id: int, dataset_id: int) -> models.Workspace | None:
    if get_workspace(workspace_id) is None:
        return None
    workspace_db.insert_dataset_link(workspace_id, dataset_id)
    return get_workspace(workspace_id)


def remove_dataset(workspace_id: int, dataset_id: int) -> bool:
    return workspace_db.delete_dataset_link(workspace_id, dataset_id)


# ── Formula links ──

def add_formula(workspace_id: int, formula_id: int) -> models.Workspace | None:
    if get_workspace(workspace_id) is None:
        return None
    workspace_db.insert_formula_link(workspace_id, formula_id)
    return get_workspace(workspace_id)


def remove_formula(workspace_id: int, formula_id: int) -> bool:
    return workspace_db.delete_formula_link(workspace_id, formula_id)


# ── Charts ──

def add_chart(workspace_id: int, name: str, chart_config: dict) -> int:
    if get_workspace(workspace_id) is None:
        raise WorkspaceValidationError(f"Workspace {workspace_id} not found")
    return workspace_db.insert_chart(workspace_id, name, chart_config)


def update_chart(
    chart_id: int, name: str | None = None, chart_config: dict | None = None
) -> dict | None:
    return workspace_db.update_chart(chart_id, name, chart_config)


def remove_chart(chart_id: int) -> bool:
    return workspace_db.delete_chart(chart_id)


def get_chart(chart_id: int) -> dict | None:
    return workspace_db.select_chart(chart_id)


# ── Analysis Flows (v8.3.2) ──

def add_flow(workspace_id: int, name: str, definition: dict) -> int:
    if get_workspace(workspace_id) is None:
        raise WorkspaceValidationError(f"Workspace {workspace_id} not found")
    return workspace_db.insert_flow(workspace_id, name, definition)


def update_flow(
    flow_id: int, name: str | None = None, definition: dict | None = None
) -> dict | None:
    return workspace_db.update_flow(flow_id, name, definition)


def remove_flow(flow_id: int) -> bool:
    return workspace_db.delete_flow(flow_id)


def get_flow(flow_id: int) -> dict | None:
    return workspace_db.select_flow(flow_id)


def list_flows(workspace_id: int) -> list[dict]:
    return workspace_db.select_flows(workspace_id)
