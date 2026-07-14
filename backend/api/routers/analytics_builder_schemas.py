"""NBACore v8.3.2 — Analytics Builder API contracts (Layer 3).

Pure data contracts. No computation, no methods beyond simple validators.
Mirrors ``career_schemas`` style. The response envelope ``{code, data,
message}`` is produced by the router (using these as request/response bodies).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── Graph sub-models ──
class NodeSpec(BaseModel):
    id: str
    type: str
    title: str | None = None
    x: int = 0
    y: int = 0
    params: dict[str, Any] = Field(default_factory=dict)


class EdgeSpec(BaseModel):
    id: str
    from_: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


class FlowGraph(BaseModel):
    version: str = "1"
    workspace_id: int | None = None
    nodes: list[NodeSpec]
    edges: list[EdgeSpec] = Field(default_factory=list)


# ── Run ──
class RunRequest(BaseModel):
    flow: FlowGraph
    workspace_id: int | None = None


class RunResponse(BaseModel):
    viz_results: list[dict[str, Any]]
    node_status: dict[str, str]
    errors: list[dict[str, str]]
    table_count: int


# ── Meta ──
class MetaTableColumn(BaseModel):
    name: str
    type: str


class MetaTable(BaseModel):
    name: str
    columns: list[MetaTableColumn]


class MetaFilterOp(BaseModel):
    op: str
    label: str


class WorkspaceDatasetRef(BaseModel):
    id: int
    name: str
    table: str | None = None


class MetaResponse(BaseModel):
    node_types: list[str]
    tables: list[MetaTable]
    agg_functions: list[str]
    viz_types: list[str]
    filter_ops: list[MetaFilterOp]
    source_modes: list[str]
    row_limit: int
    workspace_datasets: list[WorkspaceDatasetRef]


# ── Flow persistence (workspace resource) ──
class FlowCreate(BaseModel):
    name: str
    definition: dict[str, Any]


class FlowUpdate(BaseModel):
    name: str | None = None
    definition: dict[str, Any] | None = None


class FlowResponse(BaseModel):
    id: int
    workspace_id: int
    name: str
    definition: dict[str, Any] | None = Field(default=None, alias="definition_json")
    created_at: Any | None = None
    updated_at: Any | None = None

    model_config = {"populate_by_name": True}
