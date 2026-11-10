#!/usr/bin/env python3
"""
nba_tracking_discover_pw.py — ONE page load with Playwright, capture JSON XHRs.

Goal: find the real data endpoint behind NBA.com tracking dashboards.
The legacy stats.nba.com JSON API now returns an HTML challenge shell, so the
endpoint must be observed from a real browser session.

RISK: exactly ONE page load (same as a human opening the page once).
      No retries, no looping, no bulk requests. Circuit-breaker on block signals.
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "probe_raw")
os.makedirs(RAW, exist_ok=True)

URL = "https://www.nba.com/stats/players/catch-shoot"
WAIT_MS = 15000
BLOCK_MARKERS = ("access denied", "forbidden", "request blocked", "are you a human",
                 "captcha", "error 403", "error 429")


def main() -> None:
    from playwright.sync_api import sync_playwright

    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--lang=en-US", "--window-size=1440,1000"],
        )
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"),
            viewport={"width": 1440, "height": 1000},
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = ctx.new_page()

        def on_response(resp):
            try:
                ct = (resp.headers or {}).get("content-type", "").lower()
                u = resp.url
                if "json" in ct or u.lower().endswith(".json") or "stats" in u.lower():
                    captured.append((resp.status, u, ct))
            except Exception:
                pass

        page.on("response", on_response)

        print(f"[disc-pw] ONE page load: {URL}")
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print("goto warning:", type(e).__name__, str(e)[:150])
        try:
            page.wait_for_load_state("networkidle", timeout=WAIT_MS)
        except Exception:
            pass
        time.sleep(4)

        # did the table actually render?
        try:
            rows = page.locator("table tbody tr").count()
            print(f"[disc-pw] rendered table rows = {rows}")
        except Exception as e:
            print("[disc-pw] row count unavailable:", type(e).__name__)

        title = page.title()
        print(f"[disc-pw] page title = {title!r}")
        low = (page.content() or "").lower()
        if any(m in low for m in BLOCK_MARKERS):
            print("!!! BLOCK MARKER in page content — stopping immediately, no retry !!!")
            browser.close()
            sys.exit(2)

        ctx.close()
        browser.close()

    print(f"\n[disc-pw] captured candidate JSON/stats responses: {len(captured)}")
    seen = set()
    for status, url, ct in captured:
        key = url.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        print(f"  [{status}] {ct}  {url[:170]}")

    if not captured:
        print("\n[disc-pw] no JSON captured — page may render client-side later, or blocked.")
        print("[disc-pw] NOT retrying (risk control). Report and decide next step.")


if __name__ == "__main__":
    main()
