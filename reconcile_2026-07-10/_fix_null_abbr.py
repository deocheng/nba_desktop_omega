"""
安全修复：dim_games 中 source=BBRef 但 away_team_abbr=NULL 的 16 行。
从 BR 权威赛程 (date, home) 反查客队缩写+队名，UPDATE 回填。幂等。
不碰比分、不碰 PBP 标志、不影响其他行。
"""
import os, psycopg2
for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY'):
    os.environ.pop(k, None)

HERE = r'C:/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega/reconcile_2026-07-10'

# BR 赛程按 (date, home) -> (away_abbr, away_name)
TEAM = {
    'ATL':'Atlanta Hawks','BOS':'Boston Celtics','BRK':'Brooklyn Nets','CHA':'Charlotte Hornets',
    'CHI':'Chicago Bulls','CLE':'Cleveland Cavaliers','DAL':'Dallas Mavericks','DEN':'Denver Nuggets',
    'DET':'Detroit Pistons','GSW':'Golden State Warriors','HOU':'Houston Rockets','IND':'Indiana Pacers',
    'LAC':'LA Clippers','LAL':'Los Angeles Lakers','MEM':'Memphis Grizzlies','MIA':'Miami Heat',
    'MIL':'Milwaukee Bucks','MIN':'Minnesota Timberwolves','NOP':'New Orleans Pelicans','NYK':'New York Knicks',
    'OKC':'Oklahoma City Thunder','ORL':'Orlando Magic','PHI':'Philadelphia 76ers','PHO':'Phoenix Suns',
    'POR':'Portland Trail Blazers','SAC':'Sacramento Kings','SAS':'San Antonio Spurs','TOR':'Toronto Raptors',
    'UTA':'Utah Jazz','WAS':'Washington Wizards',
}

br_by_date_home = {}
with open(os.path.join(HERE, 'br_2026_rs.tsv')) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        ds, a, h = line.split('\t')
        br_by_date_home[(ds, h)] = (a, TEAM.get(a, a))

c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                    user='postgres', password='postgres')
cur = c.cursor()

cur.execute("""SELECT game_id, game_date, home_team_abbr
               FROM dim_games
               WHERE season=2026 AND season_type='Regular Season'
                 AND source='BBRef' AND away_team_abbr IS NULL""")
null_rows = cur.fetchall()

todo = []
for gid, gdate, home in null_rows:
    ds = str(gdate)
    hit = br_by_date_home.get((ds, home))
    if hit:
        todo.append((gid, hit[0], hit[1]))
    else:
        print(f'  SKIP {gid} ({ds} {home}): BR 赛程无匹配')

print(f'\n待修复 {len(todo)} 行（预览）：')
for gid, a, an in todo:
    print(f'  {gid}: away_team_abbr <- {a} ({an})')

if '--execute' not in os.sys.argv:
    print('\n[dry-run] 加 --execute 落库')
    c.close()
    raise SystemExit(0)

n = 0
for gid, a, an in todo:
    cur.execute("""UPDATE dim_games SET away_team_abbr=%s, away_team_name=%s
                   WHERE game_id=%s AND away_team_abbr IS NULL""",
                (a, an, gid))
    # games 表若也有该行（按 game_id 或 br_crawled_id）
    cur.execute("""UPDATE games SET away_team_abbr=%s
                   WHERE (game_id=%s OR br_crawled_id=%s) AND away_team_abbr IS NULL""",
                (a, gid, gid))
    n += 1
c.commit()
print(f'\n已修复 {n} 行')
c.close()
