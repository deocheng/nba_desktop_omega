"""Re-export the Fusion Clutch Replay feature tests.

This lets the team's standard command ``pytest tests/ -k clutch_replay`` collect
and run every feature test (mapper units, service units, and the router
integration test) even though the canonical test modules live under
``backend/services/...`` per the architecture spec. Single source of truth — the
real test bodies are defined in those modules.
"""
from backend.services.clutch_replay_engine.tests.test_mapper import *  # noqa: F401,F403
from backend.services.clutch_replay_engine.tests.test_service import *  # noqa: F401,F403
from backend.services.tactics_engine.tests.test_clutch_replay_integration import *  # noqa: F401,F403
