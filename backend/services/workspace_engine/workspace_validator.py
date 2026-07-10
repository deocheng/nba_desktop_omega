"""NBACore v8.3.1 — Workspace validation (PRD v8.3.1 §10).

Pure guard rails applied before persistence. No DB access.
"""
from __future__ import annotations

from backend.services.workspace_engine.models import LOCAL_OWNER_ID, VALID_STATUSES

NAME_MAX = 200


class WorkspaceValidationError(ValueError):
    """Raised when a workspace fails validation (maps to HTTP 400)."""


def validate_create(
    name: str,
    owner_id: int = LOCAL_OWNER_ID,
    description: str = "",
    status: str = "active",
) -> dict:
    if not name or not str(name).strip():
        raise WorkspaceValidationError("Workspace name is required")
    if len(str(name)) > NAME_MAX:
        raise WorkspaceValidationError(f"Workspace name too long (max {NAME_MAX})")
    if status not in VALID_STATUSES:
        raise WorkspaceValidationError(
            f"Invalid status {status!r}; must be one of {list(VALID_STATUSES)}"
        )
    if owner_id is None or owner_id < 1:
        raise WorkspaceValidationError("owner_id must be a positive integer")
    return {
        "name": str(name).strip(),
        "owner_id": int(owner_id),
        "description": description or "",
        "status": status,
    }


def validate_update(
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> dict:
    """Validate an update payload; only non-None fields are checked."""
    clean: dict = {}
    if name is not None:
        if not str(name).strip():
            raise WorkspaceValidationError("Workspace name cannot be empty")
        if len(str(name)) > NAME_MAX:
            raise WorkspaceValidationError(f"Workspace name too long (max {NAME_MAX})")
        clean["name"] = str(name).strip()
    if status is not None:
        if status not in VALID_STATUSES:
            raise WorkspaceValidationError(
                f"Invalid status {status!r}; must be one of {list(VALID_STATUSES)}"
            )
        clean["status"] = status
    if description is not None:
        clean["description"] = description
    return clean
