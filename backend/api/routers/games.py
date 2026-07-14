"""NBACore v8 §2 Layer 3 — /games router (pure orchestration).

All data fetched via data_layer. This router contains NO SQL,
NO pandas, NO computation — only request shaping + data_layer calls.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.data_layer import (
    get_game_detail,
    get_game_player_performance,
    get_game_radar,
    get_play_by_play,
    get_quarter_stats,
    list_games,
)

router = APIRouter(prefix="/games", tags=["games"])


class GamesListResponse(BaseModel):
    games: list[dict]
    total: int
    page: int
    per_page: int
    total_pages: int


class QuarterStatsResponse(BaseModel):
    team_abbr: str
    season: int
    data: list[dict]
    count: int


class GameDetailResponse(BaseModel):
    game_id: str
    data: dict


class GameRadarResponse(BaseModel):
    game_id: str
    home_team: str | None
    away_team: str | None
    home: dict
    away: dict


class PlayByPlayResponse(BaseModel):
    game_id: str
    events: list[dict]
    count: int


class PlayerPerformanceResponse(BaseModel):
    game_id: str
    players: list[dict]
    count: int


@router.get("", response_model=GamesListResponse)
def get_games(
    season: int | None = Query(None, ge=1900, le=2100, description="NBA season filter (optional)"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    per_page: int = Query(20, ge=1, le=200, description="Items per page (max 200)"),
) -> GamesListResponse:
    """Paginated list of games."""
    try:
        rows, total = list_games(season, page, per_page)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    total_pages = (total + per_page - 1) // per_page if per_page > 0 else 0
    return GamesListResponse(
        games=rows,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get("/quarters", response_model=QuarterStatsResponse)
def get_quarter_stats_endpoint(
    team: str = Query(..., min_length=2, max_length=5, description="Team abbreviation"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    limit: int = Query(10, ge=1, le=50, description="Max games (capped at 50)"),
) -> QuarterStatsResponse:
    """Quarter-by-quarter scoring for a team's recent games."""
    try:
        rows = get_quarter_stats(team, season, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return QuarterStatsResponse(
        team_abbr=team.upper(),
        season=season,
        data=rows,
        count=len(rows),
    )


@router.get("/{game_id}/radar", response_model=GameRadarResponse)
def get_game_radar_endpoint(game_id: str) -> GameRadarResponse:
    """Get radar chart data for both teams in a single game."""
    try:
        data = get_game_radar(game_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not data:
        raise HTTPException(status_code=404, detail=f"Game {game_id!r} not found")
    return GameRadarResponse(
        game_id=str(game_id),
        home_team=data.get('home_team'),
        away_team=data.get('away_team'),
        home=data.get('home', {}),
        away=data.get('away', {}),
    )


@router.get("/{game_id}/play-by-play", response_model=PlayByPlayResponse)
def get_play_by_play_endpoint(game_id: str) -> PlayByPlayResponse:
    """Get all play-by-play events for a game."""
    try:
        events = get_play_by_play(game_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PlayByPlayResponse(
        game_id=str(game_id),
        events=events,
        count=len(events),
    )


@router.get("/{game_id}/players", response_model=PlayerPerformanceResponse)
def get_game_players_endpoint(game_id: str) -> PlayerPerformanceResponse:
    """Get aggregated player performance by period from play-by-play data."""
    try:
        players = get_game_player_performance(game_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PlayerPerformanceResponse(
        game_id=str(game_id),
        players=players,
        count=len(players),
    )


@router.get("/{game_id}", response_model=GameDetailResponse)
def get_game_detail_endpoint(game_id: str) -> GameDetailResponse:
    """Get full game detail including both teams' stats and quarter scores."""
    try:
        data = get_game_detail(game_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not data:
        raise HTTPException(status_code=404, detail=f"Game {game_id!r} not found")
    return GameDetailResponse(
        game_id=str(game_id),
        data=data,
    )
