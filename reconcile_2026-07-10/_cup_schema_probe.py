import os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2
conn = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password='postgres')
cur = conn.cursor()
# columns of dim_games
cur.execute("""SELECT column_name, data_type, is_nullable, column_default
               FROM information_schema.columns WHERE table_name='dim_games' ORDER BY ordinal_position""")
print("=== dim_games columns ===")
for r in cur.fetchall():
    print(r)
# full sample of an existing legitimate Cup final row (202412170OKC)
cur.execute("SELECT * FROM dim_games WHERE game_id='202412170OKC'")
cols = [d[0] for d in cur.description]
print("\n=== sample Cup row 202412170OKC ===")
row = cur.fetchone()
for c, v in zip(cols, row):
    print(f"  {c} = {v!r}")
conn.close()
