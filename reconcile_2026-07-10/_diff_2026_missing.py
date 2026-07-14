import os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
tsv = os.path.join(HERE, 'br_2026_rs.tsv')

br = set()
with open(tsv) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        ds, a, h = line.split('\t')
        br.add((ds, a, h))
print('BR authority RS games:', len(br))

c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                     user='postgres', password=os.environ.get('DB_PASSWORD'))
cur = c.cursor()
cur.execute("""
    SELECT game_date, away_team_abbr, home_team_abbr
    FROM dim_games
    WHERE season = 2026 AND season_type = 'Regular Season'
      AND home_team_abbr IS NOT NULL AND away_team_abbr IS NOT NULL
""")
db = set()
for date, a, h in cur.fetchall():
    db.add((str(date), a, h))
# also count NULL-abbr broken rows
cur.execute("""SELECT COUNT(*) FROM dim_games
               WHERE season=2026 AND season_type='Regular Season'
               AND (home_team_abbr IS NULL OR away_team_abbr IS NULL)""")
nullcnt = cur.fetchone()[0]
c.close()
print('DB 2026 RS games (non-null abbr):', len(db))
print('DB 2026 RS rows with NULL abbr (broken):', nullcnt)

missing = sorted(br - db)   # in BR authority, not in DB  -> need to crawl
extra = sorted(db - br)     # in DB, not in BR authority -> review

print('\n=== MISSING in DB (BR has, DB lacks) :', len(missing), '===')
for ds, a, h in missing:
    print(f'  {ds} {a} @ {h}')

print('\n=== EXTRA in DB (DB has, BR lacks) :', len(extra), '===')
for ds, a, h in extra:
    print(f'  {ds} {a} @ {h}')

print('\nSUMMARY: missing=%d extra=%d null_broken=%d db_total=%d br_total=%d'
      % (len(missing), len(extra), nullcnt, len(db), len(br)))
