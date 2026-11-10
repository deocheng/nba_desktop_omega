#!/usr/bin/env python3
"""
nba_tracking_headers.py — minimal header diagnostic for stats.nba.com.

WHY
    The first probe returned HTTP 200 but HTML (an NBA.com shell) instead of JSON.
    That is the classic symptom of missing stats.nba.com-specific headers, NOT a
    block (no 403/401/429). This script tests a few header combos on ONE endpoint
    to find which combination yields JSON, without hammering.

ANTI-BAN
    * <=6 requests total, fixed delay, single-threaded
    * stops at the first combo that yields JSON
    * circuit-breaker on 401/403/429 / block markers (stop, never retry)

Usage:
    .venv/bin/python nba_tracking_headers.py
"""
from __future__ import annotations

import os, sys, json, time
import urllib.request, urllib.error, urllib.parse

API = "https://stats.nba.com/stats/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
DELAY = 3.0
TIMEOUT = 25
BLOCK_MARKERS = ("access denied", "forbidden", "request blocked", "are you a human",
                 "captcha", "blocked")

SEASON = "2025-26"
BASE_PARAMS = {
    "College": "", "Conference": "", "Country": "", "DateFrom": "", "DateTo": "",
    "Division": "", "DraftPick": "", "DraftYear": "", "GameScope": "",
    "GameSegment": "", "Height": "", "LastNGames": "0", "LeagueID": "00",
    "Location": "", "Month": "0", "OpponentTeamID": "0", "Outcome": "",
    "PORound": "0", "PerMode": "Totals", "PlayerExperience": "",
    "PlayerPosition": "", "Season": SEASON, "SeasonSegment": "",
    "SeasonType": "Regular Season", "StarterBench": "", "TeamID": "0",
    "VsConference": "", "VsDivision": "", "Weight": "",
    "PtMeasureType": "CatchShoot",
}

BASE = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# (label, extra headers)
COMBOS = [
    ("A_referer_stats", {"Referer": "https://stats.nba.com/"}),
    ("B_plus_origin",   {"Referer": "https://stats.nba.com/",
                         "x-nba-stats-origin": "stats"}),
    ("C_plus_token",    {"Referer": "https://stats.nba.com/",
                         "x-nba-stats-origin": "stats",
                         "x-nba-stats-token": "true"}),
    ("D_token_only",    {"Referer": "https://stats.nba.com/",
                         "x-nba-stats-token": "true"}),
]


def get(endpoint, params, headers):
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode("utf-8", "replace") if e.fp else "")
    except Exception as e:
        return 0, f"__TRANSPORT_ERROR__ {type(e).__name__}: {e}"


def classify(status, body):
    low = body.lower()
    if status in (401, 403, 429) or any(m in low for m in BLOCK_MARKERS):
        return "BLOCK"
    if body.lstrip().startswith(("{", "[")):
        try:
            json.loads(body)
            return "JSON"
        except Exception:
            pass
    if "<!DOCTYPE html>" in body or "<html" in low[:200]:
        return "HTML"
    return f"OTHER({status})"


def main():
    endpoint = "leaguedashplayerptshot"
    print(f"[diag] endpoint={endpoint} PtMeasureType=CatchShoot season={SEASON}")
    print(f"[diag] testing {len(COMBOS)} header combos, delay={DELAY}s")
    for label, extra in COMBOS:
        hdrs = dict(BASE); hdrs.update(extra)
        status, body = get(endpoint, BASE_PARAMS, hdrs)
        kind = classify(status, body)
        print(f"\n  [{label}] HTTP {status} -> {kind}  (len={len(body)})")
        if kind == "BLOCK":
            print("   !!! BLOCK SIGNAL — stopping, no retry. Access preserved over completeness.")
            sys.exit(2)
        if kind == "JSON":
            data = json.loads(body)
            rsets = data.get("resultSets") or []
            print(f"   SUCCESS: resultSets={len(rsets)}")
            for rs in rsets:
                print(f"     name={rs.get('name')} cols={len(rs.get('headers') or [])} "
                      f"rows={len(rs.get('rowSet') or [])}")
                print(f"       headers: {rs.get('headers')}")
                if rs.get("rowSet"):
                    print(f"       sample : {rs['rowSet'][0]}")
            out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "probe_raw", f"diag_{label}.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            print(f"   saved -> {out}")
            print(f"\n[diag] WINNING COMBO = {label}: {extra}")
            return
        print(f"   head: {body[:120]!r}")
        time.sleep(DELAY)
    print("\n[diag] no combo yielded JSON — endpoint/API shape changed (not a block).")
    print("[diag] next: verify current stats API host (data.nba.net / cdn.nba.com) "
          "before any further requests.")


if __name__ == "__main__":
    main()
