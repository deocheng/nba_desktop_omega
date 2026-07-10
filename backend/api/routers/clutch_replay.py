"""NBACore v8 — /clutch-replay router (pure orchestration, Layer 3).

Mirrors the existing /clutch and /tactics routers: it validates the request,
delegates to :class:`ClutchReplayService`, and returns a
``{code, data, message}`` envelope. Contains NO SQL, NO pandas, NO computation
(v8 §2 Layer 3 mandate) — all aggregation lives in the clutch_replay_engine.

Envelope codes (architecture §8.5):
    0      success
    40001  invalid game / season
    40002  no br_crawler xy replay data for the game+season
    50000  aggregation / mapping error
"""
from __future__ import annotations

from fastapi import APIRouter

from backend.services.clutch_replay_engine import schemas
from backend.services.clutch_replay_engine.service import ClutchReplayService
from backend.services.tactics_engine import service as tactics_service

router = APIRouter(prefix="/clutch-replay", tags=["clutch-replay"])

_svc = ClutchReplayService()


@router.post("/replay")
def post_replay(req: schemas.ClutchReplayRequest):
    """Fuse clutch stats with a tactics replay timeline for one game."""
    try:
        result = _svc.clutch_replay(req)
        return {"code": 0, "data": result.model_dump(), "message": "ok"}
    except schemas.ClutchReplayError as exc:
        return {"code": exc.code, "data": None, "message": exc.message}
    except ValueError as exc:
        return {"code": 40001, "data": None, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 — surface aggregation errors cleanly
        return {"code": 50000, "data": None, "message": f"clutch replay failed: {exc}"}


@router.get("/games")
def get_games(season: str = "2025"):
    """List replayable games for a season (reuses the tactics engine)."""
    try:
        games = tactics_service.TacticsService().list_games(season)
        return {"code": 0, "data": games, "message": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"code": 50000, "data": None, "message": f"clutch replay games failed: {exc}"}
