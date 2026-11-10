#!/usr/bin/env python3
"""
nba_tracking_probe.py — read-only endpoint/structure probe for NBA.com tracking dashboards.

PURPOSE
    Discover whether the NBA.com stats tracking endpoints answer, and capture their
    exact resultSet names + column headers, so the real scraper can be written
    against verified schemas instead of guesses.

ANTI-BAN (hard constraints — NBA.com bans are permanent)
    * single-threaded, one request at a time, fixed DELAY between requests
    * browser User-Agent + Referer + Accept, no proxy for outbound
    * CIRCUIT BREAKER: on 401/403/429 or any block marker -> STOP IMMEDIATELY,
      do NOT retry. A 403 is treated as a pre-ban signal; preserving access
      outranks completeness.
    * MAX_REQUESTS hard cap per run
    * read-only: writes go only to probe_raw/ (local JSON), never to the DB

Usage:
    .venv/bin/python nba_tracking_probe.py            # run probe
    .venv/bin/python nba_tracking_probe.py --limit 3  # fewer endpoints
"""
from __future__ import annotations

import os
import sys
import json
import time
import urllib.request
import urllib.error
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(HERE, "probe_raw")
os.makedirs(RAW_DIR, exist_ok=True)

API = "https://stats.nba.com/stats/"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Referer": "https://www.nba.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nba.com",
}

DELAY = 3.0            # seconds between requests (never decrease)
TIMEOUT = 25
MAX_REQUESTS = 8
BLOCK_MARKERS = ("access denied", "forbidden", "request blocked",
                 "are you a human", "captcha", "blocked")

SEASON = "2025-26"     # == our season 2026

# Canonical param set the NBA.com frontend sends (empties are required by the API).
BASE_PARAMS = {
    "College": "", "Conference": "", "Country": "", "DateFrom": "", "DateTo": "",
    "Division": "", "DraftPick": "", "DraftYear": "", "GameScope": "",
    "GameSegment": "", "Height": "", "LastNGames": "0", "LeagueID": "00",
    "Location": "", "Month": "0", "OpponentTeamID": "0", "Outcome": "",
    "PORound": "0", "PerMode": "Totals", "PlayerExperience": "",
    "PlayerPosition": "", "Season": SEASON, "SeasonSegment": "",
    "SeasonType": "Regular Season", "StarterBench": "", "TeamID": "0",
    "VsConference": "", "VsDivision": "", "Weight": "",
}

# (label, endpoint, extra params)  -- ordered by value to our offense-eval goal
ENDPOINTS = [
    ("shots_closest_defender", "leaguedashplayerptshot", {"PtMeasureType": "ClosestDefender"}),
    ("shots_catch_shoot",      "leaguedashplayerptshot", {"PtMeasureType": "CatchShoot"}),
    ("shots_pull_up",          "leaguedashplayerptshot", {"PtMeasureType": "PullUp"}),
    ("shots_shot_clock",       "leaguedashplayerptshot", {"PtMeasureType": "ShotClock"}),
    ("shots_dribbles",         "leaguedashplayerptshot", {"PtMeasureType": "Dribbles"}),
    ("shots_by_zone",          "leaguedashplayerptshot", {"DistanceRange": "ByZone"}),
    ("drives",                 "leaguedashplayerptdrive", {}),
    ("hustle",                 "leaguedashhustle", {}),
]


def http_get(endpoint: str, params: dict):
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        return e.code, body
    except Exception as e:  # network/DNS/timeout
        return 0, f"__TRANSPORT_ERROR__ {type(e).__name__}: {e}"


def is_block(status: int, body: str) -> bool:
    if status in (401, 403, 429):
        return True
    low = body.lower()
    return any(m in low for m in BLOCK_MARKERS)


def summarize(label: str, status: int, body: str) -> None:
    """Print a compact structural summary of one endpoint response."""
    print(f"\n--- {label}  [HTTP {status}] ---")
    if not body or body.startswith("__TRANSPORT_ERROR__"):
        print("   no body:", body[:200])
        return
    try:
        data = json.loads(body)
    except Exception as e:
        print(f"   non-JSON ({e}); first 200 chars: {body[:200]!r}")
        return
    if isinstance(data, dict) and "Message" in data and "resultSets" not in data:
        # API-level error (e.g. invalid PtMeasureType) -> discovery info
        print(f"   API error message: {data.get('Message')}")
        return
    rsets = data.get("resultSets") or []
    if not rsets:
        print("   resultSets empty/absent; top keys:", list(data.keys()))
        return
    for rs in rsets:
        name = rs.get("name")
        hdrs = rs.get("headers") or []
        rows = rs.get("rowSet") or []
        print(f"   resultSet={name}  cols={len(hdrs)}  rows={len(rows)}")
        print(f"     headers: {hdrs}")
        if rows:
            print(f"     sample : {rows[0]}")
    # persist raw for later schema work
    fp = os.path.join(RAW_DIR, f"{label}.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"   raw -> {fp}")


def main() -> None:
    limit = MAX_REQUESTS
    if "--limit" in sys.argv:
        try:
            limit = min(int(sys.argv[sys.argv.index("--limit") + 1]), MAX_REQUESTS)
        except Exception:
            pass

    targets = ENDPOINTS[:limit]
    print(f"[probe] {len(targets)} endpoints | delay={DELAY}s | season={SEASON} | "
          f"circuit-breaker on 401/403/429/block-markers")
    print("[probe] outbound proxy disabled by caller (unset http_proxy/https_proxy)")

    for i, (label, endpoint, extra) in enumerate(targets, 1):
        params = dict(BASE_PARAMS)
        params.update(extra)
        status, body = http_get(endpoint, params)

        if is_block(status, body):
            print(f"\n!!! CIRCUIT BREAKER TRIPPED on {label} [HTTP {status}] — STOPPING, NO RETRY !!!")
            print("!!! Potential block signal. Preserving access > completeness. Aborting run. !!!")
            print(f"body head: {body[:300]!r}")
            sys.exit(2)

        summarize(label, status, body)
        if i < len(targets):
            time.sleep(DELAY)

    print("\n[probe] done — no block signals encountered.")


if __name__ == "__main__":
    main()
