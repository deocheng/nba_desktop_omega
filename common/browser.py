"""common/browser.py — process-level shared Playwright driver manager.

This is the single source for the BR team-page crawlers' headless browser
instance. It replaces the previous ``undetected-chromedriver`` (UC-Chrome)
backend with **Playwright + playwright_stealth**, i.e. we move *back* to the
Cloudflare-bypass approach that was already validated on the Windows side
before the Mac migration temporarily switched to UC. UC kept hard-freezing at
runtime (SAFE_DELETE death spiral), so we retire it.

Why a shared driver?
--------------------
Building a headless browser is expensive. The crawlers call ``get_driver()``
for every team/year/page, so we build the browser **once per process** and
reuse the single page for every navigation. The public API is unchanged, so
``transactions_crawl/fetch.py`` and ``hof_exec/fetch.py`` switch backends with
*zero* code changes (they only call ``get_driver()``, ``warmup_once(base)``,
``reset_driver()`` and use ``.get(url)`` / ``.page_source`` on the result).

What this module provides on top of the raw page:
  * A thin ``_PWDriver`` wrapper exposing the ``WebDriver``-like surface the
    fetch modules rely on (``.get(url)`` + ``.page_source``), so the callers
    never see a Playwright object directly.
  * Inline Cloudflare JS/browser-challenge handling, copied from the proven
    ``external_crawler/crawler/br_injuries_playwright.py`` recipe (detect the
    "Checking your browser" / "Just a moment" interstitial, sleep, reload).
  * Best-effort teardown of the Playwright ``pw`` / ``browser`` / ``context``
    resources, so a dead driver can be discarded and rebuilt by the caller.

Public API (identical to the old UC-Chrome version):
  * ``get_driver()``      — return the process-wide driver (builds on first call)
  * ``reset_driver()``    — invalidate the current driver; next ``get_driver()``
                            rebuilds it (old one quit, errors ignored)
  * ``warmup_once(base)`` — hit ``base`` exactly once on the live driver
  * ``quit_driver()``     — quit the driver (registered with ``atexit``)

Import safety:
  ``playwright`` / ``playwright_stealth`` are imported **lazily inside**
  ``_build_driver`` (i.e. only when ``get_driver`` is first called), so
  importing this module is harmless offline and never launches a browser.
  ``_build_driver`` is a module-level function on purpose: QA monkeypatches
  ``common.browser._build_driver`` to return a fake driver instead of a real
  Playwright instance.
"""

from __future__ import annotations

import atexit
import logging
import threading
import time

logger = logging.getLogger(__name__)


class CFChallengeError(Exception):
    """Raised when a page stays behind a Cloudflare challenge after retries.

    The crawler catches this to pause-and-wait (the user must solve the
    challenge in the connected browser window) rather than silently
    spinning on timeouts.
    """


# ---------------------------------------------------------------------------
# Module-level state. All mutations are guarded by _LOCK for thread safety.
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_DRIVER: object | None = None          # the live _PWDriver (or fake), or None
_INVALID: bool = False                 # True => must rebuild before next use
_WARMED: bool = False                  # True => warm-up already done this driver
_CDP: bool = False                    # True => 当前 driver 是 CDP 直连的用户浏览器

# Stable per-process user agent so cached pages are reproducible. Playwright
# manages its own throwaway profile, so we do not need a --user-data-dir.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)


class _PWDriver:
    """Thin ``WebDriver``-like wrapper around a Playwright page.

    The fetch modules only need two things from a driver:

      * ``driver.get(url)``  — navigate to a page,
      * ``driver.page_source`` — the rendered HTML.

    This class bridges that tiny surface onto a real Playwright ``Page``, while
    also transparently riding out a Cloudflare JS/browser check. All underlying
    Playwright handles (``pw`` / ``browser`` / ``context`` / ``page``) are kept
    as private attributes so ``_teardown`` can close them on reset/quit.
    """

    def __init__(self, pw, browser, context, page) -> None:
        """Store the Playwright handles for later navigation and teardown."""
        self._pw = pw
        self._browser = browser
        self._context = context
        self._page = page

    def get(self, url: str, _tries: int = 20) -> None:
        """Navigate to ``url`` and transparently ride out a Cloudflare challenge.

        A ``cf_clearance`` cookie expires (~30-60 min), after which
        Cloudflare re-issues a challenge that **cannot** be solved by
        automation — a human must click through in the browser window.
        So instead of blindly retrying (which just spins on timeouts),
        we DETECT the challenge and **wait** for the user to solve it,
        polling the page up to ``_tries`` times. This is the realistic
        ceiling for a Cloudflare-protected site: the crawler auto-pauses
        and auto-resumes once the user clears the check, no cookie-pasting
        required (we drive the user's browser directly via CDP).

        Raises ``CFChallengeError`` if the challenge is not cleared within
        ``_tries`` polls (the caller should then pause/alert).
        """
        last_err = None
        for _ in range(_tries):
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as _e:  # noqa: BLE001 - a challenged
                last_err = _e                     # page may never fire DCL
            if not self._is_challenged():
                self._flag_cf(False)
                return
            # Challenge still up: tell the user and wait for them to solve it.
            self._flag_cf(True)
            logger.warning(
                "Cloudflare challenge active — solve it in the browser "
                "window (click through); crawler auto-resumes"
            )
            time.sleep(15)
            try:
                self._page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception:  # noqa: BLE001 - best-effort reload
                pass
        self._flag_cf(False)
        raise CFChallengeError(
            f"Cloudflare challenge not cleared after {_tries} polls: {last_err}"
        )

    @property
    def page_source(self) -> str:
        """Return the current page's rendered HTML."""
        return self._page.content()

    # 哨兵文件：CF 挑战期间存在，用户解除后移除（供监控/用户判断）。
    _CF_FLAG = "/tmp/br_cf_challenge.flag"

    def _flag_cf(self, on: bool) -> None:
        import os as _os
        try:
            if on:
                with open(self._CF_FLAG, "w") as _f:
                    _f.write("cf challenge active; solve it in the browser window\n")
            else:
                if _os.path.exists(self._CF_FLAG):
                    _os.remove(self._CF_FLAG)
        except Exception:  # noqa: BLE001 - best-effort
            pass

    def _is_challenged(self) -> bool:
        """Detect a live Cloudflare challenge on the current page."""
        try:
            u = self._page.url or ""
            if "__cf_chl_rt_tk" in u or "cf_chl" in u:
                return True
            txt = self._page.evaluate(
                "() => (document.body && document.body.innerText) "
                "? document.body.innerText.slice(0, 500) : ''"
            )
            return (
                "Checking your browser" in txt
                or "Just a moment" in txt
                or "Verify you are human" in txt
            )
        except Exception:  # noqa: BLE001 - page mid-navigation etc.
            return False


def _build_driver():
    """Build and return a fresh Playwright driver (stealth-injected).

    This is a module-level function so QA can monkeypatch
    ``common.browser._build_driver`` to return a fake driver. Construction
    pulls in ``playwright`` and ``playwright_stealth`` lazily; if the stealth
    library is missing we log a warning and continue **without** stealth rather
    than crashing (the page still loads, just less effectively).

    Returns a ``_PWDriver`` wrapping the Playwright ``pw`` / ``browser`` /
    ``context`` / ``page``. Raises whatever Playwright raises on launch/nav
    setup — ``get_driver`` lets those bubble to the caller's retry loop.
    """
    # CDP 直连模式：直接驱动用户「已手动过 CF」的 Chrome（同源 cookie，
    # 无跨浏览器指纹错配），比「搬 cookie 注入 headless」可靠得多。
    if _os.environ.get("BROWSER_BACKEND", "playwright").lower() == "cdp":
        return _build_driver_cdp()

    _CDP = False  # 无头分支：确保状态正确（每进程单一后端）
    from playwright.sync_api import sync_playwright

    try:
        from playwright_stealth import Stealth
    except ImportError:  # pragma: no cover - depends on the host environment
        Stealth = None
        logger.warning(
            "playwright_stealth not installed; building driver WITHOUT stealth "
            "injection (Cloudflare bypass may be weaker)"
        )

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    context = browser.new_context(
        user_agent=_USER_AGENT,
        locale="en-US",
        viewport={"width": 1440, "height": 900},
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
        },
    )
    page = context.new_page()

    # Optional Cloudflare clearance cookie injection. If BR_COOKIE_FILE points
    # to a JSON file (a list of {"name","value"} objects, or a single dict),
    # inject those cookies into the fresh context so a manually-passed CF
    # challenge (issued in a real browser) can be reused by this headless
    # driver. Without the file (or if it fails to load) behavior is completely
    # unchanged.
    _cookie_file = _os.environ.get("BR_COOKIE_FILE")
    if _cookie_file and _os.path.exists(_cookie_file):
        try:
            import json
            with open(_cookie_file, "r", encoding="utf-8") as _fh:
                _cookies = json.load(_fh)
            if isinstance(_cookies, dict):
                _cookies = [_cookies]
            _add = []
            for _c in _cookies:
                _name = _c.get("name") or _c.get("Name")
                _value = _c.get("value") or _c.get("Value") or _c.get("content")
                if not _name or _value is None:
                    continue
                for _dom in (".basketball-reference.com", "www.basketball-reference.com"):
                    _add.append({
                        "name": _name,
                        "value": _value,
                        "domain": _dom,
                        "path": "/",
                    })
            if _add:
                context.add_cookies(_add)
                logger.info(
                    "injected %d CF cookies from %s", len(_add), _cookie_file
                )
        except Exception as _e:  # noqa: BLE001 - best-effort
            logger.warning("failed to load BR_COOKIE_FILE: %s", _e)

    # playwright_stealth: full 20+ parameter CF bypass (identical to the
    # validated br_injuries_playwright.py configuration).
    if Stealth is not None:
        Stealth(
            navigator_webdriver=True,
            webgl_vendor=True,
            chrome_app=True,
            chrome_csi=True,
            chrome_load_times=True,
            chrome_runtime=True,
            iframe_content_window=True,
            media_codecs=True,
            navigator_languages=True,
            navigator_permissions=True,
            navigator_plugins=True,
            navigator_hardware_concurrency=True,
            navigator_platform=True,
            navigator_user_agent=True,
            navigator_vendor=True,
            hairline=True,
            sec_ch_ua=True,
            error_prototype=True,
        ).apply_stealth_sync(page)

    return _PWDriver(pw, browser, context, page)


# ---------------------------------------------------------------------------
# Raw CDP helpers (NO Playwright — against a stock user Chrome,
# ``connect_over_cdp`` emits a ``Browser.setDownloadBehavior`` call this
# Chrome rejects, aborting the whole connect; raw CDP sidesteps it).
# ---------------------------------------------------------------------------
def _CDP_BASE() -> str:
    return _os.environ.get("CHROME_CDP_URL", "http://127.0.0.1:9222")


def _cdp_http_get(path: str):
    import json as _json
    import urllib.request as _u
    with _u.urlopen(f"{_CDP_BASE()}{path}", timeout=10) as _r:
        return _json.loads(_r.read())


def _cdp_call_browser(method: str, params=None, timeout=30):
    """Send one CDP command to the *browser* endpoint, return its result."""
    import asyncio
    import json as _json
    import websockets
    ver = _cdp_http_get("/json/version")
    bws = ver["webSocketDebuggerUrl"]

    async def go():
        async with websockets.connect(
            bws, max_size=None, ping_interval=None, open_timeout=15
        ) as ws:
            await ws.send(_json.dumps({"id": 1, "method": method, "params": params or {}}))
            while True:
                m = _json.loads(await asyncio.wait_for(ws.recv(), timeout))
                if m.get("id") == 1:
                    if "error" in m:
                        raise RuntimeError(f"CDP {method} error: {m['error']}")
                    return m.get("result")

    return asyncio.run(go())


class _RawCDPDriver:
    """Drive a *single* page target in the user's Chrome via raw CDP.

    Avoids Playwright's ``connect_over_cdp`` entirely (that emits
    ``Browser.setDownloadBehavior`` which a stock user Chrome rejects with
    "Browser context management is not supported", aborting the connect).
    Raw CDP — the same channel ``cookie_refresher`` already uses
    successfully — just opens a dedicated page target and navigates /
    evaluates it directly.

    Exposes the same ``WebDriver``-like surface as ``_PWDriver``
    (``.get(url)`` / ``.page_source``) so the fetch modules are
    completely untouched.
    """

    def __init__(self, target_ws: str, target_id: str) -> None:
        self._ws = target_ws
        self._tid = target_id

    # -- low-level CDP (fresh websocket per call; the target itself
    #    persists in the browser so navigation state is retained) ----------
    @staticmethod
    def _send(target_ws: str, method: str, params=None, timeout=60):
        import asyncio
        import json as _json
        import websockets

        async def go():
            async with websockets.connect(
                target_ws, max_size=None, ping_interval=None, open_timeout=15
            ) as ws:
                await ws.send(_json.dumps({"id": 1, "method": method, "params": params or {}}))
                while True:
                    m = _json.loads(await asyncio.wait_for(ws.recv(), timeout))
                    if m.get("id") == 1:
                        if "error" in m:
                            raise RuntimeError(f"CDP {method} error: {m['error']}")
                        return m.get("result")

        return asyncio.run(go())

    def _eval(self, expr: str, timeout=60):
        r = self._send(
            self._ws,
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": False},
            timeout=timeout,
        )
        return (r or {}).get("result", {}).get("value")

    # -- public WebDriver-like surface --------------------------------------
    def get(self, url: str, _tries: int = 40) -> None:
        """Navigate to ``url`` and ride out a Cloudflare challenge.

        The BR Cloudflare interstitial (English "Checking your browser" /
        "Verify you are human", or zh-CN "请稍候… / 正在进行安全验证")
        forwards to the real page automatically a few seconds after
        navigation *if* a valid ``cf_clearance`` cookie is present. So we
        navigate once, then POLL until it clears (valid cookie → a few
        seconds) or the wait budget is spent.

        On a *stale* cookie the page never forwards, so we keep the
        ``/tmp/br_cf_challenge.flag`` sentinel ON and sleep ~30s per
        round, giving the user time to click through in the 9222 window.
        The crawler thus PAUSES in place (does NOT spin failing requests
        against every player) and auto-resumes the moment CF clears.
        Only raises ``CFChallengeError`` if it stays challenged past the
        whole budget (~30 min) — a genuine "user never came back" case.
        """
        import time as _t
        last_err = None
        for _ in range(_tries):
            try:
                self._send(self._ws, "Page.enable", timeout=30)
                self._send(self._ws, "Page.navigate", {"url": url}, timeout=40)
            except Exception as _e:  # noqa: BLE001 - navigation may be delayed
                last_err = _e
            # poll up to ~20s for the challenge to auto-forward
            cleared = False
            for _w in range(40):
                _t.sleep(0.5)
                try:
                    if not self._is_challenged():
                        cleared = True
                        break
                except Exception:  # noqa: BLE001
                    pass
            if cleared:
                self._flag_cf(False)
                return
            # still challenged: keep the sentinel ON, give the user time
            self._flag_cf(True)
            logger.warning(
                "Cloudflare challenge active — solve it in the browser "
                "window (click through); crawler auto-resumes"
            )
            _t.sleep(30)
        # budget exhausted: leave the flag ON (we WERE waiting) and raise
        self._flag_cf(True)
        raise CFChallengeError(
            f"Cloudflare challenge not cleared after {_tries} rounds: {last_err}"
        )

    @property
    def page_source(self) -> str:
        return self._eval("document.documentElement.outerHTML") or ""

    def _is_challenged(self) -> bool:
        try:
            u = self._eval("location.href") or ""
            if "__cf_chl_rt_tk" in u or "cf_chl" in u:
                return True
            txt = (
                self._eval(
                    "(() => (document.body ? document.body.innerText.slice(0,500) : ''))()"
                )
                or ""
            )
            return any(
                k in txt
                for k in (
                    "Checking your browser",
                    "Just a moment",
                    "Verify you are human",
                    "请稍候",
                    "正在进行安全验证",
                    "安全验证",
                    "安全服务防护",
                )
            )
        except Exception:  # noqa: BLE001
            return False

    _CF_FLAG = "/tmp/br_cf_challenge.flag"

    def _flag_cf(self, on: bool) -> None:
        import os as _os
        try:
            if on:
                with open(self._CF_FLAG, "w") as _f:
                    _f.write("cf challenge active; solve it in the browser window\n")
            else:
                if _os.path.exists(self._CF_FLAG):
                    _os.remove(self._CF_FLAG)
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        """Close ONLY the page target we opened — never the user's browser."""
        try:
            _cdp_call_browser("Target.closeTarget", {"targetId": self._tid})
        except Exception:  # noqa: BLE001
            pass


def _build_driver_cdp():
    """Build a driver by driving a *dedicated* page in the user's Chrome
    via raw CDP (NOT Playwright ``connect_over_cdp`` — that emits a
    ``Browser.setDownloadBehavior`` call this stock Chrome rejects).

    Opens a fresh page target so the user's existing BR tab is untouched,
    then returns a ``_RawCDPDriver`` pointing at it.

    Env:
      CHROME_CDP_URL  (default http://127.0.0.1:9222) — the
                         remote-debugging port of the user's Chrome,
                         launched e.g. via launch_chrome_cdp.sh.
    """
    global _CDP
    _CDP = True

    base = _CDP_BASE()
    # 1. create a dedicated blank page target
    try:
        res = _cdp_call_browser("Target.createTarget", {"url": "about:blank", "newWindow": False})
        tid = (res or {}).get("targetId")
    except Exception as _e:  # noqa: BLE001
        logger.warning("CDP createTarget failed (%s); reusing an existing page", _e)
        tid = None
    # 2. resolve its page-level websocket URL
    targets = _cdp_http_get("/json")
    entry = next((t for t in targets if t.get("id") == tid), None) if tid else None
    if not entry:
        entry = next((t for t in targets if t.get("type") == "page"), None)
    if not entry or "webSocketDebuggerUrl" not in entry:
        raise RuntimeError("CDP: no usable page target found in the user's Chrome")
    page_ws = entry["webSocketDebuggerUrl"]
    logger.info(
        "connected to user Chrome via raw CDP (target %s); driving it directly", tid
    )
    return _RawCDPDriver(page_ws, entry.get("id", ""))


def _teardown(drv) -> None:
    """Best-effort teardown of a driver's Playwright resources.

    Closes the browser and context, then stops the Playwright runner. Every
    step swallows exceptions so a wedged browser never blocks reset/quit.

    CDP mode (``_CDP``): the "browser" is the user's running Chrome.
    We must NEVER close it — only close the page we opened and stop the
    Playwright driver, leaving the user's window fully intact.
    """
    if drv is None:
        return
    if _CDP:
        try:
            drv.close()  # _RawCDPDriver: only closes OUR page target
        except Exception:  # noqa: BLE001 - best-effort
            pass
        return
    try:
        drv._browser.close()
    except Exception:  # noqa: BLE001 - best-effort teardown
        pass
    try:
        drv._context.close()
    except Exception:  # noqa: BLE001 - best-effort teardown
        pass
    try:
        drv._pw.stop()
    except Exception:  # noqa: BLE001 - best-effort teardown
        pass


def get_driver():
    """Return the process-wide Playwright driver, building it on first use.

    Thread-safe. If ``reset_driver()`` was called (or the driver died), a new
    instance is built and returned. Concurrent callers share a single instance.
    """
    global _DRIVER, _INVALID
    with _LOCK:
        if _DRIVER is not None and not _INVALID:
            return _DRIVER
        # (Re)build under the lock so concurrent callers share one instance
        # instead of each launching their own browser.
        if _DRIVER is not None:
            try:
                if not _CDP:  # CDP 模式绝不关用户浏览器
                    _DRIVER._browser.close()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
        logger.info("building shared Playwright driver (process-wide singleton)")
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
            _teardown(_DRIVER)
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
    try:
        driver = get_driver()
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
        _teardown(_DRIVER)
        _DRIVER = None
        _INVALID = True
        _WARMED = False


# Tear down the shared driver on normal interpreter exit.
atexit.register(quit_driver)

# === 后端选择：UC-Chrome 作为 Playwright 的备案（BROWSER_BACKEND=uc 时启用） ===
# 默认（不设置或 =playwright）保持上方 Playwright 实现，既有测试零改动。
# 设 BROWSER_BACKEND=uc 时，在模块加载期把公开 API 重新绑定到 common.browser_uc；
# fetch.py 用 `from common.browser import get_driver, reset_driver, warmup_once`
# 在 import 时即拿到最终绑定值，因此零改动即可切换后端。
import os as _os
_BACKEND = _os.environ.get("BROWSER_BACKEND", "playwright").lower()
if _BACKEND == "uc":
    from common import browser_uc
    get_driver = browser_uc.get_driver
    reset_driver = browser_uc.reset_driver
    warmup_once = browser_uc.warmup_once
    quit_driver = browser_uc.quit_driver
    _build_driver = browser_uc._build_driver
    atexit.register(quit_driver)  # 重新注册为 UC 版退出钩子
