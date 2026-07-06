"""NBACore v8 §2 Layer 3 — /vs router (pure orchestration).

VS comparison endpoint. All computation delegated to metric_engine.vs_compare.
This router contains NO SQL, NO pandas, NO computation.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.api.schemas import VSCompareResponse
from backend.services.metric_engine import list_metrics, vs_compare

router = APIRouter(prefix="/vs", tags=["vs"])

# Default metrics for VS comparison (can be overridden via query param)
_DEFAULT_VS_METRICS = [
    "pts_per_game",
    "reb_per_game",
    "ast_per_game",
    "stl_per_game",
    "blk_per_game",
    "true_shooting_pct",
    "effective_fg_pct",
    "usage_percent",
    "fantasy_points",
    "efficiency_rating",
]


@router.get("/compare", response_model=VSCompareResponse)
def compare_players(
    p1: str = Query(..., description="BBR player_id for player 1"),
    p2: str = Query(..., description="BBR player_id for player 2"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    metrics: str | None = Query(
        None,
        description="Comma-separated metric names (defaults to all built-ins)",
    ),
) -> VSCompareResponse:
    """Compare two players across multiple metrics for a season."""
    if p1 == p2:
        raise HTTPException(status_code=400, detail="p1 and p2 must be different players")

    # Resolve metric list (default or user-specified)
    if metrics:
        metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
    else:
        metric_names = list(_DEFAULT_VS_METRICS)

    # Validate metric names against registry
    available = set(list_metrics())
    invalid = [m for m in metric_names if m not in available]
    if invalid:
        raise HTTPException(
            status_code=404,
            detail=f"unknown metrics: {invalid}. Available: {sorted(available)}",
        )

    try:
        result = vs_compare(metric_names, season, p1, p2)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"compute failed: {exc}")

    return VSCompareResponse(
        player_1=p1,
        player_2=p2,
        season=season,
        metrics=result,
    )
