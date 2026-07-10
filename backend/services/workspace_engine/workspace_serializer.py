"""NBACore v8.3.1 — Workspace serializer (.nbacore file format, PRD §8).

Pure (de)serialization between a `Workspace` domain object and the portable
`.nbacore` JSON project file. No DB access — pairs with the manager for
import/export (PRD v8.3.1 Phase 2, included here so Core is self-contained).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.services.workspace_engine import models


def to_dict(ws: models.Workspace) -> dict[str, Any]:
    return ws.to_dict()


def from_dict(data: dict[str, Any]) -> models.Workspace:
    return models.Workspace.from_dict(data)


def to_file(ws: models.Workspace, path: str | Path) -> Path:
    """Write a workspace to a `.nbacore` JSON file and return its path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(ws.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


def from_file(path: str | Path) -> models.Workspace:
    """Load a workspace from a `.nbacore` JSON file."""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    return models.Workspace.from_dict(data)
