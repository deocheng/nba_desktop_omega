"""Unit tests for common/browser.py — the shared Playwright driver manager.

All browser construction is mocked (no real browser, no network). The real
``_build_driver`` is replaced with a fake factory via
``monkeypatch.setattr(browser, "_build_driver", factory)`` so the wrapper's
``.get`` / ``.page_source`` operate on a ``MagicMock`` instead of a live
Playwright page. Proves:

  * ``get_driver()`` is a process-wide singleton (builds the driver once),
  * ``reset_driver()`` forces a rebuild on the next ``get_driver()``,
  * each rebuild yields a distinct driver object (no stale reuse),
  * ``warmup_once()`` hits the base URL only once per driver,
  * a raising ``_build_driver`` propagates its original exception.

(The old UC-Chrome hang→TimeoutError watchdog test and the ``uc_br_``
user-data-dir test were removed: Playwright manages its own throwaway profile
and has no silent-hang construction path, so those failure modes no longer
apply.)

Run from the repo root:
    python -m pytest tests/test_browser_driver.py -v
"""

from __future__ import annotations

import sys
import os

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


def _patch_build(monkeypatch, factory):
    """Replace ``common.browser._build_driver`` with a counting/simulating factory."""
    monkeypatch.setattr(browser, "_build_driver", factory)


def test_get_driver_singleton_builds_once(monkeypatch):
    calls = {"n": 0}

    def fake_build():
        calls["n"] += 1
        return MagicMock()

    _patch_build(monkeypatch, fake_build)
    monkeypatch.setattr(browser.time, "sleep", lambda *a, **k: None)

    d1 = browser.get_driver()
    d2 = browser.get_driver()
    d3 = browser.get_driver()
    assert d1 is d2 is d3
    assert calls["n"] == 1, "_build_driver must run exactly once per process"


def test_reset_driver_forces_rebuild(monkeypatch):
    calls = {"n": 0}

    def fake_build():
        calls["n"] += 1
        return MagicMock()

    _patch_build(monkeypatch, fake_build)

    d1 = browser.get_driver()
    assert calls["n"] == 1
    browser.reset_driver()
    d2 = browser.get_driver()
    assert calls["n"] == 2, "reset_driver must force a fresh build"
    # subsequent calls reuse the rebuilt driver, not a third one
    browser.get_driver()
    assert calls["n"] == 2
    # and the rebuilt driver is a distinct object, not the stale one
    assert d2 is not d1, "reset must yield a distinct driver instance"


def test_two_builds_return_distinct_drivers(monkeypatch):
    """Each rebuild produces a brand-new driver object (no stale reuse)."""
    built = []

    def fake_build():
        drv = MagicMock()
        built.append(drv)
        return drv

    _patch_build(monkeypatch, fake_build)

    first = browser.get_driver()
    browser.reset_driver()
    second = browser.get_driver()

    assert first is not second, "two builds must return different driver objects"
    assert len(built) == 2, "exactly two driver builds should have happened"


def test_warmup_once_calls_get_only_once(monkeypatch):
    def fake_build():
        return MagicMock()

    _patch_build(monkeypatch, fake_build)
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


def test_construction_exception_propagates(monkeypatch):
    def fake_build():
        raise RuntimeError("patched boom")

    _patch_build(monkeypatch, fake_build)

    with pytest.raises(RuntimeError):
        browser.get_driver()
