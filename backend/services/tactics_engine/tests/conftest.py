"""Shared fixtures for tactics_engine tests.

Ensures the project root (nba_desktop_omega) is importable so that
``import backend...`` resolves regardless of the working directory, and
provides a module-scoped real-game replay fixture (DB-backed).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[4])  # .../nba_desktop_omega
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest  # noqa: E402

REAL_GAME_ID = "22400740"
REAL_SEASON = "2025"


@pytest.fixture(scope="session")
def real_game():
    return REAL_GAME_ID, REAL_SEASON


@pytest.fixture(scope="module")
def real_frames():
    """Build the real PBP replay frames once (fps=10 keeps it light but representative).

    Coordinate mapping / interpolation is fps-independent at the endpoints, so a
    lower fps is sufficient to validate bounds and (0,0) red-line behaviour.
    """
    from backend.services.tactics_engine import service as svc_mod
    from backend.services.tactics_engine.schemas import ReplayRequest

    svc = svc_mod.TacticsService()
    result = svc.replay(
        ReplayRequest(game_id=REAL_GAME_ID, season=REAL_SEASON, frame_rate=10)
    )
    return result
