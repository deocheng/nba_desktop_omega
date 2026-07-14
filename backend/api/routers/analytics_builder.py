"""NBACore v8.3.2 — /api/analytics-builder router (pure orchestration, Layer 3).

Zero SQL, zero pandas, zero computation. It validates the request, calls the
Analytics Builder engine, and shapes the ``{code, data, message}`` envelope.
All SELECTs live in ``analytics_builder_engine/ab_queries``; all flow DML lives
in ``workspace_db`` (v8 §6).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.routers.analytics_builder_schemas import (
    RunRequest,
)
from backend.services.analytics_builder_engine import ab_service
from backend.services.analytics_builder_engine.ab_validation import (
    FlowValidationError,
)

router = APIRouter(prefix="/api/analytics-builder", tags=["analytics-builder"])


@router.post("/run")
def run_flow(req: RunRequest):
    """Execute an analysis flow DAG. Returns viz results + per-node status."""
    try:
        result = ab_service.run_flow(
            req.flow.model_dump(by_alias=True), req.workspace_id
        )
    except FlowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"运行失败: {exc}")
    return {"code": 0, "data": result, "message": "ok"}


@router.get("/meta")
def meta(workspace_id: int | None = None):
    """Enumerate tables / functions / viz types for the builder UI."""
    try:
        data = ab_service.get_meta(workspace_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"获取元数据失败: {exc}")
    return {"code": 0, "data": data, "message": "ok"}
