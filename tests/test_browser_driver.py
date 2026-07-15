"""Unit tests for common/browser.py — the shared UC-Chrome driver manager.

All browser construction is mocked (no real Chrome, no network). Proves:

  * ``get_driver()`` is a process-wide singleton (builds ``uc.Chrome`` once),
  * ``reset_driver()`` forces a rebuild on the next ``get_driver()``,
  * ``warmup_once()`` hits the base URL only once per driver,
  * a hanging ``uc.Chrome()`` construction raises ``TimeoutError`` (hard
    watchdog),
  * a raising ``uc.Chrome()`` propagates its original exception,
  * each process gets a unique ``--user-data-dir``.

Run from the repo root:
    python -m pytest tests/test_browser_driver.py -v
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from unittest.mock import MagicMock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common import browser  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_state():
    """Ensure each test starts and ends with a torn-down driver."""
    browser.reset_driver()
    yield
    browser.reset_driver()


def _patch_chrome(monkeypatch, factory):
    """Replace ``common.browser.uc.Chrome`` with a counting/simulating factory."""
    monkeypatch.setattr(browser.uc, "Chrome", factory)


def test_get_driver_singleton_builds_once(monkeypatch):
    calls = {"n": 0}

    def fake_chrome(options=None):
        calls["n"] += 1
        return MagicMock()

    _patch_chrome(monkeypatch, fake_chrome)
    monkeypatch.setattr(browser.time, "sleep", lambda *a, **k: None)

    d1 = browser.get_driver()
    d2 = browser.get_driver()
    d3 = browser.get_driver()
    assert d1 is d2 is d3
    assert calls["n"] == 1, "uc.Chrome must be built exactly once for the process"


def test_reset_driver_forces_rebuild(monkeypatch):
    calls = {"n": 0}

    def fake_chrome(options=None):
        calls["n"] += 1
        return MagicMock()

    _patch_chrome(monkeypatch, fake_chrome)

    browser.get_driver()
    assert calls["n"] == 1
    browser.reset_driver()
    browser.get_driver()
    assert calls["n"] == 2, "reset_driver must force a fresh build"
    # subsequent calls reuse the rebuilt driver, not a third one
    browser.get_driver()
    assert calls["n"] == 2


def test_warmup_once_calls_get_only_once(monkeypatch):
    def fake_chrome(options=None):
        return MagicMock()

    _patch_chrome(monkeypatch, fake_chrome)
    monkeypatch.setattr(browser.time, "sleep", lambda *a, **k: None)

    drv = browser.get_driver()
    browser.warmup_once("https://example.com")
    browser.warmup_once("https://example.com")
    browser.warmup_once("https://example.com")
    assert drv.get.call_count == 1, "warm-up must hit the base URL only once"

    # after a reset a fresh driver is warmed again (exactly once)
    browser.reset_driver()
    drv2 = browser.get_driver()
    browser.warmup_once("https://example.com")
    assert drv2.get.call_count == 1


def test_hanging_construction_raises_timeout(monkeypatch):
    def fake_chrome(options=None):
        # simulate the silent uc.Chrome() hang (no exception raised)
        time.sleep(1.0)
        return MagicMock()

    _patch_chrome(monkeypatch, fake_chrome)
    # shrink the watchdog so the test is fast while still exercising the path
    monkeypatch.setattr(browser, "_BUILD_TIMEOUT_SECONDS", 0.2)

    with pytest.raises(TimeoutError):
        browser.get_driver()


def test_construction_exception_propagates(monkeypatch):
    def fake_chrome(options=None):
        raise RuntimeError("patched boom")

    _patch_chrome(monkeypatch, fake_chrome)

    with pytest.raises(RuntimeError):
        browser.get_driver()


def test_user_data_dir_unique_per_process():
    # within one process the dir is allocated once and cached
    dir1 = browser._user_data_dir()
    dir2 = browser._user_data_dir()
    assert dir1 == dir2
    assert os.path.basename(dir1).startswith("uc_br_")

    # simulate a second process: reloading the module reallocates the dir
    importlib.reload(browser)
    dir3 = browser._user_data_dir()
    try:
        assert dir3 != dir1, "each process must get its own user-data-dir"
        assert os.path.basename(dir3).startswith("uc_br_")
    finally:
        for d in (dir1, dir3):
            if d and os.path.isdir(d):
                try:
                    os.rmdir(d)
                except OSError:
                    pass
