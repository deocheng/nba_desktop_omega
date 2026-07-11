import os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2
from collections import Counter, defaultdict

conn = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password='postgres')
cur = conn.cursor()

# Use the authoritative `season` column directly.
cur.execute("""SELECT game_id, game_date, season, home_team_abbr, away_team_abbr, season_type, source, nba_api_id
               FROM dim_games WHERE season_type='Regular Season' AND season IN (2024,2025,2026)""")
rows = cur.fetchall()
print("RS rows in seasons 2024/2025/2026:", len(rows))

by_season = defaultdict(list)
none_abbr = 0
for gid, d, s, h, a, st, src, nid in rows:
    if h is None or a is None:
        none_abbr += 1
        continue
    by_season[s].append((gid, d, h, a, src, nid))
print(f"  skipped NULL-abbr: {none_abbr}\n")

for s in (2024, 2025, 2026):
    games = by_season.get(s, [])
    pairs = Counter(tuple(sorted((h, a))) for (_, _, h, a, _, _) in games)
    dates = [d for (_, d, _, _, _, _) in games]
    n_api = sum(1 for g in games if g[5] is not None)
    bbr = sum(1 for g in games if g[4] == 'BBRef')
    print(f"=== Season {s} ===")
    print(f"  RS games={len(games)}  distinct_pairs={len(pairs)}  nba_api={n_api}  BBRef={bbr}")
    if dates:
        print(f"  date range: {min(dates)} .. {max(dates)}")
    print(f"  expected ~1230 games, ~435 pairs\n")

template = Counter(tuple(sorted((h, a))) for (_, _, h, a, _, _) in by_season.get(2025, []))
print(f"Template season 2025 distinct pairs: {len(template)}")

for s in (2024, 2026):
    games = by_season.get(s, [])
    pairs = Counter(tuple(sorted((h, a))) for (_, _, h, a, _, _) in games)
    diff = {p: (template.get(p), c) for p, c in pairs.items() if template.get(p) != c}
    over = {p: c for p, c in pairs.items() if c > template.get(p, 0)}
    under = {p: c for p, c in pairs.items() if c < template.get(p, 0)}
    print(f"\n=== Season {s} vs 2025 template ===")
    print(f"  pairs OVER-played (db>template): {len(over)}  total excess={sum(c-t for p,(t,c) in [(p,(template.get(p),c)) for p,c in over.items()])}")
    print(f"  pairs UNDER-played (db<template): {len(under)}  total deficit={sum(t-c for p,(t,c) in [(p,(template.get(p),c)) for p,c in under.items()])}")
    # show a few over-played with their dates to diagnose
    print(f"  sample OVER-played pairs (pair: db_count, dates):")
    for p in sorted(over, key=lambda x: -over[x])[:8]:
        ds = sorted(d for (_, d, h, a, _, _) in games if tuple(sorted((h, a))) == p)
        print(f"    {p}: {over[p]} -> {ds[:6]}{'...' if len(ds)>6 else ''}")

conn.close()
print("\nDONE")
