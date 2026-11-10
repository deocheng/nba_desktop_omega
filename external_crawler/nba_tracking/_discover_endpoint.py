#!/usr/bin/env python3
"""
nba_tracking_discover.py — ONE page load, capture the JSON endpoints the page calls.

WHY
    The legacy stats.nba.com JSON API now returns an HTML challenge shell regardless
    of headers. The real data endpoint lives inside the page's JS bundle, so we load
    the dashboard ONCE in a real Chrome and record which XHRs return JSON.

RISK POSTURE
    * exactly ONE page load — equivalent to a human opening the page once
    * no retries, no looping, no bulk requests
    * everything else is local analysis of captured responses

Usage:
    .venv/bin/python nba_tracking_discover.py
"""
from __future__ import annotations

import os, sys, json, time

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "probe_raw")
os.makedirs(RAW, exist_ok=True)

URL = "https://www.nba.com/stats/players/catch-shoot"
WAIT = 12  # seconds for the SPA to fetch + render


def main() -> None:
    try:
        import undetected_chromedriver as uc
    except Exception as e:
        print("FATAL: undetected_chromedriver unavailable:", e)
        sys.exit(1)

    opts = uc.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1440,1000")
    opts.add_argument("--lang=en-US")
    try:
        opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    except Exception:
        pass

    print(f"[discover] launching Chrome (headless), ONE page load: {URL}")
    driver = None
    try:
        driver = uc.Chrome(options=opts, version_main=152)
        driver.execute_cdp_cmd("Network.enable", {})
        driver.get(URL)
        print(f"[discover] loaded, waiting {WAIT}s for XHR...")
        time.sleep(WAIT)
    except Exception as e:
        print("FATAL during launch/load:", type(e).__name__, e)
        if driver:
            try: driver.quit()
            except Exception: pass
        sys.exit(1)

    # collect JSON responses from performance log
    found = []
    try:
        logs = driver.get_log("performance")
    except Exception as e:
        print("perf log unavailable:", e)
        logs = []

    req_ids = []
    for entry in logs or []:
        try:
            msg = json.loads(entry.get("message", "{}")).get("message", {})
        except Exception:
            continue
        if msg.get("method") != "Network.responseReceived":
            continue
        resp = msg.get("params", {}).get("response", {}) or {}
        url = resp.get("url", "")
        mime = (resp.get("mimeType") or "").lower()
        if "json" in mime or url.lower().endswith(".json"):
            rid = msg.get("params", {}).get("requestId")
            req_ids.append((rid, url, resp.get("status"), mime))

    print(f"\n[discover] JSON responses seen: {len(req_ids)}")
    for rid, url, status, mime in req_ids:
        print(f"  [{status}] {mime}  {url[:160]}")
        body = None
        try:
            r = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": rid})
            body = r.get("body")
        except Exception as e:
            print(f"      (body unavailable: {type(e).__name__})")
        if body:
            try:
                data = json.loads(body)
            except Exception:
                print(f"      non-JSON body, {len(body)} chars")
                continue
            keys = list(data.keys())[:10] if isinstance(data, dict) else f"list[{len(data)}]"
            print(f"      top-level keys: {keys}")
            fp = os.path.join(RAW, f"discover_{abs(hash(url)) % 100000}.json")
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            print(f"      saved -> {fp}")

    try:
        driver.quit()
    except Exception:
        pass
    print("\n[discover] done (single page load, no retries).")


if __name__ == "__main__":
    main()
