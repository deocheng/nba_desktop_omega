import os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2
from collections import defaultdict

c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                     user='postgres', password=os.environ.get('DB_PASSWORD'))
cur = c.cursor()
cur.execute("""
    SELECT game_date, home_team_abbr, away_team_abbr, season_type, source, nba_api_id
    FROM dim_games
    WHERE season = 2026
      AND home_team_abbr IS NOT NULL
      AND away_team_abbr IS NOT NULL
""")
rows = cur.fetchall()
c.close()

home = defaultdict(set)   # team -> set of away opponents it hosted
away = defaultdict(set)   # team -> set of home opponents it visited
rs_total = 0
for date, h, a, st, src, nid in rows:
    if st == 'Regular Season':
        rs_total += 1
        home[h].add(a)
        away[a].add(h)

teams = sorted(set(list(home.keys()) + list(away.keys())))
allteams = set(teams)
print("2026 RS games (non-null abbr):", rs_total, " expected ~1230")
print("teams with any 2026 game:", len(teams))

print("\n-- teams short on distinct opponents (missing_opp = never played at all) --")
short = []
for t in teams:
    opp = home[t] | away[t]
    missing = sorted(allteams - opp)
    hc, ac = len(home[t]), len(away[t])
    if missing or hc < 41 or ac < 41:
        short.append(t)
        print(f"  {t}: home_vs={hc} away_vs={ac} distinct_opp={len(opp)}/"
              f"{len(allteams)-1} missing_opp={missing}")

print("\nshort teams count:", len(short))

# also count NULL-abbr broken rows
c2 = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                      user='postgres', password=os.environ.get('DB_PASSWORD'))
cur2 = c2.cursor()
cur2.execute("""SELECT COUNT(*) FROM dim_games
                WHERE season=2026 AND season_type='Regular Season'
                AND (home_team_abbr IS NULL OR away_team_abbr IS NULL)""")
nullcnt = cur2.fetchone()[0]
c2.close()
print("2026 RS rows with NULL abbr (broken, cannot recover away):", nullcnt)
