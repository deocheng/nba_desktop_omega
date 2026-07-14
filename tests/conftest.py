"""Pytest fixtures for NBACore v8 — Phase 0.

v8 §6 forbids mocking Metric Engine core logic. DB-dependent tests use a
live connection (skipped if PostgreSQL unavailable) rather than mocking.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.core.db import is_port_open, ping


@pytest.fixture(scope="session")
def app_client():
    """FastAPI TestClient with lifespan triggered (pool init attempted)."""
    from backend.app import create_app
    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def db_available() -> bool:
    """True only if a live PostgreSQL is reachable."""
    return is_port_open() and ping()


def skip_without_db(db_available: bool):
    """Helper for tests that need a live DB."""
    if not db_available:
        pytest.skip("PostgreSQL not available — set DB_PORT and start service")
