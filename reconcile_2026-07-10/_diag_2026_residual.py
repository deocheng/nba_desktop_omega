import os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

conn = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password='postgres')
cur = conn.cursor()

print("=== Season 2026 : season_type counts ===")
cur.execute("SELECT season_type, COUNT(*) FROM dim_games WHERE season=2026 GROUP BY season_type ORDER BY season_type")
for st, c in cur.fetchall():
    print(f"  {st}: {c}")

print("\n=== 2026 exact (date,home,away) duplicate groups ===")
cur.execute("""SELECT game_date, home_team_abbr, away_team_abbr, COUNT(*),
                       ARRAY_AGG(game_id ORDER BY game_id), ARRAY_AGG(season_type ORDER BY game_id), ARRAY_AGG(source ORDER BY game_id)
               FROM dim_games WHERE season=2026 AND home_team_abbr IS NOT NULL AND away_team_abbr IS NOT NULL
               GROUP BY game_date, home_team_abbr, away_team_abbr HAVING COUNT(*)>1 ORDER BY game_date""")
dups = cur.fetchall()
print(f"  duplicate groups: {len(dups)}")
for d, h, a, n, gids, sts, srcs in dups:
    print(f"  {d} {a}@{h} x{n}: {list(zip(gids, sts, srcs))}")

print("\n=== 2024 residual: over-played RS-window pairs (possible cross-season) ===")
cur.execute("""SELECT game_date, home_team_abbr, away_team_abbr, season_type, source, nba_api_id
               FROM dim_games WHERE season=2024 AND season_type='Regular Season'
               AND game_date < '2024-04-15' ORDER BY game_date""")
rs = cur.fetchall()
from collections import Counter
pairs = Counter(tuple(sorted((h, a))) for (_, _, h, a, _, _) in rs)
over = {p: c for p, c in pairs.items() if c > 4}
print(f"  2024 RS-window games: {len(rs)}, pairs played >4 times (impossible in one season): {len(over)}")
for p, c in sorted(over.items(), key=lambda x: -x[1])[:15]:
    ds = sorted(d for (d, h, a, _, _, _) in rs if tuple(sorted((h, a))) == p)
    print(f"    {p}: {c} -> {ds}")
conn.close()
