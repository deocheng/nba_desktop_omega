"""NBACore v8 §2 Layer 3 — /teams router (pure orchestration).

All data fetched via data_layer. This router contains NO SQL,
NO pandas, NO computation — only request shaping + data_layer calls.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.data_layer import (
    get_league_radar_avg,
    get_team_radar,
    get_team_ratios,
    get_team_scoring_trend,
    get_team_splits,
    get_team_standings,
    get_team_stats_per_game,
    list_all_teams,
)

router = APIRouter(prefix="/teams", tags=["teams"])


class TeamInfo(BaseModel):
    team_abbr: str
    team_name: str | None = None
    is_active: bool | None = None


class TeamListResponse(BaseModel):
    teams: list[TeamInfo]
    total: int


class TeamSplitsResponse(BaseModel):
    team_abbr: str
    season: int
    splits: list[dict]
    total: int


class TeamStandingsResponse(BaseModel):
    season: int
    data: list[dict]
    count: int


class TeamStatsResponse(BaseModel):
    season: int
    data: list[dict]
    count: int


class TeamRatiosResponse(BaseModel):
    season: int
    data: list[dict]
    count: int


class TeamTrendResponse(BaseModel):
    team_abbr: str
    data: list[dict]
    count: int


class TeamRadarResponse(BaseModel):
    team_abbr: str
    season: int
    data: dict


class LeagueRadarAvgResponse(BaseModel):
    season: int
    data: dict


@router.get("", response_model=TeamListResponse)
def get_teams() -> TeamListResponse:
    """List all teams with abbreviation, name, and active status."""
    try:
        rows = list_all_teams()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TeamListResponse(
        teams=[TeamInfo(**r) for r in rows],
        total=len(rows),
    )


@router.get("/{team_abbr}/splits", response_model=TeamSplitsResponse)
def get_team_splits_endpoint(
    team_abbr: str,
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> TeamSplitsResponse:
    """Get team game splits for a specific team and season."""
    try:
        rows = get_team_splits(team_abbr, season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TeamSplitsResponse(
        team_abbr=team_abbr.upper(),
        season=season,
        splits=rows,
        total=len(rows),
    )


@router.get("/standings", response_model=TeamStandingsResponse)
def get_standings(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> TeamStandingsResponse:
    """Get team standings (W/L records and advanced metrics) for a season."""
    try:
        rows = get_team_standings(season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TeamStandingsResponse(
        season=season,
        data=rows,
        count=len(rows),
    )


@router.get("/stats", response_model=TeamStatsResponse)
def get_team_stats(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> TeamStatsResponse:
    """Get team per-game stats (offensive/defensive points for scatter plot)."""
    try:
        rows = get_team_stats_per_game(season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TeamStatsResponse(
        season=season,
        data=rows,
        count=len(rows),
    )


@router.get("/ratios", response_model=TeamRatiosResponse)
def get_ratios(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> TeamRatiosResponse:
    """Get team-level AST/TOV ratio and STL/PF ratio."""
    try:
        rows = get_team_ratios(season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TeamRatiosResponse(
        season=season,
        data=rows,
        count=len(rows),
    )


@router.get("/{team_abbr}/trend", response_model=TeamTrendResponse)
def get_scoring_trend(
    team_abbr: str,
) -> TeamTrendResponse:
    """Get team scoring trend across multiple seasons."""
    try:
        rows = get_team_scoring_trend(team_abbr)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TeamTrendResponse(
        team_abbr=team_abbr.upper(),
        data=rows,
        count=len(rows),
    )


@router.get("/league-avg/radar", response_model=LeagueRadarAvgResponse)
def get_league_avg_radar(season: int = Query(..., ge=1900, le=2100)) -> LeagueRadarAvgResponse:
    """Get league average radar stats for a season."""
    try:
        data = get_league_radar_avg(season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"No league average data for season {season}",
        )
    return LeagueRadarAvgResponse(
        season=season,
        data=data,
    )


@router.get("/{team_abbr}/radar", response_model=TeamRadarResponse)
def get_team_radar_endpoint(
    team_abbr: str,
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> TeamRadarResponse:
    """Get radar chart data for a single team in a season."""
    try:
        data = get_team_radar(team_abbr, season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"No radar data for team {team_abbr!r} in season {season}",
        )
    return TeamRadarResponse(
        team_abbr=team_abbr.upper(),
        season=season,
        data=data,
    )
