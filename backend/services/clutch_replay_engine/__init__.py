"""NBACore v8 — Fusion Clutch Replay aggregation layer (Layer 2 facade).

Thin orchestration layer that fuses the existing ``clutch_engine`` (clutch-time
player stats + event-level clutch rows) with the ``tactics_engine`` (PBP replay
frame sequence) into a single replay timeline.

Strict four-layer isolation (v8 §6):
    Frontend  → API (orchestration only) → this aggregation layer
              → reuses clutch_engine / tactics_engine → Data (read-only batch_query)

This package does NOT compute coordinates, interpolate frames, or evaluate the
clutch window. It maps ``eventnum → event_index → frame_index`` (pure Python),
reuses engine outputs, and shapes the ``ClutchReplayResult`` contract.
"""
from __future__ import annotations

from backend.services.clutch_replay_engine import mapper, schemas, service

__all__ = ["mapper", "schemas", "service", "ClutchReplayService"]


def ClutchReplayService() -> "service.ClutchReplayService":  # pragma: no cover - convenience
    """Factory returning a configured :class:`ClutchReplayService`."""
    return service.ClutchReplayService()
