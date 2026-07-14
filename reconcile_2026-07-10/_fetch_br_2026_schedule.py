"""
_fetch_br_2026_schedule.py — 抓取 Basketball-Reference 2025-26 常规赛赛程，
写出 reconcile_2026-07-10/br_2026_rs.tsv（date \t away \t home）。

依赖：复用 nba_daily_crawler.BrowserManager（已验证可在此机跑通 Chrome 150 + 过 CF）。
前置：需先有 CF cookie（nba_data/.br_cf_cookies.pkl，可由 gen_cf_cookie.py 生成）。

用法（禁用代理）：
  cd /c/autopick/AutoPick/nba_data
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    python nba_desktop/nba_desktop_omega/reconcile_2026-07-10/_fetch_br_2026_schedule.py
"""
import os, sys, time, datetime, logging
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
# reconcile_2026-07-10 -> nba_desktop_omega -> nba_desktop -> nba_data（三级上溯）
NBA_DATA = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, NBA_DATA)
from nba_daily_crawler import BrowserManager

log = logging.getLogger('fetch_br_2026')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

MONTHS = ['october', 'november', 'december', 'january', 'february', 'march', 'april']
BASE = 'https://www.basketball-reference.com/leagues/NBA_2026_games-'

TEAM = {
    'Atlanta Hawks': 'ATL', 'Boston Celtics': 'BOS', 'Brooklyn Nets': 'BRK',
    'Charlotte Hornets': 'CHO', 'Chicago Bulls': 'CHI', 'Cleveland Cavaliers': 'CLE',
    'Dallas Mavericks': 'DAL', 'Denver Nuggets': 'DEN', 'Detroit Pistons': 'DET',
    'Golden State Warriors': 'GSW', 'Houston Rockets': 'HOU', 'Indiana Pacers': 'IND',
    'Los Angeles Clippers': 'LAC', 'Los Angeles Lakers': 'LAL', 'Memphis Grizzlies': 'MEM',
    'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL', 'Minnesota Timberwolves': 'MIN',
    'New Orleans Pelicans': 'NOP', 'New York Knicks': 'NYK', 'Oklahoma City Thunder': 'OKC',
    'Orlando Magic': 'ORL', 'Philadelphia 76ers': 'PHI', 'Phoenix Suns': 'PHO',
    'Portland Trail Blazers': 'POR', 'Sacramento Kings': 'SAC', 'San Antonio Spurs': 'SAS',
    'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTA', 'Washington Wizards': 'WAS',
}

BM = BrowserManager(log)
BM.start()  # 注入已生成的 CF cookie（nba_data/.br_cf_cookies.pkl），单会话复用

rows = []
for m in MONTHS:
    url = BASE + m + '.html'
    print('GET', url)
    html = BM.fetch_page(url, cf_timeout=90)
    if html is None:
        print('  !! fetch failed (CF) for', m)
        continue
    tables = pd.read_html(html, flavor='lxml')
    sched = None
    for t in tables:
        cols = [str(c) for c in t.columns]
        if 'Date' in cols and any(c.startswith('Visitor') for c in cols) \
                and any(c.startswith('Home') for c in cols):
            sched = t
            break
    if sched is None:
        print('  !! no schedule table found in', m)
        continue
    vcol = [c for c in sched.columns if str(c).startswith('Visitor')][0]
    hcol = [c for c in sched.columns if str(c).startswith('Home')][0]
    note_col = None
    for c in sched.columns:
        if 'note' in str(c).lower() or 'play' in str(c).lower():
            note_col = c
            break
    cnt = 0
    for _, r in sched.iterrows():
        d = r['Date']
        if not isinstance(d, str) or ',' not in d:
            continue
        try:
            dt = datetime.datetime.strptime(d, '%a, %b %d, %Y')
        except Exception:
            continue
        ds = dt.strftime('%Y-%m-%d')
        a = TEAM.get(str(r[vcol]).strip())
        h = TEAM.get(str(r[hcol]).strip())
        if not a or not h:
            continue
        note = str(r[note_col]) if note_col is not None else ''
        # exclude Play-In and the single NBA Cup final (extra game)
        if 'Play-In' in note:
            continue
        if ds == '2025-12-16' and a == 'SAS' and h == 'NYK':
            continue
        rows.append((ds, a, h))
        cnt += 1
    print(f'  parsed {cnt} RS rows from {m}')

BM.quit()
# dedupe
rows = sorted(set(rows))
out = os.path.join(HERE, 'br_2026_rs.tsv')
with open(out, 'w') as f:
    for ds, a, h in rows:
        f.write(f'{ds}\t{a}\t{h}\n')
print('TOTAL BR 2025-26 RS games:', len(rows))
print('written to', out)
