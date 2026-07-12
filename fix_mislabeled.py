"""Relabel 7 playoff-window games from 'Regular Season' to 'Playoffs'.

These 7 games (2026-04-19 .. 2026-05-13) carry season_type='Regular Season'
but fall inside the 2026 playoff window (2026-04-18 .. 2026-06-13). They have
valid nba_api_ids, so they were ingested as if real but tagged wrong.

Also reports PBP/gamelog coverage for these 7 and for the whole 2026 Playoffs,
so we know if playoff PBP also needs backfilling.
"""
from __future__ import annotations
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.core import config

conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)
cur = conn.cursor()

# Candidate game_ids (from find_mislabeled.py)
CANDIDATES = [
    '202604190DET', '202604270PHO', '202605010TOR', '202605020BOS',
    '202605040SAS', '202605050DET', '202605130DET',
]

# 1) confirm current state
cur.execute("""
    SELECT game_id, game_date, away_team_abbr, home_team_abbr, season_type, nba_api_id
    FROM games WHERE game_id = ANY(%s) ORDER BY game_date
""", (CANDIDATES,))
before = cur.fetchall()
print("=== BEFORE ===")
for r in before:
    print(f"  {r['game_id']} {r['game_date']} {r['away_team_abbr']}@{r['home_team_abbr']} "
          f"type={r['season_type']} nba_api_id={r['nba_api_id']}")

# 2) apply fix
cur.execute("""
    UPDATE games SET season_type='Playoffs'
    WHERE game_id = ANY(%s) AND season_type='Regular Season'
""", (CANDIDATES,))
n = cur.rowcount
conn.commit()
print(f"\nUpdated {n} rows -> 'Playoffs'")

# 3) verify
cur.execute("SELECT game_id, season_type FROM games WHERE game_id = ANY(%s) ORDER BY game_id", (CANDIDATES,))
print("=== AFTER ===")
for r in cur.fetchall():
    print(f"  {r['game_id']} -> {r['season_type']}")

# 4) PBP/gamelog coverage for these 7 (via nba_api_id numeric gameid)
print("\n=== PBP/gamelog coverage for the 7 (by nba_api_id) ===")
for r in before:
    nid = int(r['nba_api_id'])
    cur.execute("SELECT COUNT(*) c FROM play_by_play WHERE gameid=%s", (str(nid),))
    pbp = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) c FROM player_gamelog WHERE gameid=%s", (str(nid),))
    log = cur.fetchone()['c']
    print(f"  {r['game_id']} (nba {nid}): PBP={pbp} gamelog={log}")

# 5) overall 2026 Playoffs PBP coverage
cur.execute("""
    SELECT COUNT(*) total FROM games WHERE season=2026 AND season_type='Playoffs'
""")
total_po = cur.fetchone()['total']
cur.execute("""
    SELECT COUNT(DISTINCT g.nba_api_id) c
    FROM games g
    JOIN play_by_play p ON p.gameid = g.nba_api_id::text
    WHERE g.season=2026 AND g.season_type='Playoffs' AND g.nba_api_id IS NOT NULL
""")
po_with_pbp = cur.fetchone()['c']
print(f"\n=== 2026 Playoffs PBP coverage ===")
print(f"  total PO games: {total_po}")
print(f"  PO games with PBP (nba_api key): {po_with_pbp}  (missing {total_po - po_with_pbp})")

conn.close()
