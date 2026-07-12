"""Probe cdn.nba.com reachability: scoreboard (gameId) + PBP JSON.
Tests both with default env (proxy if set) and with proxy explicitly unset.
"""
from __future__ import annotations
import os, json, sys
import urllib.request

DATE = sys.argv[1] if len(sys.argv) > 1 else "20251022"
print("proxy env:", {k: os.environ.get(k) for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")})


def fetch(url, use_proxy: bool):
    handlers = []
    if not use_proxy:
        # force no proxy
        proxy_handler = urllib.request.ProxyHandler({})
        handlers.append(proxy_handler)
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return opener.open(req, timeout=25)


def try_mode(label, use_proxy):
    print(f"\n=== mode: {label} (use_proxy={use_proxy}) ===")
    url = f"https://cdn.nba.com/static/json/liveData/scoreboard/{DATE}.json"
    try:
        resp = fetch(url, use_proxy)
        data = json.load(resp)
        games = data.get("games", [])
        print(f"  scoreboard OK, http={resp.status}, games={len(games)}")
        for g in games[:4]:
            print(f"    {g['visitorTeam']['teamTricode']}@{g['homeTeam']['teamTricode']} gameId={g['gameId']}")
        if games:
            gid = games[0]["gameId"]
            pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{gid}.json"
            try:
                p = fetch(pbp_url, use_proxy)
                pd = json.load(p)
                acts = pd.get("game", {}).get("actions", [])
                print(f"  PBP OK gameId={gid}, actions={len(acts)}")
            except Exception as e:
                print(f"  PBP FAIL: {e}")
        return True
    except Exception as e:
        print(f"  scoreboard FAIL: {type(e).__name__}: {str(e)[:120]}")
        return False


ok_proxy = try_mode("WITH proxy (default env)", True)
if not ok_proxy:
    try_mode("WITHOUT proxy", False)
