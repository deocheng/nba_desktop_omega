"""common/browser.py — process-level shared undetected-chromedriver manager.

This is the single source for the BR team-page crawlers' UC-Chrome instance.

Why a shared driver?
--------------------
The previous implementation rebuilt ``uc.Chrome()`` *inside the per-page retry
loop*. A cold ``uc.Chrome()`` construction is stable at ~50s (measured: 56s on
the first call, 48s on the second). With 30 teams x 27 years x 3 page types x
up to 4 retries, that is millions of seconds — effectively days — to crawl
everything. The fix: build the driver **once per process** and reuse it for
every page.

What else this module fixes (root causes verified by the lead):
  * **Silent construction hang** — ``uc.Chrome()`` can hang *without raising*,
    so the old ``try/except`` around ``driver.get`` could not catch it and the
    whole crawl froze with zero logs. Construction now runs in a daemon thread
    with a hard ``join(timeout=120)`` watchdog; a hang becomes a catchable
    ``TimeoutError`` that the caller's retry loop absorbs.
  * **Concurrent profile clash** — two crawl processes share the same patched
    global Chrome binary; without a per-process ``--user-data-dir`` the second
    ``uc.Chrome()`` crashed immediately (``no such window: target window
    already closed``). Each process now gets a unique temp ``--user-data-dir``.

Public API:
  * ``get_driver()``      — return the process-wide driver (builds on first call)
  * ``reset_driver()``    — invalidate the current driver; next ``get_driver()``
                            rebuilds it (old one quit, errors ignored)
  * ``warmup_once(base)`` — hit ``base`` exactly once on the live driver
  * ``quit_driver()``     — quit the driver (registered with ``atexit``)

Import safety:
  ``undetected_chromedriver`` is imported at module load (it does NOT launch a
  browser), so importing this module is harmless offline. The browser is only
  ever constructed inside ``_build_driver`` (i.e. when ``get_driver`` is first
  called). ``uc`` is kept as a module attribute so tests can monkeypatch
  ``common.browser.uc.Chrome``.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import subprocess
import tempfile
import threading
import time

import undetected_chromedriver as uc  # safe to import: no browser launched here

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state. All mutations are guarded by _LOCK for thread safety.
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_DRIVER: object | None = None          # the live WebDriver, or None
_INVALID: bool = False                 # True => must rebuild before next use
_WARMED: bool = False                  # True => warm-up already done this driver
_USER_DATA_DIR: str | None = None      # unique per-process Chrome profile dir

# Generous vs. the ~50s measured cold-start; lets a slow-but-healthy build
# finish while still converting a true hang into a catchable TimeoutError.
_BUILD_TIMEOUT_SECONDS = 120

# BR homepage, used by the CF handshake / self-healing navigation.
# Defined locally (not imported from common.browser) to avoid a circular
# import: common/browser.py imports this module at load time when
# BROWSER_BACKEND=uc.
_BR_HOMEPAGE = "https://www.basketball-reference.com/"

# Kept identical to the legacy per-page user-agent so cached pages are stable.
# NOTE: the Chrome major version must match the *installed* browser — a UA
# claiming a different major than the binary is a classic automation
# fingerprint and makes Cloudflare far more likely to challenge the session.
# (It used to be hard-coded to 150 while the installed Chrome moved to 155;
# the effective UA is now derived from ``_chrome_major_version()``.)
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)


def _user_agent(major: int) -> str:
    """Return a UA string whose Chrome major matches the installed browser."""
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.0.0 Safari/537.36"
    )


class _UCDriver:
    """Adapter: raw Selenium WebDriver → the shared crawler driver contract.

    The shared crawl layer (``common.browser.ensure_cf_cleared`` and
    ``common.br_team_page``) requires **every** driver to expose two extra
    members beyond ``get``/``page_source``:

      * ``_navigate(url)``     — fire-and-forget navigation used by the CF handshake
      * ``_is_challenged()``   — live Cloudflare challenge detection

    ``_PWDriver`` and ``_RawCDPDriver`` both implement them; the raw
    ``undetected_chromedriver`` WebDriver did **not**.  The consequence was a
    silent deadlock: the handshake's ``driver._navigate(...)`` raised
    ``AttributeError`` (logged as a warning), and the following
    ``driver._is_challenged()`` raised the *same* AttributeError inside the
    poll loop where it is swallowed — so the loop concluded "challenged" on
    every iteration and waited forever for a human to click "Verify you are
    human" in a visible Chrome window.  The UC browser is **headless**, so no
    such window exists and the crawl could never proceed.

    This adapter supplies the missing half and delegates everything else to
    the wrapped WebDriver, so the UC backend becomes a first-class citizen of
    the shared crawl layer.
    """

    #: Cloudflare interstitial markers (mirrors ``_RawCDPDriver._is_challenged``).
    _CF_TEXT_MARKERS = (
        "Checking your browser",
        "Just a moment",
        "Verify you are human",
        "请稍候",
        "正在进行安全验证",
        "安全验证",
        "安全服务防护",
    )

    def __init__(self, driver) -> None:
        self._d = driver
        #: The UC browser runs headless → no human can interact with a window.
        self.headless = True

    # ── shared contract ──────────────────────────────────────────────
    def get(self, url: str) -> None:
        self._d.get(url)

    @property
    def page_source(self) -> str:
        return self._d.page_source

    @property
    def title(self) -> str:
        try:
            return self._d.title
        except Exception:  # noqa: BLE001 - page mid-navigation
            return ""

    @property
    def current_url(self) -> str:
        try:
            return self._d.current_url
        except Exception:  # noqa: BLE001 - page mid-navigation
            return ""

    def _navigate(self, url: str, timeout: int = 60) -> None:
        """Fire-and-forget navigation (no CF poll); the caller owns the poll.

        Used by ``ensure_cf_cleared`` so the handshake controls the polling
        interval exactly instead of relying on ``get``'s internal retry loop.
        """
        try:
            self._d.set_page_load_timeout(timeout)
        except Exception:  # noqa: BLE001 - best-effort
            pass
        self._d.get(url)

    def _is_challenged(self) -> bool:
        """Detect a live Cloudflare challenge on the current page."""
        try:
            u = self.current_url or ""
            if "__cf_chl_rt_tk" in u or "cf_chl" in u:
                return True
        except Exception:  # noqa: BLE001
            pass
        txt = ""
        try:
            txt = self._d.execute_script(
                "return (document.body && document.body.innerText) "
                "? document.body.innerText.slice(0, 500) : '';"
            ) or ""
        except Exception:  # noqa: BLE001 - page mid-navigation: fall back to HTML
            try:
                html = self._d.page_source or ""
            except Exception:  # noqa: BLE001
                return False
            return any(k in html for k in self._CF_TEXT_MARKERS)
        return any(k in txt for k in self._CF_TEXT_MARKERS)

    def auto_pass_cf(self, attempts: int = 1, wait: float = 4.0,
                     url: str | None = None) -> bool:
        """Headless self-healing: re-navigate and let the JS challenge clear.

        A headless browser can never receive a human click, so the shared
        handshake's "please click Verify you are human" prompt would block
        forever.  ``undetected_chromedriver`` exists precisely to clear
        Cloudflare's JS challenge unattended — re-navigating grants it a fresh
        attempt.  ``url`` is the original target to re-fetch (the interstitial
        may have replaced ``current_url`` with a challenge token URL).
        Returns True as soon as the page is no longer challenged.
        """
        target = url or self.current_url or _BR_HOMEPAGE
        for _ in range(max(1, attempts)):
            try:
                self._navigate(target)
            except Exception:  # noqa: BLE001 - navigation may fail; retry below
                pass
            time.sleep(wait)
            try:
                if not self._is_challenged():
                    return True
            except Exception:  # noqa: BLE001
                return True
        return False

    def quit(self) -> None:
        try:
            self._d.quit()
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass

    # ── delegate the rest of the WebDriver surface ───────────────────
    def __getattr__(self, name: str):
        try:
            wrapped = self.__dict__["_d"]
        except KeyError:
            raise AttributeError(name) from None
        return getattr(wrapped, name)


def _user_data_dir() -> str:
    """Return this process's unique Chrome ``--user-data-dir`` (created once).

    Cached at module level so every ``uc.Chrome()`` in the same process reuses
    the exact same profile — guaranteeing two *concurrent* crawl processes
    never collide on the patched global driver binary.

    By default a fresh temp dir is used (per-process isolation).  Set
    ``UC_USER_DATA_DIR`` to a fixed path to opt into a **persistent** profile:
    Cloudflare's ``cf_clearance`` cookie then survives across processes, so
    the browser stops presenting as a brand-new client on every run and BR
    challenges it far less often.  (Persistent profiles must not be shared by
    concurrent crawl processes — that is what the temp dir is for.)
    """
    global _USER_DATA_DIR
    if _USER_DATA_DIR is None:
        persistent = (os.environ.get("UC_USER_DATA_DIR") or "").strip()
        if persistent:
            if not os.path.isdir(persistent):
                os.makedirs(persistent, exist_ok=True)
            _USER_DATA_DIR = persistent
            logger.info("使用持久化 UC profile: %s", persistent)
        else:
            _USER_DATA_DIR = tempfile.mkdtemp(prefix="uc_br_")
            logger.debug("allocated unique user-data-dir: %s", _USER_DATA_DIR)
    return _USER_DATA_DIR


def _build_opts(major: int | None = None):
    """Assemble the ChromeOptions shared by every driver build in this process."""
    opts = uc.ChromeOptions()
    opts.headless = True  # unchanged from legacy behaviour
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    # new: avoid GPU / software raster paths that can wedge headless Chrome
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-software-rasterizer")
    # new + critical: unique per-process profile dir (prevents concurrent clash)
    opts.add_argument(f"--user-data-dir={_user_data_dir()}")
    # UA major version must match the installed Chrome (see _user_agent).
    if major is None:
        major = _chrome_major_version() or 155
    opts.add_argument(f"--user-agent={_user_agent(major)}")
    return opts


def _chrome_major_version() -> int:
    """Detect the installed Chrome/Chromium *major* version at runtime.

    ``undetected_chromedriver`` grabs the *latest* driver when ``version_main``
    is not pinned, which mismatches an older (or newer) installed Chrome and
    crashes at launch with ``SessionNotCreatedException``. Pinning a hard-coded
    version broke every time Chrome auto-updated, so we detect the real version
    instead and pin to that.

    Returns the major version as int, or 0 if detection fails (the caller
    falls back to a sane default).
    """
    exe = None
    try:
        exe = uc.find_chrome_executable()
    except Exception:  # noqa: BLE001 - detection is best-effort
        exe = None
    if not exe:
        # Fallback candidates (macOS / Linux / Windows-in-PATH).
        for cand in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "google-chrome", "chromium", "chromium-browser",
        ):
            if shutil.which(cand) or os.path.exists(cand):
                exe = cand
                break
    if not exe:
        return 0
    try:
        out = subprocess.run(
            [exe, "--version"],
            capture_output=True, text=True, timeout=20,
        ).stdout
        m = re.search(r"(\d+)\.\d+\.\d+", out)
        if m:
            return int(m.group(1))
    except Exception:  # noqa: BLE001 - detection is best-effort
        return 0
    return 0


def _build_driver():
    """Build and return a fresh UC-Chrome driver behind a hard-timeout watchdog.

    Returns the driver on success. Raises ``TimeoutError`` if construction does
    not finish within ``_BUILD_TIMEOUT_SECONDS`` (the daemon worker is left to
    exit with the interpreter), or re-raises whatever ``uc.Chrome()`` raised.

    Because ``uc.Chrome()`` can hang *without raising*, we run it in a daemon
    thread and ``join`` with a timeout — converting a silent hang into a
    catchable ``TimeoutError`` that the caller's retry loop can absorb.
    """
    result: dict = {"driver": None, "error": None}

    def _spawn() -> None:
        try:
            # Pin the driver to the *installed* Chrome major version so UC does
            # not grab the latest driver and mismatch the browser. Detected at
            # runtime (see _chrome_major_version) so Chrome auto-updates no
            # longer silently break the crawler with SessionNotCreatedException.
            major = _chrome_major_version() or 155
            # On Apple Silicon, undetected_chromedriver downloads an x86_64
            # driver that cannot run without Rosetta 2. Allow an explicit arm64
            # driver via UC_CHROMEDRIVER_PATH (set by the run env) so the UC
            # backend launches natively. If unset/missing, fall back to UC's
            # default auto-downloaded driver.
            kwargs = {"options": _build_opts(major), "version_main": major}
            driver_path = os.environ.get("UC_CHROMEDRIVER_PATH")
            if driver_path and os.path.exists(driver_path):
                kwargs["driver_executable_path"] = driver_path
            # Wrap in the shared-contract adapter: the crawl layer calls
            # _navigate / _is_challenged, which the raw WebDriver lacks.
            result["driver"] = _UCDriver(uc.Chrome(**kwargs))
        except Exception as exc:  # noqa: BLE001 - propagate to the caller
            result["error"] = exc

    worker = threading.Thread(target=_spawn, name="uc-chrome-build", daemon=True)
    worker.start()
    worker.join(timeout=_BUILD_TIMEOUT_SECONDS)

    if worker.is_alive():
        # The build thread is still running => silent hang. It is a daemon, so
        # it will be reaped on interpreter exit; raise so the caller retries.
        logger.error(
            "uc.Chrome() construction timed out after %ds (silent hang); "
            "forcing rebuild",
            _BUILD_TIMEOUT_SECONDS,
        )
        raise TimeoutError(
            f"uc.Chrome() did not finish within {_BUILD_TIMEOUT_SECONDS}s"
        )

    if result["error"] is not None:
        raise result["error"]

    driver = result["driver"]
    if driver is None:
        # Defensive: a finished thread that set neither field.
        raise RuntimeError("uc.Chrome() returned no driver and no error")
    return driver


def get_driver():
    """Return the process-wide UC-Chrome driver, building it on first use.

    Thread-safe. If ``reset_driver()`` was called (or the driver died), a new
    instance is built and returned. Concurrent callers share a single instance.
    """
    global _DRIVER, _INVALID
    with _LOCK:
        if _DRIVER is not None and not _INVALID:
            return _DRIVER
        # (Re)build under the lock so concurrent callers share one instance
        # instead of each spawning their own Chrome.
        if _DRIVER is not None:
            try:
                _DRIVER.quit()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
        logger.info("building shared UC-Chrome driver (process-wide singleton)")
        _DRIVER = _build_driver()
        _INVALID = False
    return _DRIVER


def reset_driver() -> None:
    """Mark the current driver invalid so the next ``get_driver()`` rebuilds it.

    The old driver is quit best-effort (exceptions ignored). Safe to call when
    no driver exists yet. Clears the warm-up flag so a rebuilt driver is warmed
    again.
    """
    global _DRIVER, _INVALID, _WARMED
    with _LOCK:
        if _DRIVER is not None:
            try:
                _DRIVER.quit()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
        _DRIVER = None
        _INVALID = True
        _WARMED = False


def warmup_once(base_url: str) -> None:
    """Hit ``base_url`` exactly once on the live driver.

    Idempotent across the process (and re-armed by ``reset_driver``). Errors are
    swallowed so a flaky warm-up never aborts a crawl. Not locked: the crawl
    loop is single-threaded and ``get_driver`` is itself thread-safe.
    """
    global _WARMED
    if _WARMED:
        return
    driver = get_driver()
    try:
        driver.get(base_url)
        time.sleep(3)
        _WARMED = True
        logger.debug("driver warm-up done for %s", base_url)
    except Exception:  # noqa: BLE001 - best-effort warm-up
        _WARMED = False


def quit_driver() -> None:
    """Quit the shared driver, if any. Registered with ``atexit``.

    Safe to call multiple times; exceptions are ignored so interpreter exit is
    never blocked by a wedged browser.
    """
    global _DRIVER, _INVALID, _WARMED
    with _LOCK:
        if _DRIVER is not None:
            try:
                _DRIVER.quit()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
        _DRIVER = None
        _INVALID = True
        _WARMED = False


# Tear down the shared driver on normal interpreter exit.
atexit.register(quit_driver)
