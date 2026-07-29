"""BR 球员页爬虫 —— Scrapling 隐身传输增强子类（继承现有基类，不改动基类）。

仅覆写「抓取传输」这一段（``fetch_team_page``）：用 Scrapling 的 ``StealthyFetcher``
（patchright 隐身 + Cloudflare 自动解算）经 ``connect_over_cdp`` 接管我方自管
Chrome（默认 9222），其余 cache-first 落盘 / 断点续跑 / 404 隔离 / 本地重放 /
去重入库 全部继承 ``BRPlayerPageCrawler``，一字不改。

设计依据：``docs/crawler_scrapling_inherit_design.md`` §5.1
"""
from __future__ import annotations

import logging
from typing import Optional

from common.br_player_page import BRPlayerPageCrawler

logger = logging.getLogger(__name__)

# Cloudflare 挑战页特征串（把「CF 拦截」与「真 404/空」区分开）
CF_MARKERS = (
    "Just a moment",
    "Checking your browser",
    "cf-chl-",
    "challenge-platform",
    "Verify you are human",
)
# BR 404 / 不存在页面特征串
NOT_FOUND_MARKERS = (
    "Page Not Found",
    "could not be found",
    "Basketball-Reference.com - 404",
)


class BRPlayerPageCrawlerStealth(BRPlayerPageCrawler):
    """继承现有主流程，仅把抓取传输替换为 Scrapling Fetcher（隐身 + CF 解算）。"""

    def __init__(self, cache_dir: Optional[str] = None,
                 dry_run: bool = False, resume: bool = False,
                 cdp_url: str = "http://127.0.0.1:9222",
                 use_stealth: bool = True, **kw) -> None:
        super().__init__(cache_dir=cache_dir, dry_run=dry_run, resume=resume)
        self._cdp_url = cdp_url
        self._use_stealth = use_stealth
        self._fetcher_cls = None  # 懒加载，避免 import 期硬依赖 scrapling

    @staticmethod
    def _resolve_cdp_ws(http_url: str) -> str:
        """把 http(s)://host:port 的 CDP 端点解析成浏览器级 ws:// 调试 URL。

        Scrapling 的 ``cdp_url`` 只接受 ``ws://`` / ``wss://``（来自
        ``/json/version`` 的 ``webSocketDebuggerUrl``），不接受 http JSON 端点。
        """
        import json
        import urllib.request
        try:
            with urllib.request.urlopen(
                http_url.rstrip("/") + "/json/version", timeout=5
            ) as r:
                data = json.load(r)
            return data.get("webSocketDebuggerUrl") or ""
        except Exception as _e:  # noqa: BLE001
            logging.getLogger(__name__).warning("解析 CDP ws 失败: %s", _e)
            return ""

    # —— 唯一覆写点：抓取传输（对应基类 _crawl_player 的 fetch 落点）——
    def fetch_team_page(self, driver, url: str) -> str:
        self._last_fetch_cf = False
        self._last_fetch_404 = False
        if self._fetcher_cls is None:
            from scrapling import StealthyFetcher  # 懒加载
            self._fetcher_cls = StealthyFetcher
        # 归一化 CDP 端点：http → ws（Scrapling 要求 ws://）
        # 若 self._cdp_url 为空/None，则不传 cdp_url，
        # 让 StealthyFetcher 自己启动隐身 Chromium（避免与已被我方
        # Playwright 接管的 Chrome 抢同一会话导致 Network 拦截冲突）。
        cdp = self._cdp_url
        if cdp:
            if cdp.startswith("http"):
                cdp = self._resolve_cdp_ws(cdp) or cdp
        kw = dict(
            url=url,
            solve_cloudflare=True,
            wait_selector="#content",
            timeout=30_000,
            wait=1_000,
            headless=True,
            network_idle=True,
            load_dom=True,
            google_search=True,
        )
        if cdp:
            kw["cdp_url"] = cdp
        try:
            resp = self._fetcher_cls.fetch(**kw)
        except Exception as exc:  # noqa: BLE001 - 抓取异常当作无页
            logger.warning("Stealth fetch 异常 %s: %s", url, exc)
            return ""
        if resp is None:
            return ""
        status = getattr(resp, "status", None)
        if status == 404:
            self._last_fetch_404 = True
            logger.warning("BR 404 → 隔离: %s", url)
            return ""
        # 取 HTML 文本（兼容 .text / .body）
        html = getattr(resp, "text", None)
        if not html:
            body = getattr(resp, "body", b"")
            html = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else (body or "")
        if not html:
            return ""
        if any(m in html for m in CF_MARKERS):
            self._last_fetch_cf = True
            logger.warning("CF 挑战页，暂停: %s", url)
            return ""
        if any(m in html for m in NOT_FOUND_MARKERS):
            self._last_fetch_404 = True
            logger.warning("BR 不存在页面，隔离: %s", url)
            return ""
        return html
