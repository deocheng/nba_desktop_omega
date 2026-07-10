"""NBACore v8 — Clutch feature request/response schemas (Layer 3 contracts).

Pure data contracts. No computation, no methods beyond simple validators.
All numeric values are produced by the clutch engine service.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ClutchQuery(BaseModel):
    """Validated query parameters for the clutch players endpoint."""

    season: int | None = Field(
        None, description="NBA season filter; null = all seasons (incl. 2026)"
    )
    period: int = Field(4, ge=1, le=8, description="Game period (4 = regulation Q4)")
    clock_max: int = Field(300, ge=0, le=3000, description="Max clock seconds remaining")
    margin_max: int = Field(5, ge=0, le=50, description="Max |score margin|")
    metric: str = Field(
        "possessions",
        pattern="^(possessions|points)$",
        description="Ranking metric: possessions (default) | points",
    )
    min_poss: int = Field(10, ge=0, description="Min FGA threshold (HAVING filter)")
    limit: int = Field(30, ge=1, le=100, description="Max rows returned")


class ClutchPlayerResponse(BaseModel):
    """One player's aggregated clutch-time stats."""

    player_id: str | None = None
    player_name: str
    team: str | None = None
    poss: int = 0
    fgm: int = 0
    fga: int = 0
    fg_pct: float | None = None
    fgm2: int = 0
    fga2: int = 0
    fg2_pct: float | None = None
    fgm3: int = 0
    fga3: int = 0
    fg3_pct: float | None = None
    ftm: int = 0
    fta: int = 0
    ft_pct: float | None = None
    catch_shots: int | None = None
    dribble_shots: int | None = None
    dribble_coverage: float | None = None
    oreb: int = 0
    dreb: int = 0
    ast: int = 0
    stl: int = 0
    tov: int = 0
    pf: int = 0
    pts: int = 0
    net_eff: float | None = None
