import os
from dotenv import load_dotenv
import psycopg2

ENV_PATH = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env"
load_dotenv(ENV_PATH)
pw = os.getenv("DB_PASSWORD")

conn = psycopg2.connect(host="localhost", port=5433, dbname="nba",
                        user="postgres", password=pw)
cur = conn.cursor()

print("PROBE player_per_game sample (magic johnson):")
cur.execute("""
    SELECT player_id, season, team, g, pts_per_game, pos
    FROM player_per_game
    WHERE player_id = 'johnsma01'
    LIMIT 6
""")
for r in cur.fetchall():
    print("  ", r)

print("-"*70)
print("dim_players.position distribution (top values + null count):")
cur.execute("""SELECT position, COUNT(*) FROM dim_players GROUP BY position ORDER BY COUNT(*) DESC LIMIT 40""")
for r in cur.fetchall():
    print("  ", r)
cur.execute("""SELECT COUNT(*) total,
    SUM(CASE WHEN position IS NULL OR position='' THEN 1 ELSE 0 END) null_empty
    FROM dim_players""")
print("  total/null_empty:", cur.fetchone())

print("-"*70)
print("Join coverage: player_per_game primary scorer candidates (g>=41, valid id) -> dim_players.position")
cur.execute("""
    WITH cands AS (
        SELECT player_id, season, team, g, pts_per_game
        FROM player_per_game
        WHERE player_id IS NOT NULL AND player_id <> ''
          AND g >= 41
    )
    SELECT
        COUNT(*) total_rows,
        SUM(CASE WHEN dp.position IS NOT NULL AND dp.position<>'' THEN 1 ELSE 0 END) with_pos
    FROM cands c
    LEFT JOIN dim_players dp ON dp.player_id = c.player_id
""")
print("  ", cur.fetchone())

print("-"*70)
print("player_per_game.pos own column distribution sample:")
cur.execute("""SELECT pos, COUNT(*) FROM player_per_game
    WHERE player_id IS NOT NULL AND player_id <> '' GROUP BY pos ORDER BY COUNT(*) DESC LIMIT 30""")
for r in cur.fetchall():
    print("  ", r)

print("-"*70)
print("Check br_player_id in player_gamelog vs dim_players.player_id coverage (sample season 2025):")
cur.execute("""
    SELECT COUNT(*) FROM player_gamelog pg
    WHERE pg.season=2025 AND pg.player_id IS NOT NULL AND pg.player_id<>''
""")
print("  gamelog rows 2025:", cur.fetchone())
cur.execute("""SELECT COUNT(*) FROM dim_players""")
print("  dim_players total:", cur.fetchone())

conn.close()
