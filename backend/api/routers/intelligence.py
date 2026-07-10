"""NBACore v8.2 §19 — /players/{id}/intelligence router (pure orchestration).

Returns the Player Intelligence object: role, DNA, availability, scoring
profile. All computation is delegated to the Intelligence Engine; this router
only shapes the request + response. No pandas / SQL / compute logic here
(v8 §2 Layer 3 mandate).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.api.schemas import (
    AvailabilityInfo,
    DnaScores,
    IntelligenceResponse,
    ZoneProfile,
)
from backend.services.intelligence_engine import (
    classify_role,
    compute_availability,
    compute_dna,
    load_player_intel,
    normalize_season_type,
    scoring_profile,
)
from backend.services.metric_engine import get_available_seasons

router = APIRouter(prefix="/players", tags=["intelligence"])


@router.get("/{player_id}/intelligence", response_model=IntelligenceResponse)
def get_player_intelligence(
    player_id: str,
    season: int | None = Query(None, description="NBA season; defaults to latest available"),
    season_type: str = Query("Regular", description="Regular | Playoffs | PlayIn"),
):
    st = normalize_season_type(season_type)
    if season is None:
        seasons = get_available_seasons()
        if not seasons:
            raise HTTPException(status_code=503, detail="No seasons available")
        season = seasons[0]

    rows = load_player_intel(season, st, [player_id])
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No {st} intelligence data for player {player_id} in season {season}",
        )
    row = rows[0]

    av = compute_availability(season, [player_id], st).get(player_id, {})
    av_score = av.get("availability")
    role = classify_role(row)
    dna = compute_dna(row, av_score if av_score is not None else 1.0)
    profile = scoring_profile(player_id, season, st)

    return IntelligenceResponse(
        player_id=player_id,
        season=season,
        season_type=st,
        role=role,
        dna=DnaScores(**dna),
        availability=AvailabilityInfo(
            team=av.get("team"),
            games=av.get("g"),
            team_games=av.get("team_games"),
            availability=av.get("availability"),
            minutes=av.get("mp"),
            team_minutes=av.get("team_minutes"),
            minutes_share=av.get("minutes_share"),
        ),
        scoring_profile={z: ZoneProfile(**v) for z, v in profile.items()},
    )
