"""NBACore v8 §2 Layer 3 — Pydantic request/response schemas.

Pure data contracts. No computation, no methods beyond simple validators.
All numeric values come from metric_engine — schemas just shape them.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ── Metric schemas ──

class MetricInfo(BaseModel):
    """Public metric definition (mirrors MetricSpec without the compute fn)."""
    name: str
    kind: str
    source_table: str
    required_cols: list[str]
    description: str
    min_denominator: float
    precision: int


class MetricListResponse(BaseModel):
    metrics: list[MetricInfo]
    count: int


# ── Ranking schemas ──

class RankingItem(BaseModel):
    rank: int
    player_id: str
    player_name: str | None = None
    position: str | None = None
    value: float
    percentile: float
    sample_size: int


class EvaluateResponse(BaseModel):
    metric: str
    season: int
    ascending: bool
    min_value: float | None
    rankings: list[RankingItem]
    total: int


# ── Player schemas ──

class PlayerBio(BaseModel):
    """Subset of dim_players columns safe for API response."""
    player_id: str
    player_name: str | None = None
    full_name: str | None = None
    position: str | None = None
    shoots: str | None = None
    height_display: str | None = None
    height_cm: int | None = None
    weight_lbs: int | None = None
    weight_kg: int | None = None
    birth_date: str | None = None  # ISO date string
    birth_city: str | None = None
    birth_state_country: str | None = None
    college: str | None = None
    nba_debut: str | None = None
    experience: str | None = None
    year_from: int | None = None
    year_to: int | None = None

    @classmethod
    def from_row(cls, row: dict) -> "PlayerBio":
        """Build from a dim_players row (handles date/datetime → str)."""
        bd = row.get("birth_date")
        bd_str = bd.isoformat() if bd is not None else None
        return cls(
            player_id=str(row.get("player_id", "")),
            player_name=row.get("player_name"),
            full_name=row.get("full_name"),
            position=row.get("position"),
            shoots=row.get("shoots"),
            height_display=row.get("height_display"),
            height_cm=row.get("height_cm"),
            weight_lbs=row.get("weight_lbs"),
            weight_kg=row.get("weight_kg"),
            birth_date=bd_str,
            birth_city=row.get("birth_city"),
            birth_state_country=row.get("birth_state_country"),
            college=row.get("college"),
            nba_debut=row.get("nba_debut"),
            experience=row.get("experience"),
            year_from=row.get("year_from"),
            year_to=row.get("year_to"),
        )


class PlayerSearchResponse(BaseModel):
    players: list[PlayerBio]
    count: int


class PlayerDetailResponse(BaseModel):
    bio: PlayerBio
    season: int
    metrics: dict[str, float]  # {metric_name: value}


# ── VS schemas ──

class VSCompareResponse(BaseModel):
    player_1: str
    player_2: str
    season: int
    metrics: dict[str, dict[str, float | None]]  # {metric: {"player_1": x, "player_2": y}}


# ── Batch schemas ──

class BatchOperation(BaseModel):
    type: str = Field(..., description="rank | compute | compute_many")
    metric: str | None = None
    metrics: list[str] | None = None
    season: int
    player_ids: list[str] | None = None
    ascending: bool = False
    min_value: float | None = None
    limit: int | None = None


class BatchRequest(BaseModel):
    operations: list[BatchOperation]


class BatchResponse(BaseModel):
    results: list[dict]
    count: int


# ── Context schemas ──

class SimilarPlayerItem(BaseModel):
    player_id: str
    similarity: float
    name: str
    team: str | None = None
    position: str | None = None


class SimilarPlayersResponse(BaseModel):
    target_player_id: str
    season: int
    metric_count: int
    similar_players: list[SimilarPlayerItem]
    count: int


class MetricChangeItem(BaseModel):
    metric: str
    first_value: float | None
    last_value: float | None
    absolute_change: float | None
    pct_change: float | None
    direction: str
    trend_slope: float | None


class RoleEvolutionResponse(BaseModel):
    player_id: str
    seasons: list[int]
    metric_changes: list[MetricChangeItem]
    overall_shift_magnitude: float
    top_growth: list[str]
    top_decline: list[str]


class TrendResponse(BaseModel):
    player_id: str
    metric: str
    seasons: list[int]
    values: list[float | None]
    slope: float | None
    intercept: float | None
    r_squared: float | None
    momentum: float | None
    predicted_next: float | None
    direction: str
