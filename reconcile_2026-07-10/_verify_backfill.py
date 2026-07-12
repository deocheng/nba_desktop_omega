import sys, os
OMEGA = r'C:/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega'
sys.path.insert(0, OMEGA)
os.chdir(OMEGA)
from backend.core import config
import psycopg2

conn = psycopg2.connect(**config.DB_CONFIG)
cur = conn.cursor()

# 1) 抽样：11位 vs 12位 哪个有行
samples = ['20251022ORL', '202510220ORL', '20251024BRK', '202510240BRK']
print('--- 抽样 gameid 行数（确认新 PBP 是几位）---')
for gid in samples:
    cur.execute("SELECT count(*) FROM play_by_play WHERE gameid=%s", (gid,))
    print(f'  {gid}: {cur.fetchone()[0]}')

# 2) 全库 BR-keyed PBP 的 11位 / 12位 分布
cur.execute("SELECT count(*) FROM play_by_play WHERE gameid ~ '^[0-9]{8}[A-Z]{3}$'")
n11 = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM play_by_play WHERE gameid ~ '^[0-9]{8}0[A-Z]{3}$'")
n12 = cur.fetchone()[0]
print(f'--- 全库 PBP: 11位={n11}  12位={n12} ---')

# 3) 这 241 场 games 的 game_id 格式（games 表当前是几位）
cur.execute("""
    SELECT
      count(*) FILTER (WHERE game_id ~ '^[0-9]{8}[A-Z]{3}$') AS g11,
      count(*) FILTER (WHERE game_id ~ '^[0-9]{8}0[A-Z]{3}$') AS g12
    FROM games WHERE season=2026 AND season_type='Regular Season'
      AND nba_api_id IS NULL
""")
g11, g12 = cur.fetchone()
print(f'--- 2026 RS (nba_api_id NULL) games: 11位={g11}  12位={g12} ---')

conn.close()
