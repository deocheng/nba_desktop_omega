import os

import psycopg2
from dotenv import load_dotenv

ENV_PATH = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env"
load_dotenv(ENV_PATH)
pw = os.getenv("DB_PASSWORD")

conn = psycopg2.connect(host="localhost", port=5433, dbname="nba",
                        user="postgres", password=pw)
cur = conn.cursor()

def cols(tbl):
    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = %s ORDER BY ordinal_position
    """, (tbl,))
    return cur.fetchall()

for t in ["player_per_game", "player_gamelog", "dim_players"]:
    print("="*70)
    print("TABLE:", t)
    for c in cols(t):
        print("  ", c[0], c[1])

print("="*70)
print("PROBE player_per_game: sample rows for a known player (magic johnson)")
cur.execute("""
    SELECT player_id, season, team, g, pts, position
    FROM player_per_game
    WHERE player_id = 'johnsma01' OR player_id = 'johnsma01'
    LIMIT 10
""")
for r in cur.fetchall():
    print("  ppg:", r)

print("-"*70)
print("PROBE: count null/empty player_id in player_per_game")
cur.execute("""SELECT COUNT(*) total,
    SUM(CASE WHEN player_id IS NULL OR player_id='' THEN 1 ELSE 0 END) null_empty
    FROM player_per_game""")
print("  ", cur.fetchone())

print("-"*70)
print("PROBE: player_per_game pts stats (is it per_game? mean vs max)")
cur.execute("""SELECT MIN(pts), MAX(pts), AVG(pts), COUNT(*),
    SUM(CASE WHEN pts>50 THEN 1 ELSE 0 END) over50
    FROM player_per_game""")
print("  pts min/max/avg/cnt/over50:", cur.fetchone())

print("-"*70)
print("PROBE: player_per_game g column range")
cur.execute("""SELECT MIN(g), MAX(g), AVG(g) FROM player_per_game WHERE g IS NOT NULL""")
print("  g min/max/avg:", cur.fetchone())

conn.close()
