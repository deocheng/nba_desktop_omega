"""NBACore v8 — Video Library aggregation layer (Layer 2 facade).

Thin orchestration layer that fuses video source management, PBP replay frames,
clutch highlight segments, and video-time offset mapping into a single playback
contract for the frontend ``<video>`` + Tactics + Timeline sync bridge.

Strict four-layer isolation (v8 §6):
    Frontend  → API (orchestration only) → this aggregation layer
              → reuses clutch_replay_engine / tactics_engine / clutch_engine
              → Data (read-only batch_query for SELECTs;
                       dedicated write pool for game_videos DML)

This package computes the offset mapping (``video_time = offset + game_elapsed``)
in pure Python (OffsetMapper) and reuses existing engine outputs for everything
else. It does NOT compute coordinates, interpolate frames, or evaluate the
clutch window.
"""
from __future__ import annotations

from backend.services.video_library_engine import (
    analyzer,
    db,
    offset_mapper,
    schemas,
    service,
)

__all__ = [
    "analyzer",
    "db",
    "offset_mapper",
    "schemas",
    "service",
    "VideoLibraryService",
    "REGISTRY",
]


def VideoLibraryService() -> "service.VideoLibraryService":  # pragma: no cover
    """Factory returning a configured :class:`VideoLibraryService`."""
    return service.VideoLibraryService()


# Re-export the analyzer registry for convenience.
REGISTRY = analyzer.REGISTRY
