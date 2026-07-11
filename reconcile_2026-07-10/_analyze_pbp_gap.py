"""
_analyze_pbp_gap.py — 对 241 场已补录的 2026 RS 维度游戏，确定「真正缺 PBP」的子集。

纠正之前「朴素查 PBP=0」的误导：必须按 app 实际的 _resolve_join_key 逻辑取 join key：
  - 若 games.nba_api_id 非空 -> join key = str(nba_api_id)（数字 key，player_gamelog/play_by_play 用）
  - 否则 -> join key = game_id 本身（BR 格式，如 202511010IND）
然后查 play_by_play WHERE gameid = join_key。

用法（禁用代理）:
  cd /c/autopick/AutoPick/nba_data
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    python nba_desktop/nba_desktop_omega/reconcile_2026-07-10/_analyze_pbp_gap.py
"""
import os, sys, psycopg2

for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)

HERE = os.path.dirname(os.path.abspath(__file__))
TSV = os.path.join(HERE, 'missing_2026_rs.tsv')

# 读 241 场（与补录时同一来源）
games = []
with open(TSV) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        ds, a, h = line.split('\t')
        br_id = ds.replace('-', '') + h
        games.append((br_id, ds, a, h))

c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                     user='postgres', password='postgres')
cur = c.cursor()

missing = []   # 真正缺 PBP（按 app join key 查为 0）
present = []   # 已有 PBP
for br_id, ds, a, h in games:
    # 取真实 games 行的 nba_api_id（可能因 backfill 幂等跳过而原本就有）
    cur.execute("SELECT nba_api_id FROM games WHERE game_id=%s", (br_id,))
    row = cur.fetchone()
    nba_api_id = row[0] if row and row[0] is not None else None
    join_key = str(nba_api_id) if nba_api_id is not None else br_id
    cur.execute("SELECT COUNT(*) FROM play_by_play WHERE gameid=%s", (join_key,))
    cnt = cur.fetchone()[0]
    if cnt == 0:
        missing.append((br_id, ds, a, h, nba_api_id, join_key))
    else:
        present.append((br_id, cnt))

# 交叉复核：missing 里是否已有 PBP 落在「同 (date,teams) 的其它 games 行」的 nba_api_id 下
# （捕捉 key 错配：PBP 被 ingest 到另一个数字 key，但该 key 对应的 games 行是同一场）
cross = 0
for br_id, ds, a, h, nba_api_id, join_key in missing:
    cur.execute("""
        SELECT COUNT(*) FROM play_by_play pbp
        JOIN games g ON g.nba_api_id::text = pbp.gameid
        WHERE g.game_date = %s AND g.away_team_abbr = %s AND g.home_team_abbr = %s
          AND g.game_id <> %s
    """, (ds, a, h, br_id))
    if cur.fetchone()[0] > 0:
        cross += 1

c.close()
print(f'241 场总数            : {len(games)}')
print(f'已有 PBP (app key)    : {len(present)}')
print(f'真正缺 PBP (需补爬)   : {len(missing)}')
print(f'  其中 key 错配命中    : {cross}  (同场不同数字 key 已有 PBP，不需爬)')
print()
print('=== 缺 PBP 样本（前 15）===')
for br_id, ds, a, h, nba_api_id, join_key in missing[:15]:
    na = 'NULL' if nba_api_id is None else str(nba_api_id)
    print(f'  {br_id} {ds} {a}@{h}  nba_api_id={na}  join={join_key}')

out = os.path.join(HERE, 'pbp_missing_2026_rs.tsv')
with open(out, 'w') as f:
    for br_id, ds, a, h, nba_api_id, join_key in missing:
        f.write(f'{ds}\t{a}\t{h}\t{br_id}\t{join_key}\n')
print()
print('written ->', out)
