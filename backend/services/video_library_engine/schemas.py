"""NBACore v8 — Video Library data contracts (Layer 2 / Layer 3 shared).

Pure data models. No computation, no methods beyond pydantic validators.
All numeric values (video_time, offset, etc.) are produced by the
``OffsetMapper`` (pure Python) or the engine layers this aggregation layer
orchestrates.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ───────────────────────── List / Browse ─────────────────────────

class VideoLibraryListRequest(BaseModel):
    """Filter parameters for the video library game list."""

    season: Optional[str] = None
    team: Optional[str] = None
    date: Optional[str] = None


class VideoLibraryGameRow(BaseModel):
    """One row in the video library game list (with has_video badge)."""

    game_id: str
    season: str
    teams: List[str] = Field(default_factory=list)
    date: Optional[str] = None
    score: Optional[str] = None
    has_video: bool = False
    source: Optional[str] = None


class VideoLibraryListResult(BaseModel):
    """Result envelope for the game list endpoint."""

    season: Optional[str] = None
    total: int = 0
    games: List[VideoLibraryGameRow] = Field(default_factory=list)


# ───────────────────────── Video Source (write path) ─────────────────────────

class VideoSourceRow(BaseModel):
    """A registered video source for one game (game_videos table row)."""

    id: Optional[int] = None
    gameid: str
    season: str
    source: str = "other"
    video_url: Optional[str] = None
    local_path: Optional[str] = None
    video_offset_seconds: float = 0.0
    created_at: Optional[str] = None


class UpsertVideoSourceRequest(BaseModel):
    """Request to add or update a video source for one game."""

    gameid: str = Field(..., description="Game ID matching dim_games.game_id")
    season: str = Field(..., description="NBA season, e.g. '2025'")
    source: str = Field(
        "other",
        description="'youtube' | 'local_file' | 'cloud_drive' | 'other'",
    )
    video_url: Optional[str] = None
    local_path: Optional[str] = None
    video_offset_seconds: float = Field(
        0.0, description="Seconds offset: video t=0 relative to Q1 0:00"
    )


class BulkImportRequest(BaseModel):
    """Batch upsert request for CSV / JSON bulk import."""

    items: List[UpsertVideoSourceRequest] = Field(default_factory=list)


class BulkImportResult(BaseModel):
    """Result of a bulk import operation."""

    inserted: int = 0
    updated: int = 0
    rejected: List[Dict[str, Any]] = Field(default_factory=list)


# ───────────────────────── Playback (offset mapping) ─────────────────────────

class EventTimeMark(BaseModel):
    """One entry in the precomputed timeline: event → video_time mapping.

    The frontend ``SyncController`` does binary search on ``timeline[]``
    using ``frame_index`` / ``video_time`` — NO offset or clock arithmetic
    in the frontend (v8 §11 red line).
    """

    event_index: int
    period: int
    clock_seconds: float
    frame_index: int
    video_time: float


class PlaybackResponse(BaseModel):
    """Full playback payload: video ref + replay frames + timeline + clutch.

    Returned by ``GET /video-library/play/{gameid}``. The frontend consumes
    this to render ``<video>`` + Tactics SVG + Clutch Timeline, bridged by
    ``SyncController``.
    """

    game_id: str
    season: str
    video_ref: str = ""
    video_ref_type: str = "url"
    video_offset_seconds: float = 0.0
    frames: List[dict] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)
    timeline: List[EventTimeMark] = Field(default_factory=list)
    clutch_segments: List[dict] = Field(default_factory=list)
    clutch_players: List[dict] = Field(default_factory=list)
    perspective: str = "viewer"


# ───────────────────────── P2 AI Analysis ─────────────────────────

class AnalysisSegment(BaseModel):
    """One AI-generated analysis segment (P2 placeholder structure)."""

    event_index: int = 0
    period_clock: str = ""
    commentary: str = ""


class GameAnalysis(BaseModel):
    """AI analysis result (P2 contract; v1 returns placeholder from StaticAnalyzer)."""

    game_id: str
    season: str
    summary: str = ""
    segments: List[AnalysisSegment] = Field(default_factory=list)


# ───────────────────────── Error ─────────────────────────

class VideoLibraryError(Exception):
    """Business-level error carrying the envelope ``code`` (v8 §8.5).

    Raised by the aggregation service for known, recoverable conditions.
    The router maps it to a ``{code, data, message}`` envelope with HTTP 200
    (NOT an HTTPException), keeping the frontend decision logic purely
    envelope-driven.
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
