"""Retry cdn.nba.com with browser-like headers; also probe play_by_play schema."""
from __future__ import annotations
import os, json, sys
import urllib.request
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.core import config

DATE = sys.argv[1] if len(sys.argv) > 1 else "20251022"


def fetch(url, headers):
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=25)


HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "sec-fetch-site": "cross-site",
    "sec-fetch-mode": "cors",
}
url = f"https://cdn.nba.com/static/json/liveData/scoreboard/{DATE}.json"
print("TRY cdn with browser headers:", url)
try:
    resp = fetch(url, HDRS)
    data = json.load(resp)
    games = data.get("games", [])
    print(f"  OK http={resp.status} games={len(games)}")
    for g in games[:4]:
        print(f"    {g['visitorTeam']['teamTricode']}@{g['homeTeam']['teamTricode']} gameId={g['gameId']}")
    if games:
        gid = games[0]["gameId"]
        pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{gid}.json"
        try:
            p = fetch(pbp_url, HDRS)
            pd = json.load(p)
            print(f"  PBP OK gameId={gid} actions={len(pd.get('game',{}).get('actions',[]))}")
        except Exception as e:
            print(f"  PBP FAIL: {e}")
except Exception as e:
    print(f"  FAIL: {type(e).__name__}: {str(e)[:160]}")

# also try stats.nba.com playbyplayv3
print("\nTRY stats.nba.com playbyplayv3:")
surl = f"https://stats.nba.com/stats/playbyplayv3?GameID=0022500001&StartPeriod=0&EndPeriod=0"
sh = dict(HDRS)
sh["Referer"] = "https://www.nba.com/"
try:
    resp = fetch(surl, sh)
    print("  OK http=", resp.status)
except Exception as e:
    print(f"  FAIL: {type(e).__name__}: {str(e)[:160]}")

# schema
conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)
cur = conn.cursor()
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='play_by_play' ORDER BY ordinal_position")
print("\nplay_by_play columns:")
for r in cur.fetchall():
    print(f"  {r['column_name']}: {r['data_type']}")
cur.execute("SELECT gameid FROM play_by_play WHERE gameid ~ '^[0-9]+$' LIMIT 1")
print("\nsample gameid:", cur.fetchone())
conn.close()
