#!/usr/bin/env python3
# 补录 2026 RS 维度缺口（紧对账结论：真实缺失 31 场，DB 完全无该球队对）。
# 仅填可靠字段（date/season/teams/br_id），比分全部留 NULL，待 PBP 补爬回填。
# - 幂等：game_id 已存在则跳过
# - 参数化 INSERT（execute_values + ON CONFLICT），无动态 SQL 拼值
# - dim_games + games 双写
# 用法:
#   python _backfill_2026_gap31.py            # 默认 dry-run，只打印计划
#   python _backfill_2026_gap31.py --execute  # 真正落库
import os, sys, psycopg2
from psycopg2.extras import execute_values

for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)

SEASON = 2026

# 标准 30 队 abbr -> 全称（事实数据，非臆造；照抄现有脚本）
TEAM_NAMES = {
    'ATL': 'Atlanta Hawks', 'BOS': 'Boston Celtics', 'BRK': 'Brooklyn Nets', 'BKN': 'Brooklyn Nets',
    'CHA': 'Charlotte Hornets', 'CHI': 'Chicago Bulls', 'CLE': 'Cleveland Cavaliers',
    'DAL': 'Dallas Mavericks', 'DEN': 'Denver Nuggets', 'DET': 'Detroit Pistons',
    'GSW': 'Golden State Warriors', 'HOU': 'Houston Rockets', 'IND': 'Indiana Pacers',
    'LAC': 'LA Clippers', 'LAL': 'Los Angeles Lakers', 'MEM': 'Memphis Grizzlies',
    'MIA': 'Miami Heat', 'MIL': 'Milwaukee Bucks', 'MIN': 'Minnesota Timberwolves',
    'NOP': 'New Orleans Pelicans', 'NYK': 'New York Knicks', 'OKC': 'Oklahoma City Thunder',
    'ORL': 'Orlando Magic', 'PHI': 'Philadelphia 76ers', 'PHX': 'Phoenix Suns',
    'POR': 'Portland Trail Blazers', 'SAC': 'Sacramento Kings', 'SAS': 'San Antonio Spurs',
    'TOR': 'Toronto Raptors', 'UTA': 'Utah Jazz', 'WAS': 'Washington Wizards',
}

# 紧对账缺口清单（date  away  home，tab 语义；BR 权威清单 vs dim_games season=2026 RS）
_GAP31 = [
    ('2025-10-22', 'SAS', 'DAL'),
    ('2025-10-24', 'MIA', 'MEM'),
    ('2025-10-25', 'OKC', 'ATL'),
    ('2025-10-27', 'POR', 'LAL'),
    ('2025-11-01', 'SAC', 'MIL'),
    ('2025-11-08', 'IND', 'DEN'),
    ('2025-11-08', 'POR', 'MIA'),
    ('2025-11-15', 'MEM', 'CLE'),
    ('2025-11-17', 'OKC', 'NOP'),
    ('2025-11-19', 'NYK', 'DAL'),
    ('2025-11-22', 'WAS', 'CHI'),
    ('2025-11-24', 'POR', 'MIL'),
    ('2025-11-26', 'SAS', 'POR'),
    ('2025-12-05', 'POR', 'DET'),
    ('2025-12-06', 'SAC', 'MIA'),
    ('2025-12-07', 'GSW', 'CHI'),
    ('2025-12-19', 'SAS', 'ATL'),
    ('2025-12-20', 'WAS', 'MEM'),
    ('2025-12-29', 'GSW', 'BRK'),
    ('2026-01-01', 'HOU', 'BRK'),
    ('2026-01-07', 'ORL', 'BRK'),
    ('2026-01-10', 'MIN', 'CLE'),
    ('2026-01-10', 'SAS', 'BOS'),
    ('2026-01-13', 'MIN', 'MIL'),
    ('2026-01-27', 'DET', 'DEN'),
    ('2026-01-29', 'HOU', 'ATL'),
    ('2026-02-05', 'SAS', 'DAL'),
    ('2026-02-22', 'PHI', 'MIN'),
    ('2026-02-26', 'SAS', 'BRK'),
    ('2026-04-24', 'SAS', 'POR'),
    ('2026-04-26', 'SAS', 'POR'),
]


def parse_gap():
    rows = []
    for ds, a, h in _GAP31:
        br_id = ds.replace('-', '') + h  # YYYYMMDD + home_abbr（BR 键格式）
        rows.append({
            'game_id': br_id,
            'game_date': ds,
            'season': SEASON,
            'season_type': 'Regular Season',
            'away_team_abbr': a,
            'home_team_abbr': h,
            'away_team_name': TEAM_NAMES.get(a, a),
            'home_team_name': TEAM_NAMES.get(h, h),
            'away_team_id': a,
            'home_team_id': h,
            'br_crawled_id': br_id,
            'nba_api_id': None,
            'source': 'BBRef',
            'game_status': 'Final',
            'pbp_saved': False,
            'pbp_imported': False,
        })
    return rows


def _count(cur, tbl, todo):
    cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE game_id = ANY(%s)",
                ([r['game_id'] for r in todo],))
    return cur.fetchone()[0]


def main():
    execute = '--execute' in sys.argv
    rows = parse_gap()
    c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                         user='postgres', password=os.environ.get('DB_PASSWORD'))
    cur = c.cursor()
    # 幂等过滤：以 dim_games 已存在的 game_id 为准
    cur.execute("SELECT game_id FROM dim_games WHERE game_id = ANY(%s)",
                ([r['game_id'] for r in rows],))
    existing = {r[0] for r in cur.fetchall()}
    todo = [r for r in rows if r['game_id'] not in existing]

    print(f'清单总行数: {len(rows)} | 已存在跳过: {len(rows)-len(todo)} | 待补录: {len(todo)}')
    if not todo:
        print('无需补录，dim_games 已包含全部 31 场。')
        c.close()
        return

    if not execute:
        print('=== DRY-RUN（加 --execute 才落库）全量计划 ===')
        for r in todo:
            print(f"  {r['game_id']} {r['game_date']} {r['away_team_abbr']}@{r['home_team_abbr']} "
                  f"name={r['away_team_name']}@{r['home_team_name']}")
        print(f'共 {len(todo)} 条。')
        c.close()
        return

    # 落库：dim_games + games 双写（execute_values 的 rowcount 不可靠，落库后用计数差汇报）
    dim_cols = ['game_id', 'game_date', 'season', 'season_type',
                'away_team_abbr', 'home_team_abbr', 'away_team_name', 'home_team_name',
                'away_team_id', 'home_team_id', 'br_crawled_id', 'nba_api_id',
                'source', 'game_status', 'pbp_saved', 'pbp_imported']
    games_cols = ['game_id', 'game_date', 'season', 'season_type',
                  'away_team_abbr', 'home_team_abbr', 'br_crawled_id', 'nba_api_id',
                  'source', 'game_status']

    dim_data = [tuple(r[col] for col in dim_cols) for r in todo]
    games_data = [tuple(r[col] for col in games_cols) for r in todo]

    dim_before = _count(cur, 'dim_games', todo)
    games_before = _count(cur, 'games', todo)
    execute_values(cur,
                   "INSERT INTO dim_games (" + ','.join(dim_cols) + ") VALUES %s "
                   "ON CONFLICT (game_id) DO NOTHING", dim_data)
    execute_values(cur,
                   "INSERT INTO games (" + ','.join(games_cols) + ") VALUES %s "
                   "ON CONFLICT DO NOTHING", games_data)
    c.commit()
    n_dim = _count(cur, 'dim_games', todo) - dim_before
    n_games = _count(cur, 'games', todo) - games_before
    print(f'已插入 dim_games: {n_dim} 行, games: {n_games} 行（幂等 ON CONFLICT DO NOTHING）')
    c.close()


if __name__ == '__main__':
    main()
