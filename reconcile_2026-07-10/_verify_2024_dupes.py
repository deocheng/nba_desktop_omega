import os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

conn = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password=os.environ.get('DB_PASSWORD'))
cur = conn.cursor()

def season_of(col):
    return f"(EXTRACT(YEAR FROM {col}) + CASE WHEN EXTRACT(MONTH FROM {col})>=9 THEN 1 ELSE 0 END)"

cur.execute(f"""SELECT COUNT(*) FROM dim_games WHERE season_type='Regular Season' AND {season_of('game_date')}=2024""")
total = cur.fetchone()[0]
cur.execute(f"""SELECT COUNT(DISTINCT (game_date, home_team_abbr, away_team_abbr))
               FROM dim_games WHERE season_type='Regular Season' AND {season_of('game_date')}=2024
               AND home_team_abbr IS NOT NULL AND away_team_abbr IS NOT NULL""")
distinct = cur.fetchone()[0]
print(f"2024 RS total rows={total}, distinct (date,home,away) keys={distinct}, exact-duplicate rows={total-distinct}")

cur.execute(f"""SELECT game_date, home_team_abbr, away_team_abbr, COUNT(*) AS n,
                       ARRAY_AGG(game_id ORDER BY game_id) AS gids,
                       ARRAY_AGG(source ORDER BY game_id) AS srcs,
                       ARRAY_AGG(nba_api_id ORDER BY game_id) AS nids
                FROM dim_games WHERE season_type='Regular Season' AND {season_of('game_date')}=2024
                AND home_team_abbr IS NOT NULL AND away_team_abbr IS NOT NULL
                GROUP BY game_date, home_team_abbr, away_team_abbr HAVING COUNT(*)>1 ORDER BY game_date""")
dups = cur.fetchall()
print(f"\nDuplicate groups: {len(dups)}")
keep = 0
remove = 0
for d, h, a, n, gids, srcs, nids in dups:
    keep_id = gids[0]
    for g, nid in zip(gids, nids):
        if nid is not None:
            keep_id = g
            break
    rem = [g for g in gids if g != keep_id]
    keep += 1
    remove += len(rem)
    print(f"  {d} {a}@{h} x{n}: keep={keep_id} remove={rem}")
print(f"\nProposed: keep {keep} groups, delete {remove} duplicate rows (dry-run, not executed)")
conn.close()
