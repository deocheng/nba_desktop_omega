"""Regression tests for the driver-death infinite-SKIP bug fix.

Background (the bug that was fixed)
-----------------------------------
In ``transactions_crawl/fetch.py`` and ``hof_exec/fetch.py`` the
``_fetch_online`` retry loop originally narrowed its handler to::

    except (WebDriverException, TimeoutError, OSError)

A dead / stale *shared* UC-Chrome driver raises
``urllib3.exceptions.ReadTimeoutError`` on ``driver.get()`` (its MRO is
ReadTimeoutError -> urllib3.TimeoutError -> ... -> Exception). That error is
**not** a subclass of ``WebDriverException``, Python's builtin ``TimeoutError``,
or ``OSError``, so the narrow tuple never caught it, ``reset_driver()`` was
never called, and the next iteration reused the *same* dead driver — every
attempt waited out its own transport timeout and SKIPped (live symptom: a fixed
port such as 57800 with zero progress for minutes on end).

Fix (already landed in both fetch.py files)
-------------------------------------------
The ``except`` is widened to ``except Exception``, so *any* driver-level
communication failure triggers ``reset_driver()`` and the next attempt rebuilds
the driver instead of silently SKIPping.

What these tests prove
----------------------
We inject a fake WebDriver whose **first** ``.get()`` raises
``urllib3.exceptions.ReadTimeoutError`` and whose **second** ``.get()`` returns a
healthy, non-Cloudflare page. We then assert:

  1. ``reset_driver()`` is invoked as a direct result of that exception, and
  2. the function returns a non-empty HTML (recovery, not infinite SKIP).

If the narrow ``except`` tuple is ever reintroduced, the ``ReadTimeoutError``
escapes the loop and ``reset_driver()`` is never recorded --> the tests fail,
catching the regression.

The real on-disk ``det2026_br`` cache is redirected to a temp dir so we never
clobber real captured pages (e.g. ``ATL_2026_transactions_raw.html``).
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest
import urllib3.exceptions as ue

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import transactions_crawl.fetch as tx_fetch  # noqa: E402
import hof_exec.fetch as hof_fetch  # noqa: E402


# ---------------------------------------------------------------------------
# Fake WebDriver: first .get() raises ReadTimeoutError; later .get()s succeed
# and populate a healthy, non-Cloudflare page_source.
# ---------------------------------------------------------------------------
class _DeadThenAliveDriver:
    def __init__(self) -> None:
        self.page_source = ""
        self._gets = 0

    def get(self, url: str) -> None:
        self._gets += 1
        if self._gets == 1:
            # The exact failure the fix must absorb: a dead shared driver
            # raising urllib3 ReadTimeoutError on .get().
            raise ue.ReadTimeoutError("fake-pool", url, "Read timed out.")
        # Subsequent attempt: the driver was rebuilt and is responsive again.
        self.page_source = (
            "<html><head><title>Atlanta Hawks Transactions | "
            "Basketball-Reference</title></head><body>"
            "<div id='div_transactions' class='table_wrapper'>"
            "Real team page content goes here."
            "</div></body></html>"
        )


@pytest.fixture
def _noop_time(monkeypatch):
    """Neutralise the real network sleeps so the test runs instantly."""
    monkeypatch.setattr(tx_fetch.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(hof_fetch.time, "sleep", lambda *a, **k: None)


@pytest.fixture
def _temp_cache(monkeypatch):
    """Redirect the on-disk raw cache to a temp dir so we never clobber the
    real det2026_br cache (e.g. ATL_2026_transactions_raw.html / ATL_hof.html)."""
    tmp = tempfile.mkdtemp(prefix="qa_fetch_recover_")
    monkeypatch.setattr(tx_fetch, "_RAW_CACHE", tmp)
    monkeypatch.setattr(hof_fetch, "_RAW_CACHE", tmp)
    return tmp


def _inject_fake_driver(monkeypatch, module, fake_driver):
    """Inject a fake WebDriver + reset_driver recorder into ``module``'s
    ``_fetch_online`` path. ``warmup_once`` is made a no-op so the first
    ``.get()`` exception surfaces *inside* the retry-loop try block (where the
    ``except Exception`` must catch it)."""
    monkeypatch.setattr(module, "get_driver", lambda: fake_driver)
    monkeypatch.setattr(module, "warmup_once", lambda base: None)
    reset_calls = []
    monkeypatch.setattr(module, "reset_driver", lambda: reset_calls.append(1))
    return reset_calls


def _assert_recovery(html, reset_calls, fake_driver, label):
    # 1) The ReadTimeoutError on the first .get() must have triggered a rebuild.
    assert len(reset_calls) >= 1, (
        f"[{label}] reset_driver() was NOT called after driver.get() raised "
        f"urllib3.exceptions.ReadTimeoutError — the narrow except tuple "
        f"(WebDriverException, TimeoutError, OSError) is back, so a dead driver "
        f"would never be rebuilt (infinite-SKIP regression)."
    )
    # 2) Recovery succeeded: a real, non-empty page is returned (no silent SKIP).
    assert html, f"[{label}] fetch returned empty HTML — the page was silently SKIPped"
    assert len(html) > 0, f"[{label}] fetch returned a zero-length payload"
    # 3) The rebuilt driver's .get() was actually exercised on recovery.
    assert fake_driver._gets >= 2, (
        f"[{label}] expected the rebuilt driver's .get() to be called on recovery"
    )


def test_transactions_fetch_recovers_from_readtimeout(
    monkeypatch, _noop_time, _temp_cache
):
    """transactions_crawl/fetch.py: ReadTimeoutError -> reset_driver -> non-empty HTML."""
    fake = _DeadThenAliveDriver()
    reset_calls = _inject_fake_driver(monkeypatch, tx_fetch, fake)

    try:
        # offline_dir=None -> online path -> _fetch_online
        html = tx_fetch.fetch_transactions_page("ATL", 2026)
    except ue.ReadTimeoutError:
        pytest.fail(
            "[transactions] ReadTimeoutError escaped _fetch_online's except — the "
            "narrow (WebDriverException, TimeoutError, OSError) tuple is back; a "
            "dead driver would never be rebuilt (infinite-SKIP regression)."
        )

    _assert_recovery(html, reset_calls, fake, "transactions")


def test_hof_fetch_recovers_from_readtimeout(monkeypatch, _noop_time, _temp_cache):
    """hof_exec/fetch.py: ReadTimeoutError -> reset_driver -> non-empty HTML."""
    fake = _DeadThenAliveDriver()
    reset_calls = _inject_fake_driver(monkeypatch, hof_fetch, fake)

    try:
        # offline_dir=None -> online path -> _fetch_online
        html = hof_fetch.fetch_team_page("ATL", "hof")
    except ue.ReadTimeoutError:
        pytest.fail(
            "[hof] ReadTimeoutError escaped _fetch_online's except — the narrow "
            "(WebDriverException, TimeoutError, OSError) tuple is back; a dead "
            "driver would never be rebuilt (infinite-SKIP regression)."
        )

    _assert_recovery(html, reset_calls, fake, "hof")
