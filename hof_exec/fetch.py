"""hof_exec/fetch.py — fetch a team HOF/executives page (offline file or live).

``fetch_team_page(abbr, kind, offline_dir=None) -> str``

  * ``offline_dir`` given  -> read ``<ABBR>_<kind>.html`` from that directory
    (used for offline parse validation + DET gold load in this sandbox).
  * otherwise              -> fetch live via UC-Chrome (warm-up + retry + CF
    detection), caching the raw HTML under ``det2026_br/``.

The fetch layer is the *only* place that knows where bytes come from; the
parsers downstream are source-agnostic.
"""

from __future__ import annotations

import logging
import os
import time

from .config import BR_TEAM_SLUGS, PROJECT_ROOT

logger = logging.getLogger(__name__)

BR_BASE = "https://www.basketball-reference.com/teams/{slug}"
_RAW_CACHE = os.path.join(PROJECT_ROOT, "det2026_br")  # default live-cache dir

_KIND_FILE = {"hof": "hof", "executives": "executives"}


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


def fetch_team_page(abbr: str, kind: str, offline_dir: str | None = None) -> str:
    """Return the HTML for one team's HOF or executives page.

    Raises ``FileNotFoundError`` when an ``offline_dir`` is given but the file
    is absent (the caller treats this as a graceful skip for non-DET teams).
    """
    abbr = abbr.upper()
    kind = kind.lower()
    if kind not in _KIND_FILE:
        raise ValueError(f"unknown kind {kind!r}; expected 'hof' or 'executives'")

    if offline_dir:
        path = os.path.join(offline_dir, f"{abbr}_{kind}.html")
        if not os.path.exists(path):
            raise FileNotFoundError(f"offline file not found: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    return _fetch_online(abbr, kind)


def _fetch_online(abbr: str, kind: str, retries: int = 4) -> str:
    """Live fetch via undetected_chromedriver (UC Chrome) with warm-up + retry."""
    import undetected_chromedriver as uc  # lazy import: not needed for offline/parse

    slug = BR_TEAM_SLUGS.get(abbr, abbr)
    base = BR_BASE.format(slug=slug)
    url = f"{base}/{kind}.html"
    warm = base

    opts = uc.ChromeOptions()
    opts.headless = True
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    )

    html = ""
    for attempt in range(1, retries + 1):
        driver = uc.Chrome(options=opts)
        try:
            # warm-up: hit the root domain first to obtain a session cookie
            if warm:
                try:
                    driver.get(warm)
                    time.sleep(3)
                except Exception:
                    pass
            driver.get(url)
            time.sleep(8)
            html = driver.page_source
            if not _is_cf_challenge(html):
                logger.info("[%s/%s attempt %d] OK (%d bytes)", abbr, kind, attempt, len(html))
                break
            logger.warning("[%s/%s attempt %d] CF challenge, retrying", abbr, kind, attempt)
        finally:
            driver.quit()
        time.sleep(3)
    else:
        logger.error(
            "[%s/%s] all %d attempts hit CF/empty; returning last payload", abbr, kind, retries
        )

    # cache the raw payload so a later offline run can reuse it
    os.makedirs(_RAW_CACHE, exist_ok=True)
    out = os.path.join(_RAW_CACHE, f"{abbr}_{kind}.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    if looks_like_404(html):
        logger.warning("[%s/%s] page looks like 404; cached at %s", abbr, kind, out)
    return html
