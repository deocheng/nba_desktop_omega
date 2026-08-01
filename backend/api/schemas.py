"""NBACore v8 §2 Layer 3 — Pydantic request/response schemas.

Pure data contracts. No computation, no methods beyond simple validators.
All numeric values come from metric_engine — schemas just shape them.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.services.workspace_engine.models import LOCAL_OWNER_ID


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
    # 增量：本地头像（与 PlayerBio 一致；前端用于统一渲染头像 + 首字母降级）
    headshot_path: str | None = None       # 12TB 盘绝对路径（status='ok' 时存在）
    headshot_status: str | None = None     # NULL/ok/missing/failed


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
    # 增量：球员本人绰号（见 sql/006_add_player_nickname.sql；多名时为逗号分隔列表）
    nickname: str | None = None
    # 增量：本地头像（headshot）落盘信息（见 docs/ARCH_headshots_incremental.md）
    headshot_path: str | None = None       # 12TB 盘绝对路径（status='ok' 时存在）
    headshot_status: str | None = None     # NULL/ok/missing/failed
    # 增量：bio_ext 7 维度（见 sql/007_add_player_bio_ext.sql）
    aba_debut: str | None = None           # ABA 首秀日期（ISO）；NULL=无 ABA
    died: str | None = None                # 离世日期（ISO）；NULL=在世/未知
    hof_inducted_year: int | None = None   # 名人堂入选年份；NULL=非名人堂
    hof_as: str | None = None              # 入选身份 Player/Coach/Contributor
    is_hall_of_famer: bool | None = None   # 是否名人堂（派生自 hof_inducted_year）
    career_length_years: int | None = None # 生涯长度（年）
    relatives: str | None = None           # 亲属文本（逗号/分号分隔）
    jersey_numbers: list[str] | None = None  # 生涯球衣号码（去重数组）
    career_honors_text: list[str] | None = None  # 生涯荣誉清单（去重数组，展示镜像）

    @classmethod
    def from_row(cls, row: dict) -> "PlayerBio":
        """Build from a dim_players row (handles date/datetime → str)."""
        bd = row.get("birth_date")
        bd_str = bd.isoformat() if bd is not None else None
        aba = row.get("aba_debut")
        aba_str = aba.isoformat() if aba is not None else None
        died = row.get("died")
        died_str = died.isoformat() if died is not None else None
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
            nickname=row.get("nickname"),
            headshot_path=row.get("headshot_path"),
            headshot_status=row.get("headshot_status"),
            aba_debut=aba_str,
            died=died_str,
            hof_inducted_year=row.get("hof_inducted_year"),
            hof_as=row.get("hof_as"),
            is_hall_of_famer=row.get("is_hall_of_famer"),
            career_length_years=row.get("career_length_years"),
            relatives=row.get("relatives"),
            jersey_numbers=row.get("jersey_numbers"),
            career_honors_text=row.get("career_honors_text"),
        )


class PlayerSearchResponse(BaseModel):
    players: list[PlayerBio]
    count: int


# ── bio_ext 荣誉（见 sql/007_add_player_bio_ext.sql / common/player_bio_ext.py）──

class PlayerHonor(BaseModel):
    """A single normalized career honor (from player_career_honors)."""
    player_id: str
    honor_raw: str                         # 原始文本: "16x All Star" / "1983 NBA Champ"
    honor_type: str                        # 归一化枚举（见 ARCH §4.1）
    honor_count: int | None = None         # "16x"→16；无次数→None
    honor_year: int | None = None          # "1983" / "1993"；无→None
    honor_detail: str | None = None        # 补充: HoF "Player" / NBA 75th "Team"


class PlayerHonorsResponse(BaseModel):
    """Response for GET /players/{id}/honors."""
    player_id: str
    honors: list[PlayerHonor] = []


class PlayerDetailResponse(BaseModel):
    bio: PlayerBio
    season: int
    metrics: dict[str, float]  # {metric_name: value}


# ── v8.1 §7/§10.2 Shooting Profile ──

class ShootingZone(BaseModel):
    zone: str
    fg_pct: float | None = None
    fga_rate: float | None = None


class ShootingSeason(BaseModel):
    season: int | None = None
    team: str | None = None
    zones: list[ShootingZone]


class ShootingProfileResponse(BaseModel):
    player_id: str
    latest_season: int | None = None
    seasons: list[ShootingSeason]


# ── v8.1 §9 Career Defensive Summary ──

class CareerDefenseResponse(BaseModel):
    player_id: str
    found: bool = True
    seasons: int | None = None
    total_games: int | None = None
    total_steals: int | None = None
    total_blocks: int | None = None
    total_fouls: int | None = None
    total_offensive_rebounds: int | None = None
    total_defensive_rebounds: int | None = None
    stocks: int | None = None
    stocks_per_game: float | None = None
    steals_per_game: float | None = None
    blocks_per_game: float | None = None
    def_activity_efficiency: float | None = None


# ── v8.2 Intelligence Layer ──

class DnaScores(BaseModel):
    """Player DNA — 7 identity dimensions on a 0-100 scale."""
    scoring: float
    playmaking: float
    defense: float
    rebounding: float
    efficiency: float
    durability: float
    leadership: float


class AvailabilityInfo(BaseModel):
    """Games-played / minutes availability context."""
    team: str | None = None
    games: int | None = None
    team_games: float | None = None
    availability: float | None = None
    minutes: float | None = None
    team_minutes: float | None = None
    minutes_share: float | None = None


class ZoneProfile(BaseModel):
    """Shot-zone frequency + efficiency (0-1 each)."""
    frequency: float
    efficiency: float


class IntelligenceResponse(BaseModel):
    player_id: str
    season: int
    season_type: str
    role: str
    dna: DnaScores
    availability: AvailabilityInfo
    scoring_profile: dict[str, ZoneProfile]


# ── v8.3.1 Workspace Core ──

class WorkspaceChartResponse(BaseModel):
    """A single chart node inside a workspace."""
    id: int
    workspace_id: int
    name: str
    chart_config: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class WorkspaceResponse(BaseModel):
    """Full workspace projection (PRD v8.3.1 §5.1 / §11)."""
    id: int
    name: str
    owner_id: int
    description: str = ""
    status: str = "active"
    datasets: list[int] = Field(default_factory=list)
    formulas: list[int] = Field(default_factory=list)
    charts: list[WorkspaceChartResponse] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class WorkspaceCreate(BaseModel):
    """Create payload (PRD v8.3.1 §11)."""
    name: str
    owner_id: int = LOCAL_OWNER_ID
    description: str = ""
    status: str = "active"


class WorkspaceUpdate(BaseModel):
    """Patch payload — all fields optional (PRD v8.3.1 §11)."""
    name: str | None = None
    description: str | None = None
    status: str | None = None


class WorkspaceDatasetLink(BaseModel):
    dataset_id: int


class WorkspaceFormulaLink(BaseModel):
    formula_id: int


class WorkspaceChartCreate(BaseModel):
    name: str = "chart"
    chart_config: dict = Field(default_factory=dict)


# ── Formula Presets ──

class FormulaPreset(BaseModel):
    """A predefined NBA analysis formula."""
    id: int
    name: str
    description: str
    expression: str
    category: str


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
    # 增量：本地头像（与 PlayerBio 一致；前端用于统一渲染头像 + 首字母降级）
    headshot_path: str | None = None       # 12TB 盘绝对路径（status='ok' 时存在）
    headshot_status: str | None = None     # NULL/ok/missing/failed


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


# ── v8 Entity Detail (player / team dedicated pages) ──

class GameRow(BaseModel):
    """A single game in an entity's schedule (with context)."""
    game_id: str
    game_date: str | None = None
    opponent: str | None = None
    is_home: bool = False
    result: str | None = None  # 'W' | 'L' | 'T' | None
    pts: float | None = None


class GameAggregate(BaseModel):
    """Aggregated stats for a group of games (or the full season)."""
    gp: int = 0
    pts: float | None = None
    fg_pct: float | None = None


class GameGroup(BaseModel):
    """One aggregation bucket (a season / month / ISO week / single game)."""
    key: str
    label: str
    games: list[GameRow] = []
    aggregate: GameAggregate


class EntityGamesResponse(BaseModel):
    """Response for /players|teams/{id}/games — games grouped by granularity."""
    entity_type: str
    entity_id: str
    season: int
    granularity: str
    groups: list[GameGroup] = []
    totals: GameAggregate


class SeasonCoverage(BaseModel):
    """A season an entity actually has data for (empty seasons are skipped)."""
    season: int
    label: str
    has_data: bool = True


class PlayerEntityDetail(BaseModel):
    """Full player entity detail (bio + metrics + shooting + defense + intel)."""
    bio: dict
    season: int
    metrics: dict
    shooting: dict
    defense: dict
    intelligence: dict
    seasons: list[SeasonCoverage]


class TeamEntityDetail(BaseModel):
    """Full team entity detail (standings / stats / radar / trend)."""
    team_abbr: str
    team_name: str | None = None
    season: int
    standings: dict
    stats: dict
    radar: dict
    trend: list[dict] = []
    seasons: list[SeasonCoverage]
