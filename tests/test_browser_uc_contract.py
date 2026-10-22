"""Regression tests for the UC-Chrome driver contract (common/browser_uc.py).

Bug being pinned
----------------
``common.browser.ensure_cf_cleared`` drives the Cloudflare handshake through
two driver members: ``_navigate(url)`` and ``_is_challenged()``.  Both the
Playwright (``_PWDriver``) and raw-CDP (``_RawCDPDriver``) backends implement
them — the **UC backend did not**.

Consequence (silent deadlock, no exception surfaced):
  1. ``driver._navigate(base_url)`` raised ``AttributeError`` (logged as a
     warning: "CF 握手导航 ... 失败").
  2. ``driver._is_challenged()`` raised the *same* ``AttributeError`` inside
     the poll loop, where it is swallowed by ``except Exception: pass``.
  3. The loop therefore concluded "challenged" on *every* iteration and waited
     forever for a human to click "Verify you are human" in a visible Chrome
     window — impossible for the headless UC browser.

These tests use a fake WebDriver (no browser, no network) and assert:
  * the UC driver exposes the shared contract,
  * challenge detection recognises both the URL token and the body text,
  * a headless driver recovers unattended (no human click, no hang),
  * a headless driver that cannot recover gives up instead of hanging.

Run from the repo root:
    python -m pytest tests/test_browser_uc_contract.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common import browser  # noqa: E402
from common.browser_uc import _UCDriver  # noqa: E402


class FakeSelenium:
    """Minimal stand-in for a Selenium WebDriver."""

    def __init__(self, html: str = "<html>ok</html>", title: str = "ok",
                 url: str = "https://www.basketball-reference.com/",
                 body_text: str = "") -> None:
        self._html = html
        self._title = title
        self._url = url
        self._body_text = body_text
        self.visited: list[str] = []
        self.quit_called = False

    @property
    def page_source(self) -> str:
        return self._html

    @property
    def title(self) -> str:
        return self._title

    @property
    def current_url(self) -> str:
        return self._url

    def execute_script(self, script, *args):
        return self._body_text

    def get(self, url: str) -> None:
        self.visited.append(url)
        self._url = url

    def set_page_load_timeout(self, t) -> None:
        self._timeout = t

    def quit(self) -> None:
        self.quit_called = True


def test_uc_driver_exposes_shared_contract():
    """The UC driver must expose what ensure_cf_cleared calls."""
    drv = _UCDriver(FakeSelenium())
    for member in ("get", "page_source", "title", "current_url",
                   "_navigate", "_is_challenged", "auto_pass_cf", "quit"):
        assert hasattr(drv, member), f"UC driver missing {member}"


def test_uc_driver_delegates_unknown_members():
    """Anything the contract doesn't cover is delegated to the WebDriver."""
    fake = FakeSelenium()
    drv = _UCDriver(fake)
    fake.some_new_api = lambda: "delegated"
    assert drv.some_new_api() == "delegated"


def test_is_challenged_detects_cf_url_token():
    drv = _UCDriver(FakeSelenium(
        url="https://www.basketball-reference.com/?__cf_chl_rt_tk=abc"))
    assert drv._is_challenged() is True


def test_is_challenged_detects_cf_body_text():
    drv = _UCDriver(FakeSelenium(body_text="请稍候… Just a moment..."))
    assert drv._is_challenged() is True


def test_is_challenged_false_on_clean_page():
    drv = _UCDriver(FakeSelenium(body_text="2023-24 San Antonio Spurs Roster"))
    assert drv._is_challenged() is False


def test_is_challenged_falls_back_to_html_when_script_fails():
    class NoScript(FakeSelenium):
        def execute_script(self, script, *args):
            raise RuntimeError("page mid-navigation")

    drv = _UCDriver(NoScript(html="<body>Verify you are human</body>"))
    assert drv._is_challenged() is True


def test_ensure_cf_cleared_recovers_headless_without_human():
    """A headless driver must recover unattended and return True."""
    fake = FakeSelenium(body_text="请稍候…")
    drv = _UCDriver(fake)

    calls = {"n": 0}
    real_auto = drv.auto_pass_cf

    def auto_pass_cf(*args, **kwargs):
        calls["n"] += 1
        # first attempt: challenge clears
        fake._body_text = "2023-24 San Antonio Spurs Roster"
        return real_auto(*args, **kwargs)

    drv.auto_pass_cf = auto_pass_cf
    assert browser.ensure_cf_cleared(drv) is True
    assert calls["n"] >= 1
    assert fake.visited, "handshake must actually navigate the driver"


def test_ensure_cf_cleared_gives_up_instead_of_hanging():
    """An unrecoverable headless challenge must time out, not block forever."""
    fake = FakeSelenium(body_text="请稍候…")
    drv = _UCDriver(fake)
    drv.auto_pass_cf = lambda *a, **k: False

    old = browser._CF_HEADLESS_TIMEOUT_SECONDS
    browser._CF_HEADLESS_TIMEOUT_SECONDS = 0.1
    old_poll = browser.ensure_cf_cleared.__defaults__
    try:
        assert browser.ensure_cf_cleared(drv, poll=0.05) is False
    finally:
        browser._CF_HEADLESS_TIMEOUT_SECONDS = old
        browser.ensure_cf_cleared.__defaults__ = old_poll


def test_ensure_cf_cleared_survives_missing_contract_members():
    """The original defect: a driver without _is_challenged must not hang.

    Simulates the pre-fix UC driver (no _navigate / no _is_challenged) but
    with the headless self-healing capability: the handshake must terminate
    instead of looping forever.
    """
    class LegacyDriver:
        headless = True
        page_source = "<html/>"

        def get(self, url):
            pass

        def auto_pass_cf(self, attempts=1, wait=4.0, url=None):
            return False

    old = browser._CF_HEADLESS_TIMEOUT_SECONDS
    browser._CF_HEADLESS_TIMEOUT_SECONDS = 0.1
    try:
        assert browser.ensure_cf_cleared(LegacyDriver(), poll=0.05) is False
    finally:
        browser._CF_HEADLESS_TIMEOUT_SECONDS = old


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
