"""NBACore v8.3.1 — Workspace Engine (Layer above Intelligence Engine).

Public API for the Analytics Workspace Core (PRD v8.3.1). The API router and
CLI consume only these names; all DB access is fenced inside `workspace_db`.

v8 §6 compliance:
    - No eval()/exec()
    - The only module importing psycopg2 is `workspace_db` (the dedicated
      write-path Data Layer — `core.db` stays SELECT-only for analytics).
    - No dynamic SQL; parameterized DML + idempotent DDL constants.
"""
from __future__ import annotations

from backend.services.workspace_engine.models import (
    LOCAL_OWNER_ID,
    VALID_STATUSES,
    Workspace,
    WorkspaceChart,
)
from backend.services.workspace_engine.workspace_manager import (
    add_chart,
    add_dataset,
    add_flow,
    add_formula,
    create,
    delete,
    duplicate,
    get_chart,
    get_flow,
    list_flows,
    list_workspaces,
    load,
    remove_chart,
    remove_dataset,
    remove_flow,
    remove_formula,
    save,
    update_chart,
    update_flow,
    update_workspace,
)
from backend.services.workspace_engine.workspace_serializer import (
    from_dict,
    from_file,
    to_dict,
    to_file,
)
from backend.services.workspace_engine.workspace_validator import (
    WorkspaceValidationError,
    validate_create,
    validate_update,
)

__phase_status__ = "phase831-core"
__all__ = [
    # models
    "Workspace",
    "WorkspaceChart",
    "LOCAL_OWNER_ID",
    "VALID_STATUSES",
    # manager (lifecycle)
    "create",
    "save",
    "load",
    "list_workspaces",
    "update_workspace",
    "delete",
    "duplicate",
    # resource links
    "add_dataset",
    "remove_dataset",
    "add_formula",
    "remove_formula",
    "add_chart",
    "update_chart",
    "remove_chart",
    "get_chart",
    # analysis flows (v8.3.2)
    "add_flow",
    "update_flow",
    "remove_flow",
    "get_flow",
    "list_flows",
    # serializer
    "to_dict",
    "from_dict",
    "to_file",
    "from_file",
    # validator
    "WorkspaceValidationError",
    "validate_create",
    "validate_update",
]
