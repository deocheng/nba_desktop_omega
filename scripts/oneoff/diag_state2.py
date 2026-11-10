"""Diagnostic v2: PBP/gamelog coverage + duplicate investigation for 2026 RS.
games.nba_api_id is bigint (22500001); play_by_play/player_gamelog.gameid is
varchar ('0022500001'). Match via p.gameid::bigint = g.nba_api_id.
"""
from __future__ import annotations

import psycopg2
from psycopg2.extras import RealDictCursor
from backend.core import config

conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)
cur = conn.cursor()


def q(sql):
    cur.execute(sql)
    return cur.fetchall()


print("=== 2026 RS PBP coverage (games WITH nba_api_id) ===")
cur.execute("""
SELECT COUNT(*) AS total,
  COUNT(CASE WHEN EXISTS (SELECT 1 FROM play_by_play p
        WHERE p.gameid ~ '^[0-9]+$' AND p.gameid::bigint = g.nba_api_id) THEN 1 END) AS has_pbp
FROM games g WHERE g.season=2026 AND g.season_type='Regular Season' AND g.nba_api_id IS NOT NULL
""")
r = cur.fetchone()
print(f"  games w/ nba_api_id: {r['total']}, with PBP: {r['has_pbp']}, missing PBP: {r['total']-r['has_pbp']}")

print("\n=== 2026 RS gamelog coverage (games WITH nba_api_id) ===")
cur.execute("""
SELECT COUNT(*) AS total,
  COUNT(CASE WHEN EXISTS (SELECT 1 FROM player_gamelog gl
        WHERE gl.gameid ~ '^[0-9]+$' AND gl.gameid::bigint = g.nba_api_id) THEN 1 END) AS has_log
FROM games g WHERE g.season=2026 AND g.season_type='Regular Season' AND g.nba_api_id IS NOT NULL
""")
r = cur.fetchone()
print(f"  games w/ nba_api_id: {r['total']}, with gamelog: {r['has_log']}, missing: {r['total']-r['has_log']}")

print("\n=== Duplicate (date,home,away) in 2026 RS ===")
for r in q("""
SELECT game_date, home_team_abbr, away_team_abbr, COUNT(*) c,
       COUNT(DISTINCT game_id) dg, COUNT(DISTINCT nba_api_id) dn
FROM games WHERE season=2026 AND season_type='Regular Season'
GROUP BY game_date, home_team_abbr, away_team_abbr HAVING COUNT(*) > 1
ORDER BY c DESC LIMIT 20
"""):
    print(f"  {r['game_date']} {r['away_team_abbr']}@{r['home_team_abbr']}: rows={r['c']} game_id={r['dg']} nba_api={r['dn']}")

cur.execute("SELECT COUNT(*) c FROM games WHERE season=2026 AND season_type='Regular Season' AND nba_api_id IS NULL")
print(f"\n  2026 RS games missing nba_api_id: {cur.fetchone()['c']}")

cur.execute("""
SELECT COUNT(*) c FROM play_by_play p
WHERE p.gameid ~ '^[0-9]+$' AND p.gameid::bigint IN (
  SELECT g.nba_api_id FROM games g
  WHERE g.season=2026 AND g.season_type='Regular Season' AND g.nba_api_id IS NOT NULL)
""")
print(f"  PBP rows linked to 2026 RS: {cur.fetchone()['c']}")

print("\n=== season_type values for season=2026 ===")
for r in q("SELECT season_type, COUNT(*) c FROM games WHERE season=2026 GROUP BY season_type ORDER BY c DESC"):
    print(f"  {r['season_type']}: {r['c']}")

conn.close()
