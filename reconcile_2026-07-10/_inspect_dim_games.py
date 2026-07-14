#!/usr/bin/env python3
# 探查 dim_games / games 结构 + 241 缺失场的 PBP 覆盖，为补录脚本设计提供依据。
import os, psycopg2
for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY'):
    os.environ.pop(k, None)

HERE = os.path.dirname(os.path.abspath(__file__))
TSV = os.path.join(HERE, 'missing_2026_rs.tsv')

c = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password=os.environ.get('DB_PASSWORD'))
cur = c.cursor()

def cols(tbl):
    cur.execute(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_name=%s ORDER BY ordinal_position", (tbl,))
    return cur.fetchall()

def pk(tbl):
    cur.execute(
        "SELECT a.attname FROM pg_index i JOIN pg_attribute a "
        "ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) "
        "WHERE i.indrelid=%s::regclass AND i.indisprimary", (tbl,))
    return [r[0] for r in cur.fetchall()]

for t in ('dim_games', 'games'):
    print(f'=== {t} columns ===')
    for r in cols(t):
        print('  ', r)
    print(f'=== {t} PK ===', pk(t))

# 样例：取一条已有 RS 维度的行
cur.execute(
    "SELECT * FROM dim_games WHERE season=2026 AND season_type='Regular Season' "
    "AND away_team_abbr IS NOT NULL LIMIT 1")
sample_cols = [d[0] for d in cur.description]
sample_row = cur.fetchone()
print('=== sample dim_games row ===')
for k_, v in zip(sample_cols, sample_row):
    print(f'   {k_} = {v!r}')

# 241 缺失场里有多少已有 PBP（用 br_id = date无横线 + home_abbr 试探）
missing = []
with open(TSV) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        ds, a, h = line.split('\t')
        br_id = ds.replace('-', '') + h   # YYYYMMDD + home_abbr
        missing.append((ds, a, h, br_id))

cur.execute("SELECT DISTINCT gameid FROM play_by_play WHERE gameid LIKE '2026%'")
pbp_ids = {r[0] for r in cur.fetchall()}

have_pbp, no_pbp = [], []
for ds, a, h, br_id in missing:
    (have_pbp if br_id in pbp_ids else no_pbp).append(br_id)

print(f'=== 241 missing: total={len(missing)} have_pbp={len(have_pbp)} no_pbp={len(no_pbp)} ===')
print('  sample no_pbp br_ids:', no_pbp[:5])
print('  sample have_pbp br_ids:', have_pbp[:5])

# dim_games 是否已存在这些 br_id（防止重复）
cur.execute("SELECT game_id FROM dim_games WHERE game_id = ANY(%s)", ([m[3] for m in missing],))
existing = {r[0] for r in cur.fetchall()}
print(f'=== dim_games already has {len(existing)} of the 241 (should be ~0) ===')

c.close()
