"""NBACore v8.3.1 — Workspace domain models (Layer 2 domain objects).

Pure data contracts. Frozen dataclasses (mirrors the MetricSpec style). No DB
access, no computation — only serialization helpers used by the serializer and
repository. The Workspace Engine is the new persistence/analysis layer that
sits above the Intelligence Engine in v8.3 (PRD v8.3.0 §4.1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Local single-user deployment has no auth system; the owning principal is the
# local analyst. External multi-user ownership arrives with v8.3 permissions.
LOCAL_OWNER_ID: int = 1

VALID_STATUSES = ("active", "archived")


@dataclass(frozen=True)
class WorkspaceChart:
    """A single chart node attached to a workspace (PRD v8.3.1 §7)."""

    id: int | None
    workspace_id: int
    name: str
    chart_config: dict[str, Any]
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "chart_config": self.chart_config,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorkspaceChart":
        return cls(
            id=d.get("id"),
            workspace_id=d.get("workspace_id", 0),
            name=d.get("name", "chart"),
            chart_config=d.get("chart_config") or {},
            created_at=_parse_dt(d.get("created_at")),
        )


@dataclass(frozen=True)
class Workspace:
    """A complete basketball analysis project (PRD v8.3.1 §5.1).

    A workspace owns datasets, formulas, and charts. The nested collections
    are populated from the workspace_* link tables by the repository.
    """

    id: int | None
    name: str
    owner_id: int
    description: str = ""
    status: str = "active"
    datasets: list[int] = field(default_factory=list)
    formulas: list[int] = field(default_factory=list)
    charts: list[WorkspaceChart] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "owner_id": self.owner_id,
            "description": self.description,
            "status": self.status,
            "datasets": list(self.datasets),
            "formulas": list(self.formulas),
            "charts": [c.to_dict() for c in self.charts],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Workspace":
        charts = [WorkspaceChart.from_dict(c) for c in d.get("charts", [])]
        return cls(
            id=d.get("id"),
            name=d["name"],
            owner_id=d.get("owner_id", LOCAL_OWNER_ID),
            description=d.get("description", ""),
            status=d.get("status", "active"),
            datasets=list(d.get("datasets", [])),
            formulas=list(d.get("formulas", [])),
            charts=charts,
            created_at=_parse_dt(d.get("created_at")),
            updated_at=_parse_dt(d.get("updated_at")),
        )


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
