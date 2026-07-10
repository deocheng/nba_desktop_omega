"""NBACore v8.3.1 — Workspace Manager (PRD v8.3.1 §9).

High-level facade used by the API/CLI. Pure orchestration: validate → persist
via repository. The "save/load/delete/duplicate" lifecycle lives here.
"""
from __future__ import annotations

from backend.services.workspace_engine import models, workspace_repository as repo
from backend.services.workspace_engine.workspace_validator import (
    WorkspaceValidationError,
    validate_create,
    validate_update,
)


def create(
    name: str,
    owner_id: int = models.LOCAL_OWNER_ID,
    description: str = "",
    status: str = "active",
) -> models.Workspace:
    clean = validate_create(name, owner_id, description, status)
    return repo.create_workspace(
        clean["name"], clean["owner_id"], clean["description"], clean["status"]
    )


def save(ws: models.Workspace) -> models.Workspace:
    """Upsert a workspace object by id."""
    if ws.id is None:
        return create(ws.name, ws.owner_id, ws.description, ws.status)
    return repo.update_workspace(ws.id, ws.name, ws.description, ws.status)


def load(workspace_id: int) -> models.Workspace | None:
    return repo.get_workspace(workspace_id)


def list_workspaces(
    owner_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[models.Workspace]:
    return repo.list_workspaces(owner_id, status, limit, offset)


def update_workspace(
    workspace_id: int,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> models.Workspace | None:
    validate_update(name, description, status)
    return repo.update_workspace(workspace_id, name, description, status)


def delete(workspace_id: int) -> bool:
    return repo.delete_workspace(workspace_id)


def duplicate(workspace_id: int, new_name: str | None = None) -> models.Workspace:
    return repo.duplicate_workspace(workspace_id, new_name)


# ── Resource link convenience wrappers (delegated to repository) ──

def add_dataset(workspace_id: int, dataset_id: int) -> models.Workspace | None:
    return repo.add_dataset(workspace_id, dataset_id)


def remove_dataset(workspace_id: int, dataset_id: int) -> bool:
    return repo.remove_dataset(workspace_id, dataset_id)


def add_formula(workspace_id: int, formula_id: int) -> models.Workspace | None:
    return repo.add_formula(workspace_id, formula_id)


def remove_formula(workspace_id: int, formula_id: int) -> bool:
    return repo.remove_formula(workspace_id, formula_id)


def add_chart(workspace_id: int, name: str, chart_config: dict) -> int:
    return repo.add_chart(workspace_id, name, chart_config)


def update_chart(
    chart_id: int, name: str | None = None, chart_config: dict | None = None
) -> dict | None:
    return repo.update_chart(chart_id, name, chart_config)


def remove_chart(chart_id: int) -> bool:
    return repo.remove_chart(chart_id)


def get_chart(chart_id: int) -> dict | None:
    return repo.get_chart(chart_id)
