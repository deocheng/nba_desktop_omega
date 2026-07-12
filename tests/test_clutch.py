"""Re-export the Clutch (v8.2-C) feature tests.

Mirrors tests/test_clutch_replay.py: the canonical test bodies live under
``backend/services/clutch_engine/tests/``; this shim collects them via the
standard ``pytest tests/ -k clutch`` command so the whole suite stays in one
place. Single source of truth = the engine-side modules.
"""
from backend.services.clutch_engine.tests.test_utils import *  # noqa: F401,F403
from backend.services.clutch_engine.tests.test_queries import *  # noqa: F401,F403
from backend.services.clutch_engine.tests.test_service import *  # noqa: F401,F403
