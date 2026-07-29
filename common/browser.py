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
# 共享 Cloudflare 防撞 + 自恢复熔断器（全爬虫共用，见 common/cf_breaker.py）
# 在 get() 层挂一个模块级实例：凡是经本模块 get() 的爬虫
# （gamelog / fill_player_cache / headshots / transactions / injuries /
# contracts / schedule ... 几十个）都自动获得「连续撞墙→熔断冷却→自恢复」，
# 无需每个爬虫各写一遍。默认 max_cooldowns=0 = 无限自恢复。
# ---------------------------------------------------------------------------
import os as _os  # 模块级，供下方 _BREAKER 读取 CF_* 环境变量
from .cf_breaker import CFBreaker  # noqa: E402  (同包, 仅依赖标准库)

_BREAKER = CFBreaker(
    breach_limit=int(_os.environ.get("CF_BREACH_LIMIT", "5")),
    backoff=int(_os.environ.get("CF_BACKOFF", "30")),
    cooldown=int(_os.environ.get("CF_COOLDOWN", "600")),
    max_cooldowns=int(_os.environ.get("CF_MAX_COOLDOWNS", "0")),
)
_CF_INNER_TRIES = 3  # 单页面内部重试上限（< breach_limit，避免单球员就触发熔断）


def configure_breaker(breach_limit=None, backoff=None, cooldown=None,
                      max_cooldowns=None) -> None:
    """运行时调参（爬虫 CLI 可调用，覆盖 env / 默认值）。"""
    if breach_limit is not None:
        _BREAKER.breach_limit = int(breach_limit)
    if backoff is not None:
        _BREAKER.backoff = int(backoff)
    if cooldown is not None:
        _BREAKER.cooldown = int(cooldown)
    if max_cooldowns is not None:
        _BREAKER.max_cooldowns = int(max_cooldowns)


# ---------------------------------------------------------------------------
# Cloudflare 握手（爬取前置门禁）
# ---------------------------------------------------------------------------
# 在「爬虫自己驱动的那个标签页」里先导航到 BR 主页，检测 CF 挑战；若命中则写
# 哨兵文件 + 打印醒目标语，并轮询同一标签页直到挑战消失（真实 BR 内容出现）
# 再继续。这样用户清的一定就是爬虫正在驱动的那个 tab，杜绝「A 标签清了、爬虫
# 驱动 B 标签」的错配——这正是 player_shooting A 阶段「全新 profile 无
# cf_clearance → 全缺口 0 行 → 缺口永久卡住」的根因。
_BR_HOMEPAGE = "https://www.basketball-reference.com/"
_CF_FLAG = "/tmp/br_cf_challenge.flag"


def _write_cf_flag() -> None:
    """写 CF 挑战哨兵文件（best-effort）。"""
    try:
        with open(_CF_FLAG, "w") as _f:
            _f.write("cf challenge active; solve it in the browser window\n")
    except Exception:  # noqa: BLE001 - best-effort
        pass


def _clear_cf_flag() -> None:
    """移除 CF 挑战哨兵文件（best-effort）。"""
    try:
        if _os.path.exists(_CF_FLAG):
            _os.remove(_CF_FLAG)
    except Exception:  # noqa: BLE001 - best-effort
        pass


def ensure_cf_cleared(driver, base_url: str = _BR_HOMEPAGE,
                      poll: float = 10.0, timeout: "float | None" = None) -> bool:
    """Block until the page the crawler is driving clears the CF challenge.

    Navigates the driver's *current* (driven) tab to ``base_url`` — the exact
    tab the crawl will use — so whatever challenge the user solves is the one
    gating the crawl. If the page is a CF challenge, writes the
    ``/tmp/br_cf_challenge.flag`` sentinel and prints a prompt, then polls
    every ``poll`` seconds until the challenge clears (real BR content appears)
    or ``timeout`` elapses. Returns ``True`` if cleared, ``False`` on timeout.

    Safe to call from any crawler right after ``get_driver()`` and before the
    main fetch loop. Works for both the Playwright (``_PWDriver``) and raw-CDP
    (``_RawCDPDriver``) backends — both expose ``_navigate`` / ``_is_challenged``.
    """
    if driver is None:
        return True
    # Fire-and-forget navigation (no internal challenge poll): we own the poll
    # loop below so the interval is exactly ``poll`` and the user's manual
    # click-through is what clears it.
    try:
        driver._navigate(base_url)
    except Exception as _e:  # noqa: BLE001 - navigation may be delayed
        logger.warning("CF 握手导航 %s 失败（仍继续检测）: %s", base_url, _e)
    deadline = None if timeout is None else time.time() + timeout
    while True:
        try:
            if not driver._is_challenged():
                _clear_cf_flag()
                return True
        except Exception:  # noqa: BLE001 - page mid-navigation
            pass
        _write_cf_flag()
        logger.warning(
            "Cloudflare 挑战页命中 %s — 请在弹出的 Chrome 窗口手动通过验证"
            "（点击 'Verify you are human'），爬虫将自动继续。", base_url)
        print("==============================================================")
        print(">>> 请在【爬虫驱动的那个 Chrome 标签页】手动通过 Cloudflare 验证")
        print(">>> （点击 'Verify you are human'）。验证通过后爬虫自动继续。")
        print("==============================================================")
        if deadline is not None and time.time() > deadline:
            _clear_cf_flag()
            logger.error("CF 握手超时（%ss）：放弃等待，爬虫以当前页面继续。", timeout)
            return False
        time.sleep(poll)


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

    def get(self, url: str, _tries: int = _CF_INNER_TRIES) -> None:
        """Navigate to ``url`` and transparently ride out a Cloudflare challenge.

        A ``cf_clearance`` cookie expires (~30-60 min), after which
        Cloudflare re-issues a challenge that **cannot** be solved by
        automation — a human must click through in the browser window.
        So instead of blindly retrying (which just spins on timeouts),
        we DETECT the challenge and **wait** for the user to solve it.

        The wait is delegated to the shared ``_BREAKER`` (common.cf_breaker):
        each challenge detection calls ``_BREAKER.on_breach()``, which does the
        backoff/cooldown *sleep* and returns a decision. When Cloudflare is
        in a site-wide storm (the common case), the breaker trips after
        ``breach_limit`` *cumulative* breaches across players and **cools down
        for ``cooldown`` seconds with zero network requests** — so we never
        burn the whole crawl budget spinning (the old 20×15s-per-player
        behaviour). After cooldown it auto-resets and the crawl self-resumes.

        Raises ``CFChallengeError`` only when ``max_cooldowns`` is exceeded
        (the breaker gives up); otherwise it returns the (likely still
        challenged) page source and lets the caller skip that one page.
        """
        last_err = None
        for _ in range(_tries):
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as _e:  # noqa: BLE001 - a challenged
                last_err = _e                     # page may never fire DCL
            if not self._is_challenged():
                self._flag_cf(False)
                _BREAKER.on_success()
                return
            # Challenge still up → feed the shared breaker (does backoff/cooldown
            # sleep internally; on "giveup" it returns that decision).
            self._flag_cf(True)
            decision = _BREAKER.on_breach()
            if decision == "giveup":
                self._flag_cf(False)
                raise CFChallengeError(
                    f"Cloudflare challenge not cleared after breaker gave up: {last_err}"
                )
            logger.warning(
                "Cloudflare challenge active — solve it in the browser "
                "window (click through); crawler auto-resumes"
            )
            try:
                self._page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception:  # noqa: BLE001 - best-effort reload
                pass
        # Exhausted inner retries: return (likely challenged) source; the
        # caller checks content and skips. Default max_cooldowns=0 means the
        # breaker never gives up, so we self-recover seamlessly.
        self._flag_cf(False)

    @property
    def page_source(self) -> str:
        """Return the current page's rendered HTML."""
        return self._page.content()

    def _navigate(self, url: str, timeout: int = 30000) -> None:
        """Fire-and-forget navigation (no CF poll); the caller owns the poll.

        Used by ``ensure_cf_cleared`` so the handshake controls the polling
        interval exactly instead of relying on ``get``'s internal retry loop.
        """
        self._page.goto(url, wait_until="domcontentloaded", timeout=timeout)

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


def _cdp_ws_url(raw: str) -> str:
    """Force a CDP webSocketDebuggerUrl onto the SAME host:port as the
    configured CDP HTTP endpoint (``_CDP_BASE()``).

    Two real-world traps are defeated here:

    1. macOS ``localhost`` resolves to IPv6 ``::1`` while the CDP
       websocket is bound to IPv4 ``127.0.0.1`` → ``Connection refused
       (Errno 61)``. Force the IPv4 literal.

    2. **Chrome's ``/json/version`` may advertise a ``webSocketDebuggerUrl``
       whose PORT differs from the HTTP port.** After an auto-update
       reassigned the browser to a *random* debugging port (while the HTTP
       endpoint stayed on the configured port), or when a stray second
       Chrome instance is present, the advertised port can be e.g. ``62470``
       while the reachable HTTP port is ``9223``. Trusting that port made
       the crawler chase a **dead** target — ``[Errno 61] Connect call
       failed ('127.0.0.1', 62470)`` — and wedge forever retrying a
       connection that never comes back. Force host+port to the base we
       already curled successfully, so every CDP call lands on the browser
       we know is up.
    """
    if not raw:
        return raw
    import re as _re
    import urllib.parse as _up
    base = _up.urlparse(_CDP_BASE())
    host = "127.0.0.1"                     # macOS: localhost → IPv6 ::1
    port = base.port                         # force the reachable HTTP port
    scheme = "wss" if base.scheme == "https" else "ws"
    m = _re.search(r"(/devtools/(?:browser|page)/[^/?#]+)", raw)
    path = m.group(1) if m else "/devtools/browser"
    return f"{scheme}://{host}:{port}{path}"


# createTarget 重试：全新 CDP Chrome 启动后 target 子系统可能比 websocket 晚就绪
# 一秒多，首次 Target.createTarget 会报 "no browser is open"。这里轮询重试而不是
# 静默复用可能空白的已有页面（那正是「驱动了错误 tab」的隐患之一）。
_CDP_CREATE_TARGET_TRIES = 15    # 重试上限（≈30s @ 2s）
_CDP_CREATE_TARGET_WAIT = 2.0   # 每次重试间隔（秒）


def _cdp_http_get(path: str):
    import json as _json
    import urllib.request as _u
    # CDP 接口永远是本机 localhost（默认 http://127.0.0.1:9222）。
    # 在设置了 HTTP(S)_PROXY 的环境（如沙箱设了 HTTP_PROXY=127.0.0.1:54323）
    # 下，裸 urlopen 会把 127.0.0.1 也塞进代理 → 502 Bad Gateway / 连接错误，
    # 哪怕本机真有 CDP Chrome。用 ProxyHandler({}) 建一个**绕过代理**的
    # opener 直连 CDP（CDP 永远是 localhost，直连才正确）。最小化改动。
    _opener = _u.build_opener(_u.ProxyHandler({}))
    with _opener.open(f"{_CDP_BASE()}{path}", timeout=10) as _r:
        return _json.loads(_r.read())


def _cdp_call_browser(method: str, params=None, timeout=30):
    """Send one CDP command to the *browser* endpoint, return its result."""
    import asyncio
    import json as _json
    import websockets
    ver = _cdp_http_get("/json/version")
    bws = _cdp_ws_url(ver["webSocketDebuggerUrl"])

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


def _cdp_validate_target(page_ws: str, tid: str) -> None:
    """Prove ``page_ws`` actually connects BEFORE handing it to the crawler.

    A dead target (e.g. a stale tab whose renderer died but Chrome
    still lists it in ``/json``) would otherwise make the crawler hang
    retrying a connection that never answers — exactly the 2026-07-28
    ``[Errno 61] Connect call failed ('127.0.0.1', 62470)`` wedge.
    On failure we close that target and raise so ``_build_driver_cdp``
    can drop it and try a fresh one instead of returning a dead driver.
    """
    try:
        _RawCDPDriver._send(
            page_ws, "Runtime.evaluate",
            {"expression": "1+1", "returnByValue": True}, timeout=10)
    except Exception as _e:  # noqa: BLE001
        try:
            _cdp_call_browser("Target.closeTarget", {"targetId": tid})
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"CDP target {tid} ws unreachable: {_e}") from _e


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
    def get(self, url: str, _tries: int = _CF_INNER_TRIES) -> None:
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
            # still challenged → feed the shared breaker (does backoff/cooldown
            # sleep internally; on "giveup" it returns that decision).
            self._flag_cf(True)
            decision = _BREAKER.on_breach()
            if decision == "giveup":
                self._flag_cf(False)
                raise CFChallengeError(
                    f"Cloudflare challenge not cleared after breaker gave up: {last_err}"
                )
            logger.warning(
                "Cloudflare challenge active — solve it in the browser "
                "window (click through); crawler auto-resumes"
            )
        # Inner retries exhausted for this one page (CF still up). With the
        # shared breaker, a site-wide storm would already have cooled down
        # (and self-resumed) *across* players; a single stubborn page is
        # just skipped — no raise by default, so callers never crash on CF.
        self._flag_cf(False)

    def _navigate(self, url: str, timeout: int = 40) -> None:
        """Fire-and-forget navigation (no CF poll); the caller owns the poll.

        Used by ``ensure_cf_cleared`` so the handshake controls the polling
        interval exactly instead of relying on ``get``'s internal retry loop.
        """
        self._send(self._ws, "Page.enable", timeout=30)
        self._send(self._ws, "Page.navigate", {"url": url}, timeout=timeout)

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
    # 1. open a dedicated blank page target. On a freshly launched CDP Chrome
    #    the target subsystem can lag the websocket by a second or two, so
    #    Target.createTarget may fail with "no browser is open". Poll + retry
    #    instead of silently reusing a possibly-blank existing page.
    tid = None
    last_err = None
    for _attempt in range(1, _CDP_CREATE_TARGET_TRIES + 1):
        try:
            res = _cdp_call_browser(
                "Target.createTarget", {"url": "about:blank", "newWindow": False})
            tid = (res or {}).get("targetId")
            if tid:
                break
        except Exception as _e:  # noqa: BLE001
            last_err = _e
            logger.warning(
                "CDP createTarget 尝试 %d/%d 失败 (%s)；%ss 后重试…",
                _attempt, _CDP_CREATE_TARGET_TRIES, _e, _CDP_CREATE_TARGET_WAIT)
            time.sleep(_CDP_CREATE_TARGET_WAIT)
    # 2. resolve its page-level websocket URL (with a short retry: the freshly
    #    created target may not yet appear in /json immediately after creation).
    entry = None
    for _attempt in range(1, _CDP_CREATE_TARGET_TRIES + 1):
        try:
            targets = _cdp_http_get("/json")
        except Exception as _e:  # noqa: BLE001
            last_err = _e
            targets = []
        entry = next((t for t in targets if t.get("id") == tid), None) if tid else None
        if entry:
            break
        time.sleep(_CDP_CREATE_TARGET_WAIT)
    if not entry:
        # Last-resort fallback: reuse an existing page target. Loud warning so
        # the operator knows we are NOT driving a clean tab we just opened.
        logger.warning(
            "CDP createTarget 重试 %d 次仍失败（%s）；回退到复用已有页面目标",
            _CDP_CREATE_TARGET_TRIES, last_err)
        try:
            targets = _cdp_http_get("/json")
        except Exception:  # noqa: BLE001
            targets = []
        entry = next((t for t in targets if t.get("type") == "page"), None)
        if not entry or "webSocketDebuggerUrl" not in entry:
            raise RuntimeError(
                "CDP: 无法创建或复用任何可用 page target（用户 Chrome 未就绪？）")
        page_ws = _cdp_ws_url(entry["webSocketDebuggerUrl"])
        logger.info(
            "connected to user Chrome via raw CDP (reused target %s); driving it directly",
            entry.get("id", ""))
        _cdp_validate_target(page_ws, entry.get("id", ""))  # 死 target 直接抛错
        return _RawCDPDriver(page_ws, entry.get("id", ""))
    page_ws = _cdp_ws_url(entry["webSocketDebuggerUrl"])
    logger.info(
        "connected to user Chrome via raw CDP (target %s); driving it directly", tid
    )
    _cdp_validate_target(page_ws, tid)  # 连接前验证：死 target 直接抛错让上层换一个
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
