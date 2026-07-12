"""Diagnostic: current state of games / PBP / gamelog for 25-26 season."""
from __future__ import annotations

import psycopg2
from psycopg2.extras import RealDictCursor
from backend.core import config

conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)
cur = conn.cursor()


def q1(sql):
    cur.execute(sql)
    return cur.fetchall()


print("=== games counts by season/type ===")
for r in q1("SELECT season, season_type, COUNT(*) c FROM games GROUP BY season, season_type ORDER BY season DESC, season_type"):
    print(f"  {r['season']} | {r['season_type']}: {r['c']}")

print("\n=== 2026 Regular Season detail ===")
for col, label in [("COUNT(*)", "total"),
                   ("COUNT(CASE WHEN nba_api_id IS NULL THEN 1 END)", "missing nba_api_id"),
                   ("COUNT(CASE WHEN game_date IS NULL THEN 1 END)", "missing game_date"),
                   ("COUNT(CASE WHEN br_crawled_id IS NULL THEN 1 END)", "missing br_crawled_id")]:
    cur.execute(f"SELECT {col} c FROM games WHERE season=2026 AND season_type='Regular Season'")
    print(f"  {label}: {cur.fetchone()['c']}")

print("\n=== PBP coverage for 2026 RS (via nba_api_id) ===")
cur.execute("""
    SELECT COUNT(*) AS total,
           COUNT(CASE WHEN EXISTS (SELECT 1 FROM play_by_play p WHERE p.gameid = g.nba_api_id) THEN 1 END) AS has_pbp
    FROM games g WHERE g.season=2026 AND g.season_type='Regular Season'
""")
r = cur.fetchone()
print(f"  games: {r['total']}, with PBP: {r['has_pbp']}, missing PBP: {r['total']-r['has_pbp']}")

print("\n=== player_gamelog coverage for 2026 RS (via nba_api_id) ===")
cur.execute("""
    SELECT COUNT(*) AS total,
           COUNT(CASE WHEN EXISTS (SELECT 1 FROM player_gamelog gl WHERE gl.gameid = g.nba_api_id) THEN 1 END) AS has_log
    FROM games g WHERE g.season=2026 AND g.season_type='Regular Season'
""")
r = cur.fetchone()
print(f"  games: {r['total']}, with gamelog: {r['has_log']}, missing: {r['total']-r['has_log']}")

print("\n=== PBP gameid format distribution ===")
for r in q1("""
    SELECT CASE WHEN gameid ~ '^[0-9]+$' THEN 'pure_numeric'
                WHEN gameid ~ '^[0-9]{10}[A-Z]{3}$' THEN 'br_format' ELSE 'other' END AS fmt,
           COUNT(DISTINCT gameid) c
    FROM play_by_play GROUP BY fmt
"""):
    print(f"  {r['fmt']}: {r['c']} unique")

print("\n=== Total distinct gameids ===")
cur.execute("SELECT COUNT(DISTINCT gameid) c FROM play_by_play"); print(f"  PBP: {cur.fetchone()['c']}")
cur.execute("SELECT COUNT(DISTINCT gameid) c FROM player_gamelog"); print(f"  gamelog: {cur.fetchone()['c']}")

conn.close()
