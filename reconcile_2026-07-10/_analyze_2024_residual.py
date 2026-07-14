import os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2
from collections import defaultdict

c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                     user='postgres', password=os.environ.get('DB_PASSWORD'))
cur = c.cursor()
cur.execute("""
    SELECT game_id, game_date, home_team_abbr, away_team_abbr,
           season_type, source, nba_api_id
    FROM dim_games
    WHERE season = 2024
      AND home_team_abbr IS NOT NULL
      AND away_team_abbr IS NOT NULL
    ORDER BY game_date
""")
rows = cur.fetchall()
c.close()

pairs = defaultdict(list)
for gid, date, h, a, st, src, nid in rows:
    key = tuple(sorted([h, a]))
    pairs[key].append((date, h, a, st, src, gid, nid))

print("total season=2024 games (non-null abbr):", len(rows))
print("distinct pairs:", len(pairs))

RS_START = '2023-10-24'
RS_END = '2024-04-14'
susp = [(k, v) for k, v in pairs.items() if len(v) >= 5]
susp.sort(key=lambda x: -len(x[1]))
print("pairs with >=5 games:", len(susp))

for k, v in susp:
    # games whose date falls outside the RS window are cross-season suspects
    out = [g for g in v if not (RS_START <= str(g[0]) <= RS_END)]
    flag = "  <-- has out-of-window dates" if out else ""
    print(f"\n=== {k[0]} vs {k[1]}  meetings={len(v)}{flag} ===")
    for date, h, a, st, src, gid, nid in sorted(v):
        tag = 'API' if nid else (src or '?')
        oow = '' if (RS_START <= str(date) <= RS_END) else '  [OUT-OF-WINDOW]'
        print(f"  {date} {a}@{h} [{st}] src={tag} {gid}{oow}")
