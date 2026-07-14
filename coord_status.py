#!/usr/bin/env python3
import os
"""坐标覆盖现状 + 实时爬虫冒烟测试"""
import sys, time
sys.path.insert(0, "external_crawler/crawler")
from curl_cffi import requests as cffi_requests

DB = dict(host="localhost", port=5433, dbname="nba", user="postgres", password=os.environ.get("DB_PASSWORD"))
import psycopg2
conn = psycopg2.connect(**DB)
cur = conn.cursor()

print("=== 当前真实坐标覆盖（play_by_play.x IS NOT NULL）===")
cur.execute("""
  SELECT COUNT(DISTINCT gameid) AS games_with_xy,
         COUNT(*) FILTER (WHERE x IS NOT NULL) AS events_with_xy,
         COUNT(*) AS events_total
  FROM play_by_play;
""")
g, ex, et = cur.fetchone()
print(f"  有真实坐标的比赛: {g:,} 场")
print(f"  有坐标的回合: {ex:,} / 总回合 {et:,}  ({100*ex/max(et,1):.1f}%)")

print("\n=== 球员特征可用度（有真实投篮坐标的球员）===")
cur.execute("""
  SELECT COUNT(DISTINCT playerid) FILTER (WHERE x IS NOT NULL AND event_type ILIKE '%shot%')
  FROM play_by_play WHERE playerid IS NOT NULL;
""")
print(f"  至少有 1 次带坐标投篮的球员: {cur.fetchone()[0]:,}")

print("\n=== 按来源看坐标分布 ===")
cur.execute("""
  SELECT source, COUNT(DISTINCT gameid) AS games,
         COUNT(*) FILTER (WHERE x IS NOT NULL) AS xy_events
  FROM play_by_play GROUP BY source ORDER BY games DESC;
""")
for src, games, xy in cur.fetchall():
    print(f"  {str(src):12s} 场={games:>7,}  xy回合={xy:>9,}")

# ── 冒烟：用爬虫同款请求真实抓一场 CDN PBP ──
print("\n=== 冒烟测试：真实抓取一场 CDN PBP（验证 curl_cffi 修复生效）===")
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.nba.com/",
}
# 取一个已知有坐标的数字 id 场（从库里找）
cur.execute("""
  SELECT gameid FROM play_by_play
  WHERE x IS NOT NULL AND gameid ~ '^[0-9]+$'
  LIMIT 1;
""")
row = cur.fetchone()
if not row:
    print("  (库里没有数字 id 的有坐标场，跳过真实抓取)")
else:
    gid = row[0].zfill(10)
    url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{gid}.json"
    t0 = time.time()
    resp = cffi_requests.get(url, headers=HEADERS, impersonate="chrome124", timeout=25)
    dt = time.time() - t0
    if resp.status_code == 200:
        acts = resp.json().get("game", {}).get("actions", [])
        xy = [a for a in acts if a.get("x") is not None]
        print(f"  HTTP 200 in {dt:.1f}s | gid={gid} | actions={len(acts)} 其中带x/y={len(xy)}")
        if xy:
            s = xy[0]
            print(f"  样例: {s.get('playerNameI')} {s.get('actionType')} -> x={s.get('x')} y={s.get('y')}  desc={s.get('description','')[:60]}")
    else:
        print(f"  HTTP {resp.status_code} in {dt:.1f}s (gid={gid})")

conn.close()
print("\nDONE")
