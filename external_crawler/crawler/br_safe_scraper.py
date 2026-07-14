#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BR Safe Scraper — Basketball-Reference 安全爬取模块
====================================================
设计原则:
  1. 请求间隔 10-15 秒 (可配置，最低 10s)
  2. 全局 rate limiter — 所有 BR 请求共享一个时间窗口
  3. Cookie 持久化 — 复用浏览器 session，减少 Cloudflare 验证
  4. 指数退避重试 — 最多 3 次，间隔 30/60/120 秒
  5. Cloudflare 检测 — 自动等待 + 重新验证
  6. 请求日志 — 记录每次请求的时间/状态/URL，便于审计

用法:
  from br_safe_scraper import SafeBRScraper
  
  scraper = SafeBRScraper(min_delay=12, max_delay=18)
  html = scraper.fetch("https://www.basketball-reference.com/players/a/achiupr01.html")
  scraper.close()

  # 或者用 context manager:
  with SafeBRScraper() as scraper:
      html = scraper.fetch(url)
"""
import os
import time
import random
import json
import logging
import hashlib
from datetime import datetime
from typing import Optional, Dict
from pathlib import Path

# ── 第三方依赖 ────────────────────────────────────────────────────────────────

try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

logger = logging.getLogger("BR_Scraper")

# ── 常量 ──────────────────────────────────────────────────────────────────────

BR_BASE = "https://www.basketball-reference.com"
COOKIE_DIR = Path(__file__).parent / ".." / "logs" / "br_cookies"
REQUEST_LOG = Path(__file__).parent / ".." / "logs" / "br_request_log.jsonl"

# 多 UA 轮换
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}


class SafeBRScraper:
    """
    安全的 BR 爬取器，内置限速、Cookie 持久化、Cloudflare 绕过。
    
    Attributes:
        min_delay: 最小请求间隔（秒），默认 12
        max_delay: 最大请求间隔（秒），默认 18
        max_retries: 最大重试次数，默认 3
        use_playwright: 是否使用 Playwright（True=只用浏览器，False=优先 curl_cffi）
    """

    def __init__(
        self,
        min_delay: float = 12.0,
        max_delay: float = 18.0,
        max_retries: int = 3,
        use_playwright: bool = False,
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.use_playwright = use_playwright
        self._last_request_time = 0.0
        self._pw_page = None
        self._pw_browser = None
        self._pw_context = None
        self._session_cookies = {}
        self._request_count = 0
        self._blocked_count = 0

        # 确保 cookie 目录存在
        COOKIE_DIR.mkdir(parents=True, exist_ok=True)

        # 加载之前保存的 cookies
        self._load_cookies()

    # ── Cookie 管理 ───────────────────────────────────────────────────────────

    def _cookie_file(self) -> Path:
        return COOKIE_DIR / "br_session.json"

    def _load_cookies(self):
        """从磁盘加载之前保存的 cookies"""
        try:
            cf = self._cookie_file()
            if cf.exists():
                with open(cf, "r") as f:
                    data = json.load(f)
                    self._session_cookies = data.get("cookies", {})
                    logger.debug(f"Loaded {len(self._session_cookies)} cookies from disk")
        except Exception as e:
            logger.debug(f"Failed to load cookies: {e}")

    def _save_cookies(self):
        """保存 cookies 到磁盘"""
        try:
            cf = self._cookie_file()
            with open(cf, "w") as f:
                json.dump({
                    "cookies": self._session_cookies,
                    "saved_at": datetime.now().isoformat(),
                }, f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to save cookies: {e}")

    # ── 请求日志 ──────────────────────────────────────────────────────────────

    def _log_request(self, url: str, method: str, status: int, duration: float, blocked: bool):
        """记录每次请求到日志文件，便于审计"""
        try:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "url": url,
                "method": method,
                "status": status,
                "duration_ms": round(duration * 1000, 1),
                "blocked": blocked,
                "request_count": self._request_count,
            }
            with open(REQUEST_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    # ── 限速 ──────────────────────────────────────────────────────────────────

    def _wait_rate_limit(self):
        """确保两次请求之间至少间隔 min_delay ~ max_delay 秒"""
        if self._last_request_time > 0:
            elapsed = time.time() - self._last_request_time
            delay = random.uniform(self.min_delay, self.max_delay)
            wait = delay - elapsed
            if wait > 0:
                logger.debug(f"Rate limit: waiting {wait:.1f}s (elapsed {elapsed:.1f}s, target {delay:.1f}s)")
                time.sleep(wait)
        self._last_request_time = time.time()

    # ── Cloudflare 检测 ───────────────────────────────────────────────────────

    @staticmethod
    def _is_cloudflare_block(html: str, title: str = "") -> bool:
        """检测是否被 Cloudflare 拦截"""
        indicators = [
            "Just a moment",
            "Checking your browser",
            "cf-challenge-running",
            "cf-browser-verification",
            "challenge-platform",
            "ray ID",
        ]
        combined = (html or "") + " " + (title or "")
        combined_lower = combined.lower()
        return any(ind.lower() in combined_lower for ind in indicators)

    # ── curl_cffi 方式 ────────────────────────────────────────────────────────

    def _fetch_cffi(self, url: str) -> Optional[str]:
        """使用 curl_cffi 获取页面"""
        if not HAS_CFFI:
            return None

        headers = dict(DEFAULT_HEADERS)
        headers["User-Agent"] = random.choice(USER_AGENTS)
        headers["Referer"] = BR_BASE + "/"

        try:
            resp = cffi_requests.get(
                url,
                headers=headers,
                timeout=20,
                impersonate="chrome124",
                cookies=self._session_cookies,
            )
            if resp.status_code == 200:
                # 保存 cookies
                self._session_cookies.update(dict(resp.cookies))
                self._save_cookies()
                return resp.text
            elif resp.status_code == 403:
                logger.debug(f"  cffi 403 (Cloudflare)")
                return None
            else:
                logger.debug(f"  cffi HTTP {resp.status_code}")
                return None
        except Exception as e:
            logger.debug(f"  cffi error: {e}")
            return None

    # ── Playwright 方式 ───────────────────────────────────────────────────────

    def _init_playwright(self):
        """初始化 Playwright 浏览器（复用 session）"""
        if self._pw_page is not None:
            return

        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth

        self._pw = sync_playwright().start()
        self._pw_browser = self._pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )

        ua = random.choice(USER_AGENTS)
        self._pw_context = self._pw_browser.new_context(
            user_agent=ua,
            locale="en-US",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

        # 注入 cookies
        if self._session_cookies:
            cookie_list = []
            for name, value in self._session_cookies.items():
                cookie_list.append({
                    "name": name,
                    "value": str(value),
                    "domain": ".basketball-reference.com",
                    "path": "/",
                })
            if cookie_list:
                try:
                    self._pw_context.add_cookies(cookie_list)
                except Exception:
                    pass

        self._pw_page = self._pw_context.new_page()

        # 全量 stealth 配置
        stealth = Stealth(
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
        )
        stealth.apply_stealth_sync(self._pw_page)

    def _fetch_playwright(self, url: str) -> Optional[str]:
        """使用 Playwright Stealth 获取页面"""
        try:
            self._init_playwright()
            page = self._pw_page

            resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            title = page.title()
            if self._is_cloudflare_block(page.content(), title):
                logger.info(f"  Cloudflare challenge, waiting 30s...")
                time.sleep(30)
                page.reload(wait_until="domcontentloaded", timeout=30000)
                time.sleep(5)
                title = page.title()
                if self._is_cloudflare_block(page.content(), title):
                    logger.warning(f"  Cloudflare still blocking after 30s wait")
                    return None

            # 保存 cookies
            cookies = self._pw_context.cookies()
            for c in cookies:
                self._session_cookies[c["name"]] = c["value"]
            self._save_cookies()

            return page.content()

        except Exception as e:
            logger.debug(f"  playwright error: {e}")
            return None

    # ── 主接口 ────────────────────────────────────────────────────────────────

    def fetch(self, url: str) -> Optional[str]:
        """
        安全获取 BR 页面 HTML。
        
        策略:
          1. 等待 rate limit (10-18s)
          2. 如果 use_playwright=True，直接用 Playwright
          3. 否则先试 curl_cffi，失败则 fallback 到 Playwright
          4. 如果被 Cloudflare 拦截，指数退避重试
          5. 最多重试 max_retries 次
        
        Returns:
            HTML 字符串，或 None（失败）
        """
        for attempt in range(1, self.max_retries + 1):
            self._wait_rate_limit()
            self._request_count += 1
            t0 = time.time()
            blocked = False

            html = None
            if self.use_playwright:
                html = self._fetch_playwright(url)
            else:
                html = self._fetch_cffi(url)
                if not html or len(html) < 5000:
                    logger.debug(f"  cffi failed (attempt {attempt}), trying Playwright...")
                    html = self._fetch_playwright(url)

            duration = time.time() - t0

            if html and len(html) > 5000:
                # 检查是否是 Cloudflare 页面
                if self._is_cloudflare_block(html):
                    blocked = True
                    self._blocked_count += 1
                    self._log_request(url, "GET", 403, duration, True)
                    logger.warning(f"  Blocked by Cloudflare (attempt {attempt}/{self.max_retries})")
                else:
                    self._log_request(url, "GET", 200, duration, False)
                    return html
            else:
                blocked = True
                self._blocked_count += 1
                self._log_request(url, "GET", 0, duration, True)
                logger.warning(f"  No valid HTML (attempt {attempt}/{self.max_retries})")

            # 指数退避: 30s, 60s, 120s
            if attempt < self.max_retries:
                backoff = 30 * (2 ** (attempt - 1))
                logger.info(f"  Retrying in {backoff}s...")
                time.sleep(backoff)

        logger.error(f"  All {self.max_retries} attempts failed for {url}")
        return None

    def warmup(self) -> bool:
        """
        预热 session — 先访问 BR 首页获取 Cloudflare cookies。
        建议在批量爬取前调用一次。
        
        Returns:
            True 如果预热成功
        """
        logger.info("Warming up BR session (visiting homepage)...")
        html = self.fetch(BR_BASE + "/")
        if html and not self._is_cloudflare_block(html):
            logger.info("  Warmup successful")
            return True
        else:
            logger.warning("  Warmup failed (Cloudflare blocking)")
            return False

    def get_stats(self) -> Dict:
        """获取当前 session 的统计信息"""
        return {
            "total_requests": self._request_count,
            "blocked_count": self._blocked_count,
            "block_rate": f"{self._blocked_count}/{self._request_count}" if self._request_count else "0/0",
            "cookies_loaded": len(self._session_cookies),
        }

    def close(self):
        """清理资源"""
        if self._pw_page:
            try:
                self._pw_page.close()
            except Exception:
                pass
        if self._pw_context:
            try:
                self._pw_context.close()
            except Exception:
                pass
        if self._pw_browser:
            try:
                self._pw_browser.close()
            except Exception:
                pass
        if hasattr(self, "_pw") and self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


# ── 便捷函数 ──────────────────────────────────────────────────────────────────

def create_safe_scraper(min_delay: float = 12.0, max_delay: float = 18.0, warmup: bool = True) -> SafeBRScraper:
    """
    创建一个安全的 BR 爬取器，可选预热 session。
    
    Args:
        min_delay: 最小间隔秒数（默认 12）
        max_delay: 最大间隔秒数（默认 18）
        warmup: 是否自动预热（访问首页获取 cookies）
    
    Returns:
        SafeBRScraper 实例
    """
    scraper = SafeBRScraper(min_delay=min_delay, max_delay=max_delay)
    if warmup:
        scraper.warmup()
    return scraper


if __name__ == "__main__":
    # 自测
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    print("Testing SafeBRScraper...")
    print(f"  min_delay=12s, max_delay=18s")
    print(f"  curl_cffi available: {HAS_CFFI}")
    
    with SafeBRScraper(min_delay=12, max_delay=18) as scraper:
        # 先预热
        ok = scraper.warmup()
        if not ok:
            print("Warmup failed, BR may be blocking us. Try again later.")
            exit(1)
        
        # 测试一个球员页面
        url = f"{BR_BASE}/players/l/jamesle01.html"
        print(f"\nFetching: {url}")
        html = scraper.fetch(url)
        
        if html:
            print(f"  Got {len(html)} chars")
            if HAS_BS4:
                soup = BeautifulSoup(html, "lxml")
                for li in soup.find_all("li"):
                    text = li.get_text(strip=True)
                    if "Weight:" in text:
                        print(f"  Found: {text}")
                        break
        else:
            print("  Failed to fetch")
        
        print(f"\nStats: {scraper.get_stats()}")
