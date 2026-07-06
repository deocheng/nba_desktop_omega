"""NBACore v8 §2 Layer 3 — /players router (pure orchestration).

All data fetched via metric_engine wrappers. This router contains NO SQL,
NO pandas, NO computation — only request shaping + metric_engine calls.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.api.schemas import (
    PlayerBio,
    PlayerDetailResponse,
    PlayerSearchResponse,
)
from backend.services.metric_engine import (
    get_available_seasons,
    get_player_bios,
    list_metrics,
    player_metrics_dict,
    search_players_by_name,
)
from backend.services.growth_report import build_growth_report

router = APIRouter(prefix="/players", tags=["players"])

# Default metrics shown on player detail page.
# These are metric names registered in the engine; if any are missing from
# the registry, they're filtered out at runtime (defensive).
_DEFAULT_PLAYER_METRICS = [
    "pts_per_game",
    "reb_per_game",
    "ast_per_game",
    "true_shooting_pct",
    "fantasy_points",
]


@router.get("/seasons")
def list_seasons() -> list[int]:
    """List available seasons from fact_player_season_stats (descending)."""
    return get_available_seasons("fact_player_season_stats")


@router.get("", response_model=PlayerSearchResponse)
def search_players(
    name: str = Query(..., min_length=2, description="Player name search (>= 2 chars)"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
) -> PlayerSearchResponse:
    """Search players by name (case-insensitive)."""
    try:
        rows = search_players_by_name(name, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PlayerSearchResponse(
        players=[PlayerBio.from_row(r) for r in rows],
        count=len(rows),
    )


@router.get("/{player_id}", response_model=PlayerDetailResponse)
def get_player_detail(
    player_id: str,
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> PlayerDetailResponse:
    """Get player bio + default metrics for a season."""
    bios = get_player_bios([player_id])
    if not bios:
        raise HTTPException(
            status_code=404,
            detail=f"player {player_id!r} not found in dim_players",
        )

    bio = PlayerBio.from_row(bios[0])

    # Filter default metrics to those actually registered (defensive)
    available = set(list_metrics())
    metric_names = [m for m in _DEFAULT_PLAYER_METRICS if m in available]

    try:
        metrics_dict = player_metrics_dict(metric_names, season, player_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"compute failed: {exc}")

    return PlayerDetailResponse(bio=bio, season=season, metrics=metrics_dict)


class GrowthReportResponse(BaseModel):
    player_id: str
    bio: dict
    seasons: list[dict]
    positions: list[dict]
    milestones: list[dict]


@router.get("/{player_id}/growth", response_model=GrowthReportResponse)
def get_player_growth(player_id: str) -> GrowthReportResponse:
    """Get a player's career growth report.

    Includes bio info, per-season trajectory, position breakdown,
    and career milestones.
    """
    try:
        report = build_growth_report(player_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not report or not report.get("bio"):
        raise HTTPException(
            status_code=404,
            detail=f"player {player_id!r} not found",
        )
    return GrowthReportResponse(**report)
