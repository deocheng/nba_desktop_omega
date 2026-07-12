"""NBACore v8.2-C — Career API request/response contracts (Layer 3).

Pure data contracts. No computation, no methods beyond simple validators.
All numeric values are produced by the career engine service.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from backend.services.career_engine.career_constants import (
    DEFAULT_ALGORITHM,
    DEFAULT_LIMIT,
    DEFAULT_MIN_GAMES,
    DEFAULT_MIN_SEASONS,
    DEFAULT_TOP_K,
    METRIC_PATTERN,
)


# ── Peak ──
class PeakQuery(BaseModel):
    """Validated query parameters for the peak endpoint."""

    metric: str = Field("pts_per_game", pattern=METRIC_PATTERN,
                        description="Whitelist metric")
    min_games: int = Field(DEFAULT_MIN_GAMES, ge=0, le=82,
                           description="Min games for a season to count")
    position: str | None = Field(None, description="Position filter (PG/SG/SF/PF/C)")
    era: str | None = Field(None, description="Decade filter e.g. '2010s' (P1)")
    limit: int = Field(DEFAULT_LIMIT, ge=1, le=100, description="Max rows")


class PeakRow(BaseModel):
    """One player's career-best single-season row."""

    rank: int
    player_id: str
    player_name: str | None = None
    peak_value: float | None = None
    peak_season: int | None = None
    peak_age: float | None = None
    peak_team: str | None = None
    second_value: float | None = None
    seasons_played: int = 0


# ── Age Curve ──
class AgeCurvePoint(BaseModel):
    season: int | None = None
    age: float | None = None
    value: float | None = None
    team: str | None = None


class AgeCurvePlayer(BaseModel):
    player_id: str
    player_name: str | None = None
    team_last: str | None = None
    peak_age: float | None = None
    curve: list[AgeCurvePoint] = []
    # Multi-metric overlay (N metrics × M players). curves/peak_ages keyed by metric.
    curves: dict[str, list[AgeCurvePoint]] = {}
    peak_ages: dict[str, float | None] = {}


# ── Similar Evolution ──
class SimilarQuery(BaseModel):
    """Validated query parameters for the similar-evolution endpoint."""

    metric: str = Field("pts_per_game", pattern=METRIC_PATTERN)
    top_k: int = Field(DEFAULT_TOP_K, ge=1, le=20)
    min_games: int = Field(DEFAULT_MIN_GAMES, ge=0, le=82)
    same_position: bool = Field(True)
    algorithm: str = Field(DEFAULT_ALGORITHM, pattern="^(pearson|cosine|euclidean)$")
    min_seasons: int = Field(DEFAULT_MIN_SEASONS, ge=1, le=30)


class SimilarPoint(BaseModel):
    age: float | None = None
    value: float | None = None


class SimilarTarget(BaseModel):
    player_id: str
    player_name: str | None = None
    curve: list[SimilarPoint] = []
    peak_age: float | None = None


class SimilarCandidate(BaseModel):
    player_id: str
    player_name: str | None = None
    similarity: float
    peak_age: float | None = None
    curve: list[SimilarPoint] = []


class SimilarResponse(BaseModel):
    target: SimilarTarget
    similar: list[SimilarCandidate] = []
