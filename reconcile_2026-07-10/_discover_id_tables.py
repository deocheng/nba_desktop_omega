import sys, os, csv
sys.path.insert(0, r'C:/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega')
os.chdir(r'C:/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega')
from backend.core import config
import psycopg2

TSV = r'C:/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega/reconcile_2026-07-10/pbp_missing_2026_rs.tsv'
# col5 = join_key (11-bit BR id), e.g. 20251022ORL
ids = []
with open(TSV, encoding='utf-8') as f:
    for line in f:
        line = line.rstrip('\n')
        if not line or line.startswith('#'):
            continue
        cols = line.split('\t')
        if len(cols) >= 5:
            ids.append(cols[4].strip())
print(f'TSV ids: {len(ids)} (sample {ids[:3]})')

conn = psycopg2.connect(**config.DB_CONFIG)
cur = conn.cursor()

# 1) 所有含 game_id 或 gameid 列的表
cur.execute("""
    SELECT table_name, column_name
    FROM information_schema.columns
    WHERE table_schema='public'
      AND column_name IN ('game_id','gameid')
    ORDER BY table_name, column_name
""")
cols = cur.fetchall()
print(f'\n含 game_id/gameid 的表: {len(cols)}')
for t, c in cols:
    print(f'  {t}.{c}')

# 2) 对每个 (表,列) 查是否含这 241 个 11位 id
print('\n--- 各表含 241 id 的行数 ---')
hits = []
for t, c in cols:
    q = f'SELECT count(*) FROM {t} WHERE {c} = ANY(%s)'
    try:
        cur.execute(q, (ids,))
        n = cur.fetchone()[0]
        if n:
            print(f'  {t}.{c}: {n}')
            hits.append((t, c, n))
    except Exception as e:
        print(f'  {t}.{c}: ERR {e}')

print('\n需要迁移的 (表,列,行数):', hits)
conn.close()
