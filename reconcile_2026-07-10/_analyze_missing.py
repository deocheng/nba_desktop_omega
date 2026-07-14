"""
_analyze_missing.py — 在 BR 权威赛程与 DB dim_games 之间做带日期容差(±1天)的匹配，
分离「真缺失」(BR 有、DB 在 ±1 天内也没有) 与「日期偏差假阳性」(同对阵仅差 1 天)。

用法（禁用代理）：
  cd /c/autopick/AutoPick/nba_data
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    python nba_desktop/nba_desktop_omega/reconcile_2026-07-10/_analyze_missing.py
"""
import os, sys, datetime
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
TSV = os.path.join(HERE, 'br_2026_rs.tsv')

# BR 权威赛程: (away,home) -> set(date_str)
br = {}
with open(TSV) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        ds, a, h = line.split('\t')
        if ds > '2026-04-15':
            continue  # 4/16 起为季后赛，不在 RS 范围内
        br.setdefault((a, h), set()).add(ds)
br_all = set()
for (a, h), dset in br.items():
    for ds in dset:
        br_all.add((ds, a, h))

c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                     user='postgres', password=os.environ.get('DB_PASSWORD'))
cur = c.cursor()
cur.execute("""
    SELECT game_date, away_team_abbr, home_team_abbr
    FROM dim_games
    WHERE season = 2026 AND season_type = 'Regular Season'
      AND home_team_abbr IS NOT NULL AND away_team_abbr IS NOT NULL
""")
db_rows = cur.fetchall()
c.close()

exact = 0
near = 0          # 同对阵、日期差 <=1 天（日期偏差假阳性）
no_match = 0      # DB 行在 BR 中找不到同对阵(±1天)
br_matched = set()

for date, a, h in db_rows:
    ds = str(date)
    key = (a, h)
    if key in br:
        if ds in br[key]:
            exact += 1
            br_matched.add((ds, a, h))
        else:
            d0 = date
            found = False
            for dstr in br[key]:
                dd = datetime.date.fromisoformat(dstr)
                if abs((dd - d0).days) <= 1:
                    found = True
                    break
            if found:
                near += 1
                br_matched.add((ds, a, h))
            else:
                no_match += 1
    else:
        no_match += 1

unmatched_br = br_all - br_matched
print('BR total RS games (authority):', len(br_all))
print('DB RS non-null rows         :', len(db_rows))
print('  exact match (date+abbr)   :', exact)
print('  near match (±1 day)       :', near, '  <-- 日期偏差假阳性')
print('  DB rows no BR match(±1d)  :', no_match)
print()
print('=== TRUE MISSING (BR has, DB lacks within ±1d):', len(unmatched_br), '===')
out = os.path.join(HERE, 'missing_2026_rs.tsv')
with open(out, 'w') as f:
    for ds, a, h in sorted(unmatched_br):
        f.write(f'{ds}\t{a}\t{h}\n')
        print(f'  {ds} {a} @ {h}')
print('written ->', out)
