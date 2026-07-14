"""NBACore v8 — /video-library router (pure orchestration, Layer 3).

Mirrors the existing /clutch-replay and /tactics routers: it validates the
request, delegates to :class:`VideoLibraryService`, and returns a
``{code, data, message}`` envelope. Contains NO SQL, NO pandas, NO computation
(v8 §2 Layer 3 mandate) — all aggregation lives in the video_library_engine.

The local media streaming endpoint (GET /video-library/media/{id}) does only
path validation + FileResponse — no SQL, no computation.

Envelope codes (architecture §8.5):
    0      success
    40001  invalid game / season / gameid mismatch
    40002  no video source registered for the game
    40003  bulk import partial rejection
    40004  local media path traversal / file not found
    50000  aggregation / mapping error
    50100  AI analysis not enabled (P2)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from backend.services.video_library_engine import schemas
from backend.services.video_library_engine.service import VideoLibraryService

logger = logging.getLogger("nbacore.api.video_library")

router = APIRouter(prefix="/video-library", tags=["video-library"])

_svc = VideoLibraryService()

# Whitelisted root directory for local video files (path traversal defense).
# Configurable via env var; defaults to a 'videos' subdirectory under the
# project base. The media endpoint resolves local_path against this root and
# rejects any path that escapes it.
_VIDEO_ROOT = os.environ.get(
    "VIDEO_LIBRARY_ROOT",
    str(Path(__file__).resolve().parents[3] / "videos"),
)


@router.get("/games")
def get_games(
    season: str | None = None,
    team: str | None = None,
    date: str | None = None,
):
    """List games with has_video badges (dim_games LEFT JOIN game_videos)."""
    try:
        req = schemas.VideoLibraryListRequest(season=season, team=team, date=date)
        result = _svc.list_games(req)
        return {"code": 0, "data": result.model_dump(), "message": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"code": 50000, "data": None, "message": f"video library list failed: {exc}"}


@router.get("/play/{gameid}")
def get_playback(gameid: str, season: str = "2025", perspective: str = "viewer"):
    """Build the full playback payload: video ref + frames + timeline + clutch."""
    try:
        result = _svc.get_playback(gameid, season, perspective)
        return {"code": 0, "data": result.model_dump(), "message": "ok"}
    except schemas.VideoLibraryError as exc:
        return {"code": exc.code, "data": None, "message": exc.message}
    except Exception as exc:  # noqa: BLE001
        return {"code": 50000, "data": None, "message": f"playback failed: {exc}"}


@router.post("/source")
def post_source(req: schemas.UpsertVideoSourceRequest):
    """Add or replace a video source for one game (UPSERT, dedicated write pool)."""
    try:
        result = _svc.upsert_video_source(req)
        return {"code": 0, "data": result.model_dump(), "message": "ok"}
    except schemas.VideoLibraryError as exc:
        return {"code": exc.code, "data": None, "message": exc.message}
    except Exception as exc:  # noqa: BLE001
        return {"code": 50000, "data": None, "message": f"upsert failed: {exc}"}


@router.delete("/source/{gameid}")
def delete_source(gameid: str, season: str = "2025"):
    """Remove the video source for one game."""
    try:
        deleted = _svc.delete_video_source(gameid, season)
        return {"code": 0, "data": {"deleted": deleted}, "message": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"code": 50000, "data": None, "message": f"removal failed: {exc}"}


@router.post("/bulk")
def post_bulk(req: schemas.BulkImportRequest):
    """Batch import video sources (CSV/JSON → batch write). Invalid rows rejected."""
    try:
        result = _svc.bulk_import(req)
        code = 0 if not result.rejected else 40003
        return {"code": code, "data": result.model_dump(), "message": "ok" if code == 0 else "partial rejection"}
    except Exception as exc:  # noqa: BLE001
        return {"code": 50000, "data": None, "message": f"bulk import failed: {exc}"}


@router.get("/media/{media_id}")
def get_media(media_id: int):
    """Stream a local video file by its game_videos.id (same-origin, path-safe).

    Path traversal defense: resolves ``local_path`` against the whitelisted
    ``_VIDEO_ROOT`` directory and rejects any path that escapes it.
    """
    from backend.services.video_library_engine import db as vl_db

    try:
        src = vl_db.get_video_source_by_id(media_id)
    except Exception as exc:  # noqa: BLE001
        return {"code": 50000, "data": None, "message": f"media lookup failed: {exc}"}

    if src is None:
        return {"code": 40004, "data": None, "message": f"media id {media_id} not found"}

    local_path = src.get("local_path")
    if not local_path:
        return {"code": 40004, "data": None, "message": "no local_path for this media"}

    # Path traversal defense: resolve and verify within whitelisted root.
    root = Path(_VIDEO_ROOT).resolve()
    target = Path(local_path).resolve()

    # If the path is relative, resolve against the root.
    if not target.is_absolute():
        target = (root / local_path).resolve()

    try:
        target.relative_to(root)
    except ValueError:
        return {"code": 40004, "data": None, "message": "path traversal rejected"}

    if not target.is_file():
        return {"code": 40004, "data": None, "message": f"file not found: {target}"}

    return FileResponse(
        path=str(target),
        media_type="video/mp4",
        filename=target.name,
    )


@router.post("/ai/analyze")
def post_ai_analyze(gameid: str, season: str = "2025", provider: str = "static"):
    """P2 AI re-analysis endpoint. v1: 'static' returns placeholder; 'llm' → 50100."""
    try:
        result = _svc.analyze(gameid, season, provider)
        return {"code": 0, "data": result.model_dump(), "message": "ok"}
    except schemas.VideoLibraryError as exc:
        return {"code": exc.code, "data": None, "message": exc.message}
    except NotImplementedError as exc:
        return {"code": 50100, "data": None, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"code": 50000, "data": None, "message": f"analysis failed: {exc}"}
