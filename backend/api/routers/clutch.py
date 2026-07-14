"""NBACore v8 — /api/clutch router (pure orchestration, Layer 3).

Mirrors the existing /api/workspaces style and returns a
``{code, data, message}`` envelope (data is an array of player rows).

All aggregation SQL is delegated to the clutch engine; this router contains
NO SQL, NO pandas, NO computation (v8 §2 Layer 3 mandate). It only
validates the request and shapes the envelope.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.api.routers.clutch_schemas import ClutchQuery
from backend.services.clutch_engine import clutch_service

router = APIRouter(prefix="/api/clutch", tags=["clutch"])


@router.get("/players")
def get_clutch_players(
    season: int | None = Query(None, description="NBA season; null = all"),
    period: int = Query(4, ge=1, le=8),
    clock_max: int = Query(300, ge=0, le=3000),
    margin_max: int = Query(5, ge=0, le=50),
    metric: str = Query("possessions", pattern="^(possessions|points)$"),
    min_poss: int = Query(10, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    """Top clutch-time players aggregated by the clutch engine."""
    try:
        q = ClutchQuery(
            season=season,
            period=period,
            clock_max=clock_max,
            margin_max=margin_max,
            metric=metric,
            min_poss=min_poss,
            limit=limit,
        )
        players = clutch_service.get_clutch_players(
            period=q.period,
            clock_max=q.clock_max,
            margin_max=q.margin_max,
            season=q.season,
            metric=q.metric,
            min_poss=q.min_poss,
            limit=q.limit,
        )
        return {"code": 0, "data": players, "message": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface engine errors cleanly
        raise HTTPException(status_code=500, detail=f"clutch players failed: {exc}")


@router.get("/seasons")
def get_clutch_seasons():
    """Distinct seasons available for the clutch filter."""
    try:
        seasons = clutch_service.get_seasons()
        return {"code": 0, "data": seasons, "message": "ok"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"clutch seasons failed: {exc}")
