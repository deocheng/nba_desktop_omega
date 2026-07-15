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

# Kept identical to the legacy per-page user-agent so cached pages are stable.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)


def _user_data_dir() -> str:
    """Return this process's unique Chrome ``--user-data-dir`` (created once).

    Cached at module level so every ``uc.Chrome()`` in the same process reuses
    the exact same profile — guaranteeing two *concurrent* crawl processes
    never collide on the patched global driver binary.
    """
    global _USER_DATA_DIR
    if _USER_DATA_DIR is None:
        _USER_DATA_DIR = tempfile.mkdtemp(prefix="uc_br_")
        logger.debug("allocated unique user-data-dir: %s", _USER_DATA_DIR)
    return _USER_DATA_DIR


def _build_opts():
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
    opts.add_argument(f"--user-agent={_USER_AGENT}")
    return opts


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
            result["driver"] = uc.Chrome(options=_build_opts())
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
