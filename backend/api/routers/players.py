"""NBACore v8 §2 Layer 3 — /players router (pure orchestration).

All data fetched via metric_engine wrappers. This router contains NO SQL,
NO pandas, NO computation — only request shaping + metric_engine calls.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel

from backend.api.schemas import (
    CareerDefenseResponse,
    EntityGamesResponse,
    PlayerBio,
    PlayerDetailResponse,
    PlayerEntityDetail,
    PlayerSearchResponse,
    SeasonCoverage,
    ShootingProfileResponse,
)
from backend.services.metric_engine import (
    get_available_seasons,
    get_player_bios,
    list_metrics,
    player_metrics_dict,
    search_players_by_name,
)
from backend.services.growth_report import build_growth_report
from backend.services.player_profile import get_career_defense, get_shooting_profile
from backend.data_layer.entity_loader import (
    load_player_games_aggregated,
    load_player_seasons,
    season_label,
)

router = APIRouter(prefix="/players", tags=["players"])

logger = logging.getLogger("nbacore.api.players")

# Default metrics shown on player detail page.
# These are metric names registered in the engine; if any are missing from
# the registry, they're filtered out at runtime (defensive).
# v8.1 §3.1/§8: ORB, DRB, AST/TO, DAE, Team Scoring Share added.
_DEFAULT_PLAYER_METRICS = [
    "pts_per_game",
    "reb_per_game",
    "ast_per_game",
    "orb_per_game",
    "drb_per_game",
    "ast_to_ratio",
    "def_activity_efficiency",
    "team_scoring_share",
    "true_shooting_pct",
    "fantasy_points",
]


@router.get("/seasons")
def list_seasons() -> list[int]:
    """List available seasons from fact_player_season_stats (descending)."""
    return get_available_seasons("fact_player_season_stats")


@router.get("/headshots/{player_id}")
def get_player_headshot(player_id: str):
    """Serve a player's local headshot image from the 12TB store.

    Only returns the file when ``headshot_status = 'ok'`` (i.e. a real image was
    scraped and persisted). Otherwise 404 — the frontend falls back to initials.
    Reuses ``get_player_bios`` (no raw SQL in this router, per Layer-3 contract).
    """
    bios = get_player_bios([player_id])
    if not bios:
        raise HTTPException(status_code=404, detail=f"player {player_id!r} not found")
    row = bios[0]
    path = row.get("headshot_path")
    status = row.get("headshot_status")
    if not path or status != "ok":
        raise HTTPException(status_code=404, detail="headshot not available")
    p = Path(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="headshot file missing")
    return FileResponse(str(p))


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


@router.get("/{player_id}/shooting-profile", response_model=ShootingProfileResponse)
def get_shooting_profile_endpoint(player_id: str) -> ShootingProfileResponse:
    """v8.1 §7/§10.2 — per-season shooting zone profile evolution."""
    try:
        return ShootingProfileResponse(**get_shooting_profile(player_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{player_id}/career-defense", response_model=CareerDefenseResponse)
def get_career_defense_endpoint(player_id: str) -> CareerDefenseResponse:
    """v8.1 §9 — career defensive totals (STL/BLK/PF/ORB/DRB)."""
    try:
        return CareerDefenseResponse(**get_career_defense(player_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class GrowthReportResponse(BaseModel):
    player_id: str
    bio: dict
    seasons: list[dict]
    positions: list[dict]
    milestones: list[dict]
    shooting: list[dict] = []


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


@router.get("/{player_id}/detail", response_model=PlayerEntityDetail)
def get_player_entity_detail(
    player_id: str,
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    season_type: str = Query("Regular", description="Regular | Playoffs | PlayIn"),
) -> PlayerEntityDetail:
    """v8 Entity Detail — full player page: bio + metrics + shooting + defense + intel + seasons."""
    bios = get_player_bios([player_id])
    if not bios:
        raise HTTPException(status_code=404, detail=f"player {player_id!r} not found in dim_players")

    bio = dict(bios[0])
    available = set(list_metrics())
    metric_names = [m for m in _DEFAULT_PLAYER_METRICS if m in available]

    metrics: dict = {}
    shooting: dict = {}
    defense: dict = {}
    intelligence: dict = {}
    try:
        metrics = player_metrics_dict(metric_names, season, player_id)
    except Exception as exc:  # noqa: BLE001 — defensive: partial detail still useful
        logger.warning("player metrics failed for %s s%s: %s", player_id, season, exc)
    try:
        shooting = get_shooting_profile(player_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("shooting profile failed for %s: %s", player_id, exc)
    try:
        defense = get_career_defense(player_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("career defense failed for %s: %s", player_id, exc)
    try:
        from backend.api.routers.intelligence import get_player_intelligence
        intelligence = get_player_intelligence(player_id, season, season_type).model_dump()
    except Exception as exc:  # noqa: BLE001
        logger.warning("intelligence failed for %s s%s: %s", player_id, season, exc)

    seasons = [
        {"season": s, "label": season_label(s), "has_data": True}
        for s in load_player_seasons(player_id)
    ]
    return PlayerEntityDetail(
        bio=bio,
        season=season,
        metrics=metrics,
        shooting=shooting,
        defense=defense,
        intelligence=intelligence,
        seasons=seasons,
    )


@router.get("/{player_id}/games", response_model=EntityGamesResponse)
def get_player_games(
    player_id: str,
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    granularity: str = Query("month", pattern="^(season|month|week|game)$", description="Grouping granularity"),
) -> EntityGamesResponse:
    """v8 Entity Detail — player's games for a season, grouped by granularity."""
    try:
        agg = load_player_games_aggregated(player_id, season, granularity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return EntityGamesResponse(
        entity_type="player",
        entity_id=player_id,
        season=season,
        granularity=granularity,
        groups=agg["groups"],
        totals=agg["totals"],
    )
