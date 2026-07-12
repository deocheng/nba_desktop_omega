"""Re-export the v8.2-C Career feature tests.

Mirrors tests/test_clutch.py: the canonical test bodies live under
``backend/services/career_engine/tests/``; this shim collects them via the
standard ``pytest tests/ -k career`` command so the whole suite stays in one
place. Single source of truth = the engine-side modules.
"""
from backend.services.career_engine.tests.test_utils import *  # noqa: F401,F403
from backend.services.career_engine.tests.test_queries import *  # noqa: F401,F403
from backend.services.career_engine.tests.test_service import *  # noqa: F401,F403
