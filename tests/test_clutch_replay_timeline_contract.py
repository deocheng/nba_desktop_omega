"""Contract regression test for the locked shared frontend contract.

``window.ClutchReplay.Timeline.mount(...)`` is the single source of truth for the
highlight timeline (architecture §3.2 / §8.6) and is consumed directly by the
Video Library (P2) via its SyncController. A broken or missing export would
silently block that feature, which is exactly how the original defect slipped
through (zero frontend coverage).

This test drives the node mock-DOM harness ``tests/frontend/test_timeline_contract.js``
which asserts the contract verbatim (handle shape, 0–1000 normalized space,
append-semantics ``onSeek``, ``setProgress`` no loop-back, defensive no-op handles).

It is **skipped automatically** when ``node`` is unavailable in the environment
so it never turns the suite red for environment reasons — but when node is
present (dev CI), it guards the contract under ``pytest -k clutch_replay``.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

_JS_HARNESS = os.path.join(
    os.path.dirname(__file__), "frontend", "test_timeline_contract.js"
)
# node resolves the relative require('./frontend/js/components/...') from cwd
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_JS_HARNESS))


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node not installed; skipping JS Timeline.mount contract harness",
)
def test_timeline_mount_contract():
    """Run the node harness; fail only on a real contract violation."""
    assert os.path.exists(_JS_HARNESS), f"missing harness file: {_JS_HARNESS}"
    proc = subprocess.run(
        ["node", _JS_HARNESS],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"Timeline.mount contract harness failed (rc={proc.returncode}):\n"
        f"--- STDOUT ---\n{proc.stdout}\n--- STDERR ---\n{proc.stderr}"
    )
