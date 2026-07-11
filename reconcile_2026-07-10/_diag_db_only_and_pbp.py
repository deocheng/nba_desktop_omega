"""
只读诊断：2026 RS 维度表里「DB 独有」可疑行 + 补录 241 场的 PBP 覆盖。
不写库、不烧 LLM 配额。
"""
import os, psycopg2
for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY'):
    os.environ.pop(k, None)

HERE = r'C:/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega/reconcile_2026-07-10'

# 1) 读 BR 权威赛程 (date, away, home)
br = set()
with open(os.path.join(HERE, 'br_2026_rs.tsv')) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        ds, a, h = line.split('\t')
        br.add((ds, a, h))

c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                    user='postgres', password='postgres')
cur = c.cursor()

# 2) 读 dim_games 2026 RS
cur.execute("""SELECT game_id, game_date, away_team_abbr, home_team_abbr,
                      away_team_name, home_team_name, source, season, season_type,
                      pbp_saved, pbp_imported
               FROM dim_games
               WHERE season=2026 AND season_type='Regular Season'""")
rows = cur.fetchall()
cols = [d[0] for d in cur.description]

db_by_key = {}
for r in rows:
    d = dict(zip(cols, r))
    ds = str(d['game_date'])
    key = (ds, d['away_team_abbr'], d['home_team_abbr'])
    db_by_key[key] = d

# DB 独有 = dim 里有、BR 赛程里没有
db_only = [d for key, d in db_by_key.items() if key not in br]

print(f'=== DB 独有（dim 有、BR 赛程无）：{len(db_only)} 场 ===')
# 按来源 / 日期分布
from collections import Counter
src = Counter(d['source'] for d in db_only)
print('来源分布:', dict(src))
# 日期范围
dates = sorted(str(d['game_date']) for d in db_only)
print('日期范围:', dates[0], '~', dates[-1])
# 样例：前 12 条
print('--- 样例（前 12 条）---')
for d in db_only[:12]:
    print(f"  {d['game_id']:<14} {d['game_date']} {d['away_team_abbr']}@{d['home_team_abbr']} "
          f"src={d['source']} pbp_saved={d['pbp_saved']} pbp_imported={d['pbp_imported']}")
# 是否有 PBP
ids_only = [d['game_id'] for d in db_only]
cur.execute('SELECT COUNT(*) FROM play_by_play WHERE gameid = ANY(%s)', (ids_only,))
print('其中已在 play_by_play 有事件的:', cur.fetchone()[0])

# 3) 补录的 241 场 PBP 覆盖
missing_ids = []
with open(os.path.join(HERE, 'missing_2026_rs.tsv')) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        ds, a, h = line.split('\t')
        missing_ids.append(ds.replace('-', '') + h)

cur.execute('SELECT gameid, COUNT(*) FROM play_by_play WHERE gameid = ANY(%s) GROUP BY gameid',
            (missing_ids,))
have_pbp = {g: n for g, n in cur.fetchall()}
with_pbp = sum(1 for i in missing_ids if have_pbp.get(i, 0) > 0)
print(f'\n=== 补录 241 场 PBP 覆盖 ===')
print(f'有 PBP 事件: {with_pbp} / 241')
print(f'无 PBP 需补爬: {241 - with_pbp} / 241')

# 4) 全局 2026 RS 维度表 vs PBP 交叉
cur.execute("""SELECT COUNT(*) FROM dim_games dg
               WHERE dg.season=2026 AND dg.season_type='Regular Season'
                 AND dg.game_id NOT IN (SELECT DISTINCT gameid FROM play_by_play)""")
no_pbp_dims = cur.fetchone()[0]
print(f'\n=== 2026 RS 维度表无 PBP 总数: {no_pbp_dims} ===')
print('(含补录 241 中无 PBP 的部分 + 历史其他缺 PBP 维度行)')

c.close()
