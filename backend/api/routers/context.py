"""NBACore v8 §2 Layer 3 — /context router (pure orchestration).

Context System endpoints: similar players, role evolution, trend analysis.
All computation delegated to context_engine (layer 2.5), which uses Metric Engine.
This router contains NO SQL, NO pandas, NO computation.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.api.schemas import (
    RoleEvolutionResponse,
    SimilarPlayersResponse,
    TrendResponse,
)
from backend.services.context_engine import (
    find_similar_players,
    player_role_evolution,
    player_trend,
)
from backend.services.metric_engine import list_metrics

router = APIRouter(prefix="/context", tags=["context"])

_DEFAULT_SIMILAR_METRICS = [
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


@router.get("/similar", response_model=SimilarPlayersResponse)
def get_similar_players(
    player_id: str = Query(..., description="Target BBR player_id"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    metrics: str | None = Query(
        None,
        description="Comma-separated metric names (default: scoring/playmaking/efficiency profile)",
    ),
    limit: int = Query(10, ge=1, le=50, description="Max similar players"),
    position_filter: bool = Query(True, description="Filter to same-position players"),
) -> SimilarPlayersResponse:
    """Find players with most similar statistical profile (cosine similarity)."""
    if metrics:
        metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
    else:
        metric_names = list(_DEFAULT_SIMILAR_METRICS)

    available = set(list_metrics())
    invalid = [m for m in metric_names if m not in available]
    if invalid:
        raise HTTPException(
            status_code=404,
            detail=f"unknown metrics: {invalid}. Available: {sorted(available)}",
        )

    try:
        results = find_similar_players(
            player_id=player_id,
            season=season,
            metric_names=metric_names,
            limit=limit,
            position_filter=position_filter,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"similar players failed: {exc}")

    return SimilarPlayersResponse(
        target_player_id=player_id,
        season=season,
        metric_count=len(metric_names),
        similar_players=[vars(p) for p in results],
        count=len(results),
    )


@router.get("/evolution", response_model=RoleEvolutionResponse)
def get_role_evolution(
    player_id: str = Query(..., description="BBR player_id"),
    seasons: str = Query(
        ...,
        description="Comma-separated season years (e.g. '2020,2021,2022,2023,2024,2025')",
    ),
    metrics: str | None = Query(
        None,
        description="Comma-separated metric names (default: core per-game + advanced)",
    ),
) -> RoleEvolutionResponse:
    """Analyze how a player's statistical role evolved across seasons."""
    season_list = [int(s.strip()) for s in seasons.split(",") if s.strip().isdigit()]
    if len(season_list) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 seasons required for evolution analysis",
        )

    if metrics:
        metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
    else:
        metric_names = list(_DEFAULT_SIMILAR_METRICS)

    available = set(list_metrics())
    invalid = [m for m in metric_names if m not in available]
    if invalid:
        raise HTTPException(
            status_code=404,
            detail=f"unknown metrics: {invalid}. Available: {sorted(available)}",
        )

    try:
        result = player_role_evolution(
            player_id=player_id,
            seasons=season_list,
            metric_names=metric_names,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"evolution analysis failed: {exc}")

    return RoleEvolutionResponse(
        player_id=result.player_id,
        seasons=result.seasons,
        metric_changes=[vars(m) for m in result.metric_changes],
        overall_shift_magnitude=result.overall_shift_magnitude,
        top_growth=result.top_growth,
        top_decline=result.top_decline,
    )


@router.get("/trend", response_model=TrendResponse)
def get_metric_trend(
    player_id: str = Query(..., description="BBR player_id"),
    metric: str = Query(..., description="Metric name"),
    seasons: str = Query(
        ...,
        description="Comma-separated season years",
    ),
) -> TrendResponse:
    """Compute linear trend + momentum for a single metric across seasons."""
    season_list = [int(s.strip()) for s in seasons.split(",") if s.strip().isdigit()]
    if not season_list:
        raise HTTPException(status_code=400, detail="At least 1 season required")

    available = set(list_metrics())
    if metric not in available:
        raise HTTPException(
            status_code=404,
            detail=f"unknown metric: {metric}. Available: {sorted(available)}",
        )

    try:
        result = player_trend(
            player_id=player_id,
            metric=metric,
            seasons=season_list,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"trend analysis failed: {exc}")

    return TrendResponse(
        player_id=result.player_id,
        metric=result.metric,
        seasons=result.seasons,
        values=result.values,
        slope=result.slope,
        intercept=result.intercept,
        r_squared=result.r_squared,
        momentum=result.momentum,
        predicted_next=result.predicted_next,
        direction=result.direction,
    )
