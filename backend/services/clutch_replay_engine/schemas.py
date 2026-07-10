"""NBACore v8 — Fusion Clutch Replay data contracts (Layer 2 / Layer 3 shared).

Pure data models. No computation, no methods beyond pydantic validators.
All numeric values are produced by the engine layers this aggregation layer
orchestrates.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ClutchReplayRequest(BaseModel):
    """Request for a fused clutch-replay timeline of one game."""

    game_id: str = Field(..., description="br_crawler gameid (matches play_by_play.gameid)")
    season: str = Field(..., description="NBA season, e.g. '2025'")
    period: int = Field(4, ge=1, le=8, description="Clutch window period (4 = Q4)")
    clock_max: int = Field(300, ge=0, le=3000, description="Max clock seconds remaining")
    margin_max: int = Field(5, ge=0, le=50, description="Max |score margin|")
    pad_events: int = Field(2, ge=0, le=20, description="Adjacent events per side of a clutch anchor")
    frame_rate: int = Field(30, ge=1, le=60, description="Replay frame rate (fps)")


class ClutchSegmentPlayer(BaseModel):
    """A player involved in a clutch segment (note: ``playerid`` no underscore)."""

    playerid: Optional[str] = None
    player: str = ""
    team: Optional[str] = None


class ClutchSegment(BaseModel):
    """One fused highlight segment: an event-index window mapped to frame indices."""

    start_event_index: int = 0
    end_event_index: int = 0
    start_frame: int = 0
    end_frame: int = 0
    period: int = 0
    clock_start: float = 0.0
    clock_end: float = 0.0
    players: List[ClutchSegmentPlayer] = Field(default_factory=list)
    margin: int = 0


class ClutchPlayerStat(BaseModel):
    """A player's aggregated clutch-time stats for the requested game.

    Field口径 is identical to ``clutch.js`` / ``clutch_schemas.ClutchPlayerResponse``
    (player_id carries an underscore here, per the stats contract).
    """

    player_id: Optional[str] = None
    player_name: str
    team: Optional[str] = None
    poss: int = 0
    fg_pct: Optional[float] = None
    fg2_pct: Optional[float] = None
    fg3_pct: Optional[float] = None
    oreb: int = 0
    dreb: int = 0
    ast: int = 0
    stl: int = 0
    tov: int = 0
    pf: int = 0
    pts: int = 0
    catch_shots: Optional[int] = None
    dribble_shots: Optional[int] = None
    dribble_coverage: Optional[float] = None


class ClutchReplayResult(BaseModel):
    """Fused replay result: raw frames + highlight segments + sidebar players."""

    game_id: str
    season: str
    frames: List[dict] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)
    clutch_segments: List[ClutchSegment] = Field(default_factory=list)
    clutch_players: List[ClutchPlayerStat] = Field(default_factory=list)


class ClutchReplayError(Exception):
    """Business-level error carrying the envelope ``code`` (v8 §8.5).

    Raised by the aggregation service for known, recoverable conditions
    (e.g. no br_crawler replay data). The router maps it to a
    ``{code, data, message}`` envelope with HTTP 200 (NOT an HTTPException),
    keeping the frontend decision logic purely envelope-driven.
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
