"""Pytest fixtures for the clutch_engine test package.

The project-root ``tests/conftest.py`` defines ``db_available`` but pytest does
not load it for this package (it lives outside this directory's conftest
discovery chain). This local conftest mirrors that fixture so the live
integration tests under ``backend/services/clutch_engine/tests/`` can run
against a real PostgreSQL (v8 §6 forbids mocking engine core logic).

Test-only file — no production code or exported symbols are modified.
"""
from __future__ import annotations

import pytest

from backend.core.db import is_port_open, ping


@pytest.fixture(scope="session")
def db_available() -> bool:
    """True only if a live PostgreSQL is reachable."""
    return is_port_open() and ping()


def skip_without_db(db_available: bool) -> None:
    """Helper for tests that need a live DB."""
    if not db_available:
        pytest.skip("PostgreSQL not available — set DB_PORT and start service")
