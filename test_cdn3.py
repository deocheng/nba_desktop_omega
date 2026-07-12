"""Test cdn.nba.com via curl_cffi (chrome impersonation) — the method ingest_2026_pbp.py uses."""
from __future__ import annotations
import sys
from curl_cffi import requests as cffi_requests

DATE = sys.argv[1] if len(sys.argv) > 1 else "20251022"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.nba.com/",
}

sb_url = f"https://cdn.nba.com/static/json/liveData/scoreboard/{DATE}.json"
print("GET", sb_url)
r = cffi_requests.get(sb_url, headers=HEADERS, impersonate="chrome124", timeout=25)
print("  status:", r.status_code)
if r.status_code == 200:
    data = r.json()
    games = data.get("games", [])
    print(f"  games: {len(games)}")
    for g in games[:6]:
        print(f"    {g['visitorTeam']['teamTricode']}@{g['homeTeam']['teamTricode']} gameId={g['gameId']}")
    if games:
        gid = games[0]["gameId"]
        pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{gid}.json"
        print("GET", pbp_url)
        p = cffi_requests.get(pbp_url, headers=HEADERS, impersonate="chrome124", timeout=25)
        print("  status:", p.status_code)
        if p.status_code == 200:
            pd = p.json()
            acts = pd.get("game", {}).get("actions", [])
            print(f"  PBP actions: {len(acts)}")
            if acts:
                print("  sample:", {k: acts[0].get(k) for k in ("actionNumber", "period", "clock", "teamTricode", "description")})
else:
    print("  body[:200]:", r.text[:200])
