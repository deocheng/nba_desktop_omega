import os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

conn = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password='postgres')
cur = conn.cursor()

print("=== 2024 RS daily counts (Apr 1 - Jun 17) ===")
cur.execute("""SELECT game_date, COUNT(*) AS n FROM dim_games
               WHERE season=2024 AND season_type='Regular Season' AND game_date >= '2024-04-01'
               GROUP BY game_date ORDER BY game_date""")
for d, n in cur.fetchall():
    print(f"  {d}: {n}")

print("\n=== 2024 already-tagged Playoffs ===")
cur.execute("""SELECT game_id, game_date, home_team_abbr, away_team_abbr
               FROM dim_games WHERE season=2024 AND season_type='Playoffs' ORDER BY game_date""")
for r in cur.fetchall():
    print("  ", r)

print("\n=== 2024 weird Oct/Nov 'Playoffs' (should not be playoffs) ===")
cur.execute("""SELECT game_id, game_date, home_team_abbr, away_team_abbr, season_type
               FROM dim_games WHERE season=2024 AND season_type='Playoffs'
               AND EXTRACT(MONTH FROM game_date) IN (10,11) ORDER BY game_date""")
for r in cur.fetchall():
    print("  ", r)

# How many 2024 RS games fall strictly after the likely RS end (Apr 14, 2024)?
for cutoff in ('2024-04-15', '2024-04-16', '2024-04-20'):
    cur.execute("""SELECT COUNT(*) FROM dim_games
                   WHERE season=2024 AND season_type='Regular Season' AND game_date >= %s""", (cutoff,))
    print(f"\nRS games >= {cutoff}: {cur.fetchone()[0]}")

conn.close()
