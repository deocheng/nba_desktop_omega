"""NBACore v8.2-C — /api/career router (pure orchestration, Layer 3).

Three endpoints (Peak / Age Curve / Similar Evolution). Pure orchestration:
it validates the request, calls the career engine, and shapes the
``{code, data, message}`` envelope. It contains NO SQL, NO pandas, and NO
computation (v8 §2 Layer 3 mandate). All read-only query SQL lives in
``career_queries``; all computation in ``career_service``.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

from backend.api.routers.career_schemas import (
    AgeCurvePlayer,
    PeakRow,
    SimilarResponse,
)
from backend.services.career_engine import career_service
from backend.services.career_engine.career_constants import (
    ALGORITHMS,
    DEFAULT_ALGORITHM,
    DEFAULT_AGE_CURVE_MIN_GAMES,
    DEFAULT_LIMIT,
    DEFAULT_MIN_GAMES,
    DEFAULT_MIN_SEASONS,
    DEFAULT_TOP_K,
    METRIC_PATTERN,
    METRIC_WHITELIST,
)

router = APIRouter(prefix="/api/career", tags=["career"])


@router.get("/peak")
def get_peak(
    metric: str = Query("pts_per_game", pattern=METRIC_PATTERN),
    min_games: int = Query(DEFAULT_MIN_GAMES, ge=0, le=82),
    position: str | None = Query(None),
    era: str | None = Query(None),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=100),
):
    """League peak ranking: career-best single-season value per player."""
    try:
        if era is not None and not re.match(r"^\d{4}s$", str(era).strip().lower()):
            raise ValueError("era must look like '2010s'")
        rows = career_service.get_peak_players(
            metric=metric, min_games=min_games,
            position=position, era=era, limit=limit,
        )
        data = [PeakRow(**r).model_dump() for r in rows]
        return {"code": 0, "data": data, "message": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface engine errors cleanly
        raise HTTPException(status_code=500, detail=f"peak failed: {exc}")


@router.get("/age-curve", response_model=dict)
def get_age_curve(
    player_ids: str = Query(..., description="comma-separated BBR ids"),
    metric: str = Query("pts_per_game", pattern=METRIC_PATTERN),
    metrics: str | None = Query(None, description="comma-separated whitelist metrics; overrides single metric"),
    min_games: int = Query(DEFAULT_AGE_CURVE_MIN_GAMES, ge=0, le=82),
):
    """Per-player (age, value) career curve for 1..N players, single or multi metric."""
    try:
        ids = [p.strip() for p in player_ids.split(",") if p.strip()]
        if not ids:
            raise ValueError("player_ids is required")
        if metrics:
            mlist = [m.strip() for m in metrics.split(",") if m.strip()]
            bad = [m for m in mlist if m not in METRIC_WHITELIST]
            if bad:
                raise ValueError(f"unknown metric(s): {bad}")
            players = career_service.get_age_curves_multi(
                player_ids=ids, metrics=mlist, min_games=min_games
            )
        else:
            players = career_service.get_age_curves(
                player_ids=ids, metric=metric, min_games=min_games
            )
        data = [AgeCurvePlayer(**p).model_dump() for p in players]
        return {"code": 0, "data": {"players": data}, "message": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"age-curve failed: {exc}")


@router.get("/similar-evolution", response_model=dict)
def get_similar_evolution(
    player_id: str = Query(..., description="target BBR id"),
    metric: str = Query("pts_per_game", pattern=METRIC_PATTERN),
    top_k: int = Query(DEFAULT_TOP_K, ge=1, le=20),
    min_games: int = Query(DEFAULT_MIN_GAMES, ge=0, le=82),
    same_position: bool = Query(True),
    algorithm: str = Query(DEFAULT_ALGORITHM, pattern="^(pearson|cosine|euclidean)$"),
    min_seasons: int = Query(DEFAULT_MIN_SEASONS, ge=1, le=30),
):
    """Find players whose age->metric trajectory is most similar to the target."""
    try:
        if algorithm not in ALGORITHMS:
            raise ValueError(f"algorithm must be one of {ALGORITHMS}")
        result = career_service.get_similar_evolution(
            player_id=player_id, metric=metric, top_k=top_k,
            min_games=min_games, same_position=same_position,
            algorithm=algorithm, min_seasons=min_seasons,
        )
        return {
            "code": 0,
            "data": SimilarResponse(**result).model_dump(),
            "message": "ok",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"similar-evolution failed: {exc}")
