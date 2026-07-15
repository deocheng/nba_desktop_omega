"""transactions_crawl/fetch.py — fetch a team transactions page (offline or live).

``fetch_transactions_page(abbr, year, offline_dir=None) -> str``

  * ``offline_dir`` given -> read ``<ABBR>_<year>_transactions_raw.html``
    (falling back to ``<ABBR>_<year>_transactions.html``) from that
    directory. Used for offline parse validation + DET gold load in sandbox.
  * otherwise            -> fetch live via UC-Chrome (warm-up + retry + CF
    detection), caching the raw HTML under ``det2026_br/``.

The fetch layer is the *only* place that knows where bytes come from; the
parsers downstream are source-agnostic.
"""

from __future__ import annotations

import logging
import os
import time
from selenium.common.exceptions import WebDriverException

from .config import BR_TEAM_SLUGS, PROJECT_ROOT
from common.browser import get_driver, reset_driver, warmup_once

logger = logging.getLogger(__name__)

BR_BASE = "https://www.basketball-reference.com/teams/{slug}"
_RAW_CACHE = os.path.join(PROJECT_ROOT, "det2026_br")  # default live-cache dir


def _is_cf_challenge(html: str) -> bool:
    """Heuristic Cloudflare interstitial / JS-challenge detector."""
    low = html.lower()
    return (
        ("请稍候" in html)
        or ("just a moment" in low)
        or ("attention required" in low)
        or ("verify you are human" in low)
        or ("ray id:" in low and "cloudflare" in low)
    )


def looks_like_404(html: str) -> bool:
    """Best-effort detector for a BR 404 / 'Page Not Found' payload."""
    if not html:
        return True
    low = html.lower()
    return "page not found" in low or "404 error" in low or "<title>404" in low


def fetch_transactions_page(abbr: str, year: int, offline_dir: str | None = None) -> str:
    """Return the HTML for one team's ``<year>_transactions`` page.

    Raises ``FileNotFoundError`` when an ``offline_dir`` is given but neither
    offline file variant is present (the caller treats this as a graceful skip).
    """
    abbr = abbr.upper()
    year = int(year)

    if offline_dir:
        # Accept either the captured "_raw" file or a plain "<ABBR>_<year>_transactions.html".
        candidates = [
            os.path.join(offline_dir, f"{abbr}_{year}_transactions_raw.html"),
            os.path.join(offline_dir, f"{abbr}_{year}_transactions.html"),
        ]
        for path in candidates:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    return fh.read()
        raise FileNotFoundError(
            "offline transactions file not found for %s/%s in %s" % (abbr, year, offline_dir)
        )

    return _fetch_online(abbr, year)


def _fetch_online(abbr: str, year: int, retries: int = 4) -> str:
    """Live fetch via the shared UC-Chrome driver (warm-up + retry + CF detect).

    The driver is a process-wide singleton (``common.browser.get_driver``) — it
    is built once and reused for every page instead of being rebuilt per page
    (~50s each). On a driver-level failure (WebDriverException / TimeoutError /
    OSError) we reset the driver so the next attempt rebuilds it, rather than
    skipping the page.
    """
    slug = BR_TEAM_SLUGS.get(abbr, abbr)
    base = BR_BASE.format(slug=slug)
    url = f"{base}/{year}_transactions.html"
    warm = base
    year_or_kind = year

    html = ""
    for attempt in range(1, retries + 1):
        try:
            driver = get_driver()          # reuse, do not rebuild per page
            warmup_once(warm)              # only warm the first time
            driver.get(url)
            time.sleep(8)
            html = driver.page_source
            if not _is_cf_challenge(html):
                logger.info("[%s/%s attempt %d] OK (%d bytes)", abbr, year_or_kind, attempt, len(html))
                break
            logger.warning("[%s/%s attempt %d] CF challenge, retrying", abbr, year_or_kind, attempt)
        except (WebDriverException, TimeoutError, OSError) as e:
            logger.warning(
                "[%s/%s attempt %d] fetch error: %s; rebuilding driver",
                abbr, year_or_kind, attempt, repr(e)[:160],
            )
            reset_driver()                  # rebuild next round; do not skip the page
            time.sleep(3)
    else:
        logger.error(
            "[%s/%s] all %d attempts hit CF/empty; returning last payload",
            abbr,
            year_or_kind,
            retries,
        )

    # cache the raw payload so a later offline run can reuse it
    os.makedirs(_RAW_CACHE, exist_ok=True)
    out = os.path.join(_RAW_CACHE, f"{abbr}_{year}_transactions_raw.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    if looks_like_404(html):
        logger.warning("[%s/%s] page looks like 404; cached at %s", abbr, year, out)
    return html
