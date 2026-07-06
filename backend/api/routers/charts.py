"""NBACore v8 §2 Layer 3 — /charts router (pure orchestration).

All data fetched via data_layer or metric_engine. This router contains
NO SQL, NO pandas, NO computation — only request shaping + data calls.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.data_layer import (
    compute_box_stats,
    get_late_clock_player_stats,
    get_late_clock_team_stats,
    get_player_advanced,
    get_player_ratios,
    get_player_shooting,
    get_scoring_distribution,
    get_team_radar,
    get_team_ratios,
    get_team_scoring_trend,
    get_team_standings,
    get_team_stats_per_game,
    list_tables,
)
from backend.services.metric_engine import get_player_bios, player_metrics_dict

router = APIRouter(prefix="/charts", tags=["charts"])

_ALLOWED_ADVANCED_SORTS = {
    "per", "ts_percent", "usg_percent", "ast_percent",
    "tov_percent", "stl_percent", "blk_percent",
    "bpm", "vorp", "ws", "ows", "dws",
}

_DEFAULT_COMPARISON_METRICS = [
    "pts_per_game",
    "reb_per_game",
    "ast_per_game",
    "stl_per_game",
    "blk_per_game",
    "true_shooting_pct",
    "usg_pct",
    "vorp",
]


class LeagueScoringResponse(BaseModel):
    season: int
    data: list[dict]


class ScoringTrendResponse(BaseModel):
    team: str
    data: list[dict]


class TeamRadarResponse(BaseModel):
    team: str
    season: int
    data: dict


class TeamComparisonResponse(BaseModel):
    teams: dict
    season: int


class TeamStandingsChartResponse(BaseModel):
    season: int
    data: list[dict]


class OffenseDefenseResponse(BaseModel):
    season: int
    data: list[dict]


class PlayerComparisonResponse(BaseModel):
    players: dict
    season: int


class ScoringDistributionResponse(BaseModel):
    box_stats: dict
    total_players: int
    season: int


class TeamRatiosChartResponse(BaseModel):
    season: int
    data: list[dict]


class PlayerAdvancedResponse(BaseModel):
    season: int
    data: list[dict]
    sort_by: str


class ShootingBreakdownResponse(BaseModel):
    season: int
    data: list[dict]


class LateClockTeamResponse(BaseModel):
    season: int
    data: list[dict]


class LateClockPlayerResponse(BaseModel):
    season: int
    data: list[dict]


class PlayerRatiosChartResponse(BaseModel):
    season: int
    data: list[dict]


class RecordsPieResponse(BaseModel):
    data: list[dict]


@router.get("/league-scoring", response_model=LeagueScoringResponse)
def get_league_scoring(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> LeagueScoringResponse:
    """League scoring leaders (bar chart data)."""
    try:
        from backend.data_layer import get_player_per_game
        rows = get_player_per_game(season, limit=50, sort_by="pts")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LeagueScoringResponse(season=season, data=rows)


@router.get("/scoring-trend", response_model=ScoringTrendResponse)
def get_scoring_trend_chart(
    team: str = Query(..., min_length=2, max_length=5, description="Team abbreviation"),
) -> ScoringTrendResponse:
    """Team scoring trend across multiple seasons."""
    try:
        rows = get_team_scoring_trend(team)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ScoringTrendResponse(team=team.upper(), data=rows)


@router.get("/team-radar", response_model=TeamRadarResponse)
def get_team_radar_chart(
    team: str = Query(..., min_length=2, max_length=5, description="Team abbreviation"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> TeamRadarResponse:
    """Team radar chart data."""
    try:
        data = get_team_radar(team, season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"No radar data for team {team!r} in season {season}",
        )
    return TeamRadarResponse(team=team.upper(), season=season, data=data)


@router.get("/team-comparison", response_model=TeamComparisonResponse)
def get_team_comparison(
    team1: str = Query(..., min_length=2, max_length=5, description="Team 1 abbreviation"),
    team2: str = Query(..., min_length=2, max_length=5, description="Team 2 abbreviation"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> TeamComparisonResponse:
    """Compare two teams via radar chart data."""
    try:
        data1 = get_team_radar(team1, season)
        data2 = get_team_radar(team2, season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not data1:
        raise HTTPException(
            status_code=404,
            detail=f"No data for team {team1!r} in season {season}",
        )
    if not data2:
        raise HTTPException(
            status_code=404,
            detail=f"No data for team {team2!r} in season {season}",
        )
    return TeamComparisonResponse(
        teams={team1.upper(): data1, team2.upper(): data2},
        season=season,
    )


@router.get("/team-standings", response_model=TeamStandingsChartResponse)
def get_team_standings_chart(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> TeamStandingsChartResponse:
    """Team standings data for chart visualization."""
    try:
        rows = get_team_standings(season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TeamStandingsChartResponse(season=season, data=rows)


@router.get("/offense-defense", response_model=OffenseDefenseResponse)
def get_offense_defense(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> OffenseDefenseResponse:
    """Offensive vs defensive points per game (scatter plot)."""
    try:
        rows = get_team_stats_per_game(season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return OffenseDefenseResponse(season=season, data=rows)


@router.get("/player-comparison", response_model=PlayerComparisonResponse)
def get_player_comparison(
    p1: str = Query(..., min_length=2, description="Player 1 ID"),
    p2: str = Query(..., min_length=2, description="Player 2 ID"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> PlayerComparisonResponse:
    """Compare two players via radar chart metrics."""
    bios_list = get_player_bios([p1, p2])
    bios = {b["player_id"]: b for b in bios_list}

    if p1 not in bios:
        raise HTTPException(
            status_code=404,
            detail=f"Player {p1!r} not found",
        )
    if p2 not in bios:
        raise HTTPException(
            status_code=404,
            detail=f"Player {p2!r} not found",
        )

    try:
        metrics1 = player_metrics_dict(_DEFAULT_COMPARISON_METRICS, season, p1)
        metrics2 = player_metrics_dict(_DEFAULT_COMPARISON_METRICS, season, p2)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"compute failed: {exc}")

    return PlayerComparisonResponse(
        players={
            p1: {
                "bio": {
                    "player_name": bios[p1].get("full_name") or bios[p1].get("player_name"),
                    "position": bios[p1].get("position"),
                },
                "metrics": metrics1,
            },
            p2: {
                "bio": {
                    "player_name": bios[p2].get("full_name") or bios[p2].get("player_name"),
                    "position": bios[p2].get("position"),
                },
                "metrics": metrics2,
            },
        },
        season=season,
    )


@router.get("/scoring-distribution", response_model=ScoringDistributionResponse)
def get_scoring_distribution_chart(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    min_games: int = Query(10, ge=0, le=82, description="Minimum games played to qualify"),
) -> ScoringDistributionResponse:
    """Player scoring distribution (box plot data)."""
    try:
        rows = get_scoring_distribution(season, min_games)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    pts_values = [float(r["pts"]) for r in rows if r.get("pts") is not None]
    box_stats = compute_box_stats(pts_values)

    return ScoringDistributionResponse(
        box_stats=box_stats,
        total_players=len(rows),
        season=season,
    )


@router.get("/team-ratios", response_model=TeamRatiosChartResponse)
def get_team_ratios_chart(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> TeamRatiosChartResponse:
    """Team ratio stats (AST/TOV, STL/PF)."""
    try:
        rows = get_team_ratios(season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TeamRatiosChartResponse(season=season, data=rows)


@router.get("/player-advanced", response_model=PlayerAdvancedResponse)
def get_player_advanced_chart(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    limit: int = Query(30, ge=1, le=200, description="Max players (capped at 200)"),
    sort_by: str = Query("per", description="Sort column (whitelist validated)"),
) -> PlayerAdvancedResponse:
    """Player advanced metrics ranking."""
    sort_key = sort_by.lower().strip()
    if sort_key not in _ALLOWED_ADVANCED_SORTS:
        sort_key = "per"

    try:
        rows = get_player_advanced(season, limit, sort_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PlayerAdvancedResponse(season=season, data=rows, sort_by=sort_key)


@router.get("/shooting-breakdown", response_model=ShootingBreakdownResponse)
def get_shooting_breakdown(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    limit: int = Query(50, ge=1, le=100, description="Max players (capped at 100)"),
) -> ShootingBreakdownResponse:
    """Player shooting breakdown by distance zone."""
    try:
        rows = get_player_shooting(season, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ShootingBreakdownResponse(season=season, data=rows)


@router.get("/late-clock-team", response_model=LateClockTeamResponse)
def get_late_clock_team(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> LateClockTeamResponse:
    """Team late shot clock stats (last 4 seconds)."""
    try:
        rows = get_late_clock_team_stats(season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LateClockTeamResponse(season=season, data=rows)


@router.get("/late-clock-player", response_model=LateClockPlayerResponse)
def get_late_clock_player(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    min_shots: int = Query(50, ge=0, description="Minimum total shots to qualify"),
) -> LateClockPlayerResponse:
    """Player late shot clock stats (last 4 seconds)."""
    try:
        rows = get_late_clock_player_stats(season, min_shots)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LateClockPlayerResponse(season=season, data=rows)


@router.get("/player-ratios", response_model=PlayerRatiosChartResponse)
def get_player_ratios_chart(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    min_games: int = Query(10, ge=0, le=82, description="Minimum games played to qualify"),
) -> PlayerRatiosChartResponse:
    """Player ratio stats (AST/TOV, STL/PF)."""
    try:
        rows = get_player_ratios(season, min_games)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PlayerRatiosChartResponse(season=season, data=rows)


@router.get("/records-pie", response_model=RecordsPieResponse)
def get_records_pie() -> RecordsPieResponse:
    """Database table record counts (pie chart)."""
    try:
        rows = list_tables()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return RecordsPieResponse(data=rows)
