import os, sys
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

conn = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password='postgres')
cur = conn.cursor()
apply = '--apply' in sys.argv

PLAYIN_DATES = {'2024-04-16', '2024-04-17', '2024-04-19'}

# [1] RS games >= Apr 15 2024 -> Playoffs / Play-In
cur.execute("""SELECT game_id, game_date, home_team_abbr, away_team_abbr, season_type
               FROM dim_games WHERE season=2024 AND season_type='Regular Season' AND game_date >= '2024-04-15' ORDER BY game_date""")
rs_late = cur.fetchall()
print(f"[1] RS games >= 2024-04-15 to reclassify: {len(rs_late)}")
for gid, d, h, a, st in rs_late:
    new = 'Play-In' if str(d) in PLAYIN_DATES else 'Playoffs'
    print(f"    {gid} {str(d)} {a}@{h}: {st} -> {new}")
    if apply:
        cur.execute("UPDATE dim_games SET season_type=%s WHERE game_id=%s", (new, gid))

# [2] existing Playoffs on play-in dates -> Play-In
cur.execute("""SELECT game_id, game_date, home_team_abbr, away_team_abbr
               FROM dim_games WHERE season=2024 AND season_type='Playoffs' AND game_date::text IN ('2024-04-16','2024-04-17','2024-04-19') ORDER BY game_date""")
pi = cur.fetchall()
print(f"\n[2] Playoffs on play-in dates -> Play-In: {len(pi)}")
for gid, d, h, a in pi:
    print(f"    {gid} {str(d)} {a}@{h}")
    if apply:
        cur.execute("UPDATE dim_games SET season_type='Play-In' WHERE game_id=%s", (gid,))

# [3] Oct/Nov 2023 'Playoffs' -> Regular Season
cur.execute("""SELECT game_id, game_date, home_team_abbr, away_team_abbr
               FROM dim_games WHERE season=2024 AND season_type='Playoffs' AND EXTRACT(MONTH FROM game_date) IN (10,11) ORDER BY game_date""")
wrong = cur.fetchall()
print(f"\n[3] Oct/Nov 2023 'Playoffs' -> Regular Season: {len(wrong)}")
for gid, d, h, a in wrong:
    print(f"    {gid} {str(d)} {a}@{h}")
    if apply:
        cur.execute("UPDATE dim_games SET season_type='Regular Season' WHERE game_id=%s", (gid,))

# duplicate detection across whole 2024
cur.execute("""SELECT game_date, home_team_abbr, away_team_abbr, COUNT(*),
                       ARRAY_AGG(game_id ORDER BY game_id), ARRAY_AGG(season_type ORDER BY game_id)
               FROM dim_games WHERE season=2024 AND home_team_abbr IS NOT NULL AND away_team_abbr IS NOT NULL
               GROUP BY game_date, home_team_abbr, away_team_abbr HAVING COUNT(*)>1 ORDER BY game_date""")
dups = cur.fetchall()
print(f"\n[DUPLICATE CHECK] exact (date,home,away) duplicate groups in 2024: {len(dups)}")
for d, h, a, n, gids, sts in dups:
    print(f"    {d} {a}@{h} x{n}: {list(zip(gids, sts))}")

if apply:
    conn.commit()
    print("\nCOMMITTED.")
else:
    print("\nDRY-RUN only (pass --apply to execute).")
conn.close()
