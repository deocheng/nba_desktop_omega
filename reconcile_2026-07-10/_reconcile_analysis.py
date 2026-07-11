import os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2
from collections import Counter, defaultdict

conn = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password='postgres')
cur = conn.cursor()

def season_label(d):
    return d.year + 1 if d.month >= 9 else d.year

cur.execute("""SELECT game_id, game_date, home_team_abbr, away_team_abbr, season_type, source, nba_api_id
               FROM dim_games WHERE season_type='Regular Season'""")
rows = cur.fetchall()
print("Total RS rows:", len(rows))

by_season = defaultdict(list)
none_abbr = 0
for gid, d, h, a, st, src, nid in rows:
    if h is None or a is None:
        none_abbr += 1
        continue
    by_season[season_label(d)].append((gid, d, h, a, src, nid))
print(f"RS rows skipped (NULL abbr): {none_abbr}")

TARGET = [2024, 2025, 2026]
for s in TARGET:
    games = by_season.get(s, [])
    pairs = Counter(tuple(sorted((h, a))) for (_, _, h, a, _, _) in games)
    n_api = sum(1 for g in games if g[5] is not None)
    bbr = sum(1 for g in games if g[4] == 'BBRef')
    print(f"\n=== Season {s} (ends {s}) ===")
    print(f"  RS games={len(games)}  nba_api_keyed={n_api}  BBRef={bbr}  distinct_pairs={len(pairs)}")
    print(f"  expected full season ~1230 games, ~435 distinct pairs")

template = Counter(tuple(sorted((h, a))) for (_, _, h, a, _, _) in by_season.get(2025, []))
print(f"\nTemplate season 2025 distinct pairs: {len(template)}")

for s in (2024, 2026):
    games = by_season.get(s, [])
    pairs = Counter(tuple(sorted((h, a))) for (_, _, h, a, _, _) in games)
    missing = {p: c for p, c in template.items() if p not in pairs}
    extra = {p: c for p, c in pairs.items() if p not in template}
    diff = {p: (template.get(p), c) for p, c in pairs.items() if template.get(p) != c}
    print(f"\n=== Season {s} vs 2025 template ===")
    print(f"  pairs MISSING entirely ({len(missing)}): {sorted(missing)[:30]}{'...' if len(missing)>30 else ''}")
    print(f"  pairs NOT in template ({len(extra)}): {sorted(extra)[:30]}{'...' if len(extra)>30 else ''}")
    nd = sorted(diff.items())[:80]
    print(f"  pairs FREQ DIFF ({len(diff)}): show first {len(nd)}")
    for p, (tpl, c) in nd:
        print(f"    {p}: template={tpl} db={c}")

conn.close()
print("\nDONE")
