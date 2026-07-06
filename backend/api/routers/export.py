"""NBACore v8 §2 Layer 3 — /export router (pure orchestration).

Export endpoints: JSON/CSV for rankings, VS, player, league.
All data from export_service → metric_engine. No computation here.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response

from backend.services.export_service import (
    export_league_json,
    export_player_json,
    export_rankings_csv,
    export_rankings_json,
    export_vs_csv,
    export_vs_json,
)
from backend.services.metric_engine import list_metrics

router = APIRouter(prefix="/export", tags=["export"])

_VALID_FORMATS = {"json", "csv"}


def _check_format(fmt: str) -> None:
    if fmt not in _VALID_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format '{fmt}'. Available: {sorted(_VALID_FORMATS)}",
        )


@router.get("/rankings")
def export_rankings(
    metric: str = Query(..., description="Metric name"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    format: str = Query("json", description="json or csv"),
    limit: int = Query(100, ge=1, le=500, description="Max players"),
) -> Response:
    """Export rankings as JSON or CSV."""
    _check_format(format)

    available = set(list_metrics())
    if metric not in available:
        raise HTTPException(
            status_code=404,
            detail=f"unknown metric: {metric}. Available: {sorted(available)}",
        )

    try:
        if format == "json":
            result = export_rankings_json(metric, season, limit)
        else:
            result = export_rankings_csv(metric, season, limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"export failed: {exc}")

    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={
            "Content-Disposition": f"attachment; filename={result.filename}",
            "X-Export-SHA256": result.sha256,
        },
    )


@router.get("/vs")
def export_vs(
    p1: str = Query(..., description="BBR player_id for player 1"),
    p2: str = Query(..., description="BBR player_id for player 2"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    format: str = Query("json", description="json or csv"),
    metrics: str | None = Query(None, description="Comma-separated metric names"),
) -> Response:
    """Export VS comparison as JSON or CSV."""
    _check_format(format)

    if p1 == p2:
        raise HTTPException(status_code=400, detail="p1 and p2 must be different")

    if metrics:
        metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
    else:
        metric_names = [
            "pts_per_game", "reb_per_game", "ast_per_game",
            "stl_per_game", "blk_per_game", "true_shooting_pct",
            "effective_fg_pct", "usage_percent", "fantasy_points",
            "efficiency_rating",
        ]

    available = set(list_metrics())
    invalid = [m for m in metric_names if m not in available]
    if invalid:
        raise HTTPException(
            status_code=404,
            detail=f"unknown metrics: {invalid}. Available: {sorted(available)}",
        )

    try:
        if format == "json":
            result = export_vs_json(p1, p2, season, metric_names)
        else:
            result = export_vs_csv(p1, p2, season, metric_names)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"export failed: {exc}")

    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={
            "Content-Disposition": f"attachment; filename={result.filename}",
            "X-Export-SHA256": result.sha256,
        },
    )


@router.get("/player")
def export_player(
    player_id: str = Query(..., description="BBR player_id"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    format: str = Query("json", description="json only"),
    metrics: str | None = Query(None, description="Comma-separated metric names"),
) -> Response:
    """Export single-player metrics as JSON."""
    if format != "json":
        raise HTTPException(status_code=400, detail="Player export only supports JSON")

    metric_names = None
    if metrics:
        metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
        available = set(list_metrics())
        invalid = [m for m in metric_names if m not in available]
        if invalid:
            raise HTTPException(
                status_code=404,
                detail=f"unknown metrics: {invalid}. Available: {sorted(available)}",
            )

    try:
        result = export_player_json(player_id, season, metric_names)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"export failed: {exc}")

    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={
            "Content-Disposition": f"attachment; filename={result.filename}",
            "X-Export-SHA256": result.sha256,
        },
    )
