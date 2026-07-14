"""NBACore v8 §2 Layer 3 — /teams router (pure orchestration).

All data fetched via data_layer. This router contains NO SQL,
NO pandas, NO computation — only request shaping + data_layer calls.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.api.schemas import (
    EntityGamesResponse,
    SeasonCoverage,
    TeamEntityDetail,
)
from backend.data_layer import (
    get_league_radar_avg,
    get_team_radar,
    get_team_ratios,
    get_team_scoring_trend,
    get_team_splits,
    get_team_standings,
    get_team_stats_per_game,
    get_teams_board,
    list_all_teams,
    get_team_history,
    get_team_legend_players,
    get_team_season_roster,
)
from backend.data_layer.entity_loader import (
    _candidate_abbrs,
    load_team_games_aggregated,
    load_team_seasons,
    season_label,
)

router = APIRouter(prefix="/teams", tags=["teams"])

logger = logging.getLogger("nbacore.api.teams")


class TeamInfo(BaseModel):
    team_abbr: str
    team_name: str | None = None
    is_active: bool | None = None


class TeamListResponse(BaseModel):
    teams: list[TeamInfo]
    total: int


class TeamBoardResponse(BaseModel):
    season: int
    groups: list[dict]


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


@router.get("/board", response_model=TeamBoardResponse)
def get_teams_board_endpoint(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> TeamBoardResponse:
    """v8 Teams board — teams grouped by division, sorted by win_pct within division.

    Each division group carries its conference and a list of teams with
    regular-season W-L, win_pct, and a made_playoffs flag (only True when the
    season actually carries playoff data).
    """
    try:
        groups = get_teams_board(season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TeamBoardResponse(season=season, groups=groups)


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


@router.get("/{team_abbr}/detail", response_model=TeamEntityDetail)
def get_team_entity_detail(
    team_abbr: str,
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> TeamEntityDetail:
    """v8 Entity Detail — full team page: standings + stats + radar + trend + seasons."""
    abbr = team_abbr.upper()
    cand = _candidate_abbrs(abbr)

    try:
        standings = get_team_standings(season) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("team standings failed for %s s%s: %s", abbr, season, exc)
        standings = []
    st_row = next((r for r in standings if r.get("team_abbr") in cand), {}) or {}

    try:
        stats = get_team_stats_per_game(season) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("team stats failed for %s s%s: %s", abbr, season, exc)
        stats = []
    stats_row = next((r for r in stats if r.get("team_abbr") in cand), {}) or {}

    try:
        radar = get_team_radar(abbr, season) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("team radar failed for %s s%s: %s", abbr, season, exc)
        radar = {}

    try:
        trend = get_team_scoring_trend(abbr) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("team trend failed for %s: %s", abbr, exc)
        trend = []

    team_name = None
    try:
        all_teams = list_all_teams()
        t = next((t for t in all_teams if t.get("team_abbr") in cand), None)
        team_name = t.get("team_name") if t else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("team name lookup failed for %s: %s", abbr, exc)

    seasons = [
        {"season": s, "label": season_label(s), "has_data": True}
        for s in load_team_seasons(abbr)
    ]
    return TeamEntityDetail(
        team_abbr=abbr,
        team_name=team_name,
        season=season,
        standings=st_row,
        stats=stats_row,
        radar=radar,
        trend=trend,
        seasons=seasons,
    )


@router.get("/{team_abbr}/games", response_model=EntityGamesResponse)
def get_team_games(
    team_abbr: str,
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    granularity: str = Query("month", pattern="^(season|month|week|game)$", description="Grouping granularity"),
) -> EntityGamesResponse:
    """v8 Entity Detail — team's games for a season, grouped by granularity."""
    abbr = team_abbr.upper()
    try:
        agg = load_team_games_aggregated(abbr, season, granularity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return EntityGamesResponse(
        entity_type="team",
        entity_id=abbr,
        season=season,
        granularity=granularity,
        groups=agg["groups"],
        totals=agg["totals"],
    )


class TeamHistoryResponse(BaseModel):
    team_abbr: str
    data: list[dict]
    count: int


class TeamLegendResponse(BaseModel):
    team_abbr: str
    data: list[dict]
    count: int


@router.get("/{team_abbr}/history", response_model=TeamHistoryResponse)
def get_team_history_endpoint(team_abbr: str) -> TeamHistoryResponse:
    """Get team historical season data including W-L records, points, rebounds, assists.

    Returns yearly summaries ordered by season descending.
    """
    abbr = team_abbr.upper()
    try:
        data = get_team_history(abbr)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TeamHistoryResponse(
        team_abbr=abbr,
        data=data,
        count=len(data),
    )


@router.get("/{team_abbr}/legends", response_model=TeamLegendResponse)
def get_team_legends_endpoint(
    team_abbr: str,
    limit: int = Query(15, ge=1, le=50, description="Maximum number of players"),
) -> TeamLegendResponse:
    """Get legendary players for a team based on career totals and achievements.

    Players are ranked by a composite score combining points, rebounds, assists,
    steals, blocks, All-Star selections, and MVP awards.
    """
    abbr = team_abbr.upper()
    try:
        data = get_team_legend_players(abbr, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TeamLegendResponse(
        team_abbr=abbr,
        data=data,
        count=len(data),
    )


class TeamRosterResponse(BaseModel):
    team_abbr: str
    season: int
    data: list[dict]
    count: int


@router.get("/{team_abbr}/roster/{season}", response_model=TeamRosterResponse)
def get_team_season_roster_endpoint(
    team_abbr: str,
    season: int,
) -> TeamRosterResponse:
    """Get team roster for a specific season.

    Returns players who played for the team in the given season,
    sorted by games started then games played.
    """
    abbr = team_abbr.upper()
    try:
        data = get_team_season_roster(abbr, season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TeamRosterResponse(
        team_abbr=abbr,
        season=season,
        data=data,
        count=len(data),
    )
