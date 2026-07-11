"""_diag_abbr.py — 比对 DB dim_games 与 BR 赛程的球队缩写是否一致。"""
import os, psycopg2, glob
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
TSV = glob.glob(r'C:/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega/reconcile_2026-07-10/br_2026_rs.tsv')[0]
c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                     user='postgres', password='postgres')
cur = c.cursor()
cur.execute("SELECT DISTINCT away_team_abbr FROM dim_games WHERE season=2026 AND season_type='Regular Season'")
dba = [r[0] for r in cur.fetchall() if r[0]]
cur.execute("SELECT DISTINCT home_team_abbr FROM dim_games WHERE season=2026 AND season_type='Regular Season'")
dbh = [r[0] for r in cur.fetchall() if r[0]]
c.close()
br = set()
for line in open(TSV):
    p = line.strip().split('\t')
    if len(p) == 3 and p[1] and p[2]:
        br.add(p[1]); br.add(p[2])
dbset = set(dba) | set(dbh)
print('DB away abbrs:', sorted(dba))
print('DB home abbrs:', sorted(dbh))
print('BR abbrs    :', sorted(br))
print('DB-only (not in BR):', sorted(dbset - br))
print('BR-only (not in DB):', sorted(br - dbset))
print('counts: db_distinct=%d br_distinct=%d' % (len(dbset), len(br)))
