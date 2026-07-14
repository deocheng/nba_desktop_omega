"""
NBA 伤病数据 + 球队薪资数据爬虫
数据源: Basketball Reference
"""

import requests
import time
import re
import json
import random
import logging
from datetime import datetime
from bs4 import BeautifulSoup
import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_CONFIG = {
    'host': 'localhost', 'port': 5433,
    'dbname': 'nba', 'user': 'postgres', 'password': 'postgres'
}

BASE_URL = "https://www.basketball-reference.com"

TEAM_ABBRS = [
    'ATL', 'BOS', 'BRK', 'CHO', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
    'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
    'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
]

TEAM_NAMES = {
    'ATL': 'Atlanta Hawks', 'BOS': 'Boston Celtics', 'BRK': 'Brooklyn Nets',
    'CHO': 'Charlotte Hornets', 'CHI': 'Chicago Bulls', 'CLE': 'Cleveland Cavaliers',
    'DAL': 'Dallas Mavericks', 'DEN': 'Denver Nuggets', 'DET': 'Detroit Pistons',
    'GSW': 'Golden State Warriors', 'HOU': 'Houston Rockets', 'IND': 'Indiana Pacers',
    'LAC': 'Los Angeles Clippers', 'LAL': 'Los Angeles Lakers', 'MEM': 'Memphis Grizzlies',
    'MIA': 'Miami Heat', 'MIL': 'Milwaukee Bucks', 'MIN': 'Minnesota Timberwolves',
    'NOP': 'New Orleans Pelicans', 'NYK': 'New York Knicks', 'OKC': 'Oklahoma City Thunder',
    'ORL': 'Orlando Magic', 'PHI': 'Philadelphia 76ers', 'PHX': 'Phoenix Suns',
    'POR': 'Portland Trail Blazers', 'SAC': 'Sacramento Kings', 'SAS': 'San Antonio Spurs',
    'TOR': 'Toronto Raptors', 'UTA': 'Utah Jazz', 'WAS': 'Washington Wizards'
}


class LightScraper:
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    ]

    def __init__(self, delay_min=3, delay_max=6):
        self.delay_min = delay_min
        self.delay_max = delay_max

    def fetch(self, url):
        time.sleep(random.uniform(self.delay_min, self.delay_max))
        headers = {
            'User-Agent': random.choice(self.USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.basketball-reference.com/',
        }
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.text


def parse_money(text):
    if not text:
        return None
    t = text.strip().replace('$', '').replace(',', '').strip()
    if not t:
        return None
    try:
        return int(t)
    except ValueError:
        return None


def init_db(conn):
    cur = conn.cursor()
    # injuries 表已存在，检查是否需要新增列
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='injuries' AND column_name='description'
    """)
    if not cur.fetchone():
        cur.execute("ALTER TABLE injuries ADD COLUMN description TEXT")
        cur.execute("ALTER TABLE injuries ADD COLUMN body_part VARCHAR(64)")
        cur.execute("ALTER TABLE injuries ADD COLUMN source_url TEXT")
        cur.execute("ALTER TABLE injuries ADD COLUMN scraped_at TIMESTAMP DEFAULT NOW()")
        conn.commit()
        logger.info("injuries 表已新增列: description, body_part, source_url, scraped_at")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS team_payroll (
            team_abbr VARCHAR(8) NOT NULL,
            team_name VARCHAR(64),
            season VARCHAR(8) NOT NULL,
            salary_cap BIGINT,
            largest_guarantee BIGINT,
            largest_guarantee_player TEXT,
            source_url TEXT,
            scraped_at TIMESTAMP NOT NULL DEFAULT NOW(),
            total_2025_26 BIGINT, total_2026_27 BIGINT, total_2027_28 BIGINT,
            total_2028_29 BIGINT, total_2029_30 BIGINT, total_2030_31 BIGINT,
            total_guaranteed BIGINT, player_count INT,
            PRIMARY KEY (team_abbr, season)
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_contracts (
            team_abbr VARCHAR(8) NOT NULL,
            season VARCHAR(8) NOT NULL,
            player_id VARCHAR(32),
            player_name TEXT NOT NULL,
            age INT,
            salary_2025_26 BIGINT, salary_2026_27 BIGINT, salary_2027_28 BIGINT,
            salary_2028_29 BIGINT, salary_2029_30 BIGINT, salary_2030_31 BIGINT,
            opt_2025_26 VARCHAR(20), opt_2026_27 VARCHAR(20), opt_2027_28 VARCHAR(20),
            opt_2028_29 VARCHAR(20), opt_2029_30 VARCHAR(20), opt_2030_31 VARCHAR(20),
            guaranteed BIGINT, is_partial BOOLEAN DEFAULT FALSE,
            notes JSONB, source_url TEXT,
            scraped_at TIMESTAMP NOT NULL DEFAULT NOW(),
            PRIMARY KEY (team_abbr, season, player_id)
        );
    """)
    conn.commit()
    cur.close()
    logger.info("数据库表初始化完成")


def scrape_injuries(scraper, conn):
    url = f"{BASE_URL}/friv/injuries.fcgi"
    logger.info(f"爬取伤病数据: {url}")
    html = scraper.fetch(url)
    soup = BeautifulSoup(html, 'lxml')

    table = soup.find('table', id='injuries')
    if not table:
        logger.error("未找到伤病表格")
        return 0

    rows = []
    scraped_at = datetime.now()

    for tr in table.find('tbody').find_all('tr'):
        th = tr.find('th', {'data-stat': 'player'})
        if not th:
            continue
        a = th.find('a')
        player_name = a.get_text(strip=True) if a else th.get_text(strip=True)

        td_team = tr.find('td', {'data-stat': 'team'})
        team_name = td_team.get_text(strip=True) if td_team else ''
        team_abbr = td_team.get('csk', '') if td_team else ''

        td_date = tr.find('td', {'data-stat': 'update'})
        update_date_raw = td_date.get_text(strip=True) if td_date else ''

        td_desc = tr.find('td', {'data-stat': 'description'})
        description = td_desc.get_text(strip=True) if td_desc else ''

        status, body_part = None, None
        m = re.match(r'^(.+?)\s*\((.+?)\)\s*[-]?\s*(.*)', description)
        if m:
            status = m.group(1).strip()
            body_part = m.group(2).strip()

        # 解析日期: "Mon, Mar 9, 2026" -> 2026-03-09
        update_date = datetime.now().date()  # 默认当天
        if update_date_raw:
            try:
                from dateutil import parser as dtparser
                update_date = dtparser.parse(update_date_raw).date()
            except:
                try:
                    update_date = datetime.strptime(update_date_raw, '%a, %b %d, %Y').date()
                except:
                    pass

        # 适配现有表结构: report_date, player_name, team_abbr, injury, status, source, created_at
        rows.append((update_date, player_name, team_abbr, description, status, url, scraped_at))

    cur = conn.cursor()
    cur.execute("DELETE FROM injuries WHERE crawl_date = CURRENT_DATE")
    if rows:
        execute_values(cur, """
            INSERT INTO injuries (report_date, player_name, team_abbr, injury, status, source, created_at, crawl_date)
            VALUES %s
        """, rows)
    conn.commit()
    cur.close()
    logger.info(f"伤病数据写入完成: {len(rows)} 条")
    return len(rows)


def scrape_payroll_summary(scraper, conn):
    url = f"{BASE_URL}/contracts/"
    logger.info(f"爬取薪资汇总: {url}")
    html = scraper.fetch(url)
    soup = BeautifulSoup(html, 'lxml')

    salary_cap = None
    cap_div = soup.find('div', string=re.compile(r'Salary Cap'))
    if cap_div:
        m = re.search(r'\$([\d,]+)', cap_div.get_text())
        if m:
            salary_cap = int(m.group(1).replace(',', ''))

    table = soup.find('table', id='contracts')
    if not table:
        logger.error("未找到薪资汇总表格")
        return {}

    team_totals = {}
    for tr in table.find('tbody').find_all('tr'):
        th = tr.find('th', {'data-stat': 'team'})
        if not th:
            continue
        a = th.find('a')
        if not a:
            continue
        team_abbr = a['href'].split('/')[-1].replace('.html', '')
        team_name = a.get_text(strip=True)
        totals = {}
        for stat in ['y1', 'y2', 'y3', 'y4', 'y5', 'y6']:
            td = tr.find('td', {'data-stat': stat})
            totals[f'total_{stat}'] = parse_money(td.get_text(strip=True)) if td else None
        team_totals[team_abbr] = {'team_name': team_name, 'salary_cap': salary_cap, **totals}

    logger.info(f"薪资汇总: {len(team_totals)} 支球队, Cap: ${salary_cap:,}" if salary_cap else f"薪资汇总: {len(team_totals)} 支球队")
    return team_totals


def scrape_team_contracts(scraper, conn, team_abbr, team_name, summary_data):
    url = f"{BASE_URL}/contracts/{team_abbr}.html"
    logger.info(f"  爬取 {team_abbr} ({team_name})...")
    html = scraper.fetch(url)
    soup = BeautifulSoup(html, 'lxml')

    contracts_tbl = soup.find('table', id='contracts')
    if not contracts_tbl:
        logger.warning(f"  {team_abbr}: 未找到合同表格")
        return

    season = "2025-26"
    scraped_at = datetime.now()
    players = []

    for tr in contracts_tbl.find('tbody').find_all('tr'):
        th = tr.find('th', {'data-stat': 'player'})
        if not th:
            continue
        a = th.find('a')
        player_name = a.get_text(strip=True) if a else th.get_text(strip=True)
        player_id = (a['href'].split('/')[-1].replace('.html', '') if a and a.get('href') else None)
        is_italic = th.find('em') is not None

        def cell(stat):
            td = tr.find(['td', 'th'], {'data-stat': stat})
            return td.get_text(strip=True) if td else ''

        def option_flag(td):
            if not td: return None
            cls = td.get('class', [])
            if 'salary-pl' in cls: return 'player_option'
            if 'salary-tm' in cls: return 'team_option'
            return None

        age_txt = cell('age_today')
        age = int(age_txt) if age_txt.isdigit() else None

        y1 = tr.find('td', {'data-stat': 'y1'})
        y2 = tr.find('td', {'data-stat': 'y2'})
        y3 = tr.find('td', {'data-stat': 'y3'})
        y4 = tr.find('td', {'data-stat': 'y4'})
        y5 = tr.find('td', {'data-stat': 'y5'})
        y6 = tr.find('td', {'data-stat': 'y6'})

        players.append({
            'player_id': player_id, 'player_name': player_name, 'age': age,
            'salary_2025_26': parse_money(cell('y1')), 'salary_2026_27': parse_money(cell('y2')),
            'salary_2027_28': parse_money(cell('y3')), 'salary_2028_29': parse_money(cell('y4')),
            'salary_2029_30': parse_money(cell('y5')), 'salary_2030_31': parse_money(cell('y6')),
            'opt_2025_26': option_flag(y1), 'opt_2026_27': option_flag(y2),
            'opt_2027_28': option_flag(y3), 'opt_2028_29': option_flag(y4),
            'opt_2029_30': option_flag(y5), 'opt_2030_31': option_flag(y6),
            'guaranteed': parse_money(cell('remain_gtd')), 'is_partial': is_italic,
        })

    # Notes
    notes_tbl = soup.find('table', id='payroll-notes')
    notes_map = {}
    if notes_tbl:
        for tr in notes_tbl.find('tbody').find_all('tr'):
            th = tr.find('th', {'data-stat': 'player'})
            if not th: continue
            a = th.find('a')
            pid = (a['href'].split('/')[-1].replace('.html', '') if a and a.get('href') else None)
            notes_td = tr.find('td', {'data-stat': 'notes'})
            bullets = [li.get_text(' ', strip=True) for li in notes_td.find_all('li')] if notes_td else []
            notes_map[pid] = bullets
    for p in players:
        p['notes'] = json.dumps(notes_map.get(p['player_id'], []), ensure_ascii=False)

    # Team Totals
    tfoot = contracts_tbl.find('tfoot')
    totals = {}
    if tfoot:
        for tr in tfoot.find_all('tr'):
            for stat in ('y1', 'y2', 'y3', 'y4', 'y5', 'y6', 'remain_gtd'):
                td = tr.find('td', {'data-stat': stat})
                if td: totals[stat] = parse_money(td.get_text(strip=True))

    # Largest guarantee
    largest_guarantee, largest_player = None, None
    lg_div = soup.find('div', string=re.compile(r'Largest Guarantee'))
    if lg_div:
        m = re.search(r'(.+?)\s*\$([\d,]+)', lg_div.get_text())
        if m:
            largest_player = m.group(1).strip()
            largest_guarantee = int(m.group(2).replace(',', ''))

    # Write to DB
    cur = conn.cursor()
    salary_cap = summary_data.get('salary_cap') if summary_data else None

    cur.execute("""
        INSERT INTO team_payroll
            (team_abbr, team_name, season, salary_cap, largest_guarantee,
             largest_guarantee_player, source_url, scraped_at,
             total_2025_26, total_2026_27, total_2027_28,
             total_2028_29, total_2029_30, total_2030_31,
             total_guaranteed, player_count)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (team_abbr, season) DO UPDATE SET
            team_name=EXCLUDED.team_name, salary_cap=EXCLUDED.salary_cap,
            largest_guarantee=EXCLUDED.largest_guarantee,
            largest_guarantee_player=EXCLUDED.largest_guarantee_player,
            source_url=EXCLUDED.source_url, scraped_at=EXCLUDED.scraped_at,
            total_2025_26=EXCLUDED.total_2025_26, total_2026_27=EXCLUDED.total_2026_27,
            total_2027_28=EXCLUDED.total_2027_28, total_2028_29=EXCLUDED.total_2028_29,
            total_2029_30=EXCLUDED.total_2029_30, total_2030_31=EXCLUDED.total_2030_31,
            total_guaranteed=EXCLUDED.total_guaranteed, player_count=EXCLUDED.player_count;
    """, (team_abbr, team_name, season, salary_cap, largest_guarantee, largest_player,
          url, scraped_at, totals.get('y1'), totals.get('y2'), totals.get('y3'),
          totals.get('y4'), totals.get('y5'), totals.get('y6'),
          totals.get('remain_gtd'), len(players)))

    rows = [(team_abbr, season, p['player_id'], p['player_name'], p['age'],
             p['salary_2025_26'], p['salary_2026_27'], p['salary_2027_28'],
             p['salary_2028_29'], p['salary_2029_30'], p['salary_2030_31'],
             p['opt_2025_26'], p['opt_2026_27'], p['opt_2027_28'],
             p['opt_2028_29'], p['opt_2029_30'], p['opt_2030_31'],
             p['guaranteed'], p['is_partial'], p['notes'], url, scraped_at)
            for p in players]

    if rows:
        execute_values(cur, """
            INSERT INTO player_contracts
                (team_abbr, season, player_id, player_name, age,
                 salary_2025_26, salary_2026_27, salary_2027_28,
                 salary_2028_29, salary_2029_30, salary_2030_31,
                 opt_2025_26, opt_2026_27, opt_2027_28,
                 opt_2028_29, opt_2029_30, opt_2030_31,
                 guaranteed, is_partial, notes, source_url, scraped_at)
            VALUES %s
            ON CONFLICT (team_abbr, season, player_id) DO UPDATE SET
                player_name=EXCLUDED.player_name, age=EXCLUDED.age,
                salary_2025_26=EXCLUDED.salary_2025_26, salary_2026_27=EXCLUDED.salary_2026_27,
                salary_2027_28=EXCLUDED.salary_2027_28, salary_2028_29=EXCLUDED.salary_2028_29,
                salary_2029_30=EXCLUDED.salary_2029_30, salary_2030_31=EXCLUDED.salary_2030_31,
                opt_2025_26=EXCLUDED.opt_2025_26, opt_2026_27=EXCLUDED.opt_2026_27,
                opt_2027_28=EXCLUDED.opt_2027_28, opt_2028_29=EXCLUDED.opt_2028_29,
                opt_2029_30=EXCLUDED.opt_2029_30, opt_2030_31=EXCLUDED.opt_2030_31,
                guaranteed=EXCLUDED.guaranteed, is_partial=EXCLUDED.is_partial,
                notes=EXCLUDED.notes, source_url=EXCLUDED.source_url, scraped_at=EXCLUDED.scraped_at;
        """, rows)

    conn.commit()
    cur.close()
    logger.info(f"  {team_abbr}: {len(players)} 名球员合同已写入")


def scrape_all_payroll(scraper, conn):
    summary = scrape_payroll_summary(scraper, conn)
    for team_abbr in TEAM_ABBRS:
        team_name = TEAM_NAMES.get(team_abbr, team_abbr)
        summary_data = summary.get(team_abbr, {})
        try:
            scrape_team_contracts(scraper, conn, team_abbr, team_name, summary_data)
        except Exception as e:
            logger.error(f"  {team_abbr} 爬取失败: {e}")
            conn.rollback()


def main():
    start = time.time()
    scraper = LightScraper(delay_min=3, delay_max=6)
    conn = psycopg2.connect(**DB_CONFIG)
    init_db(conn)

    print("\n" + "=" * 60)
    print("[1/2] 爬取伤病数据")
    print("=" * 60)
    injury_count = scrape_injuries(scraper, conn)

    print("\n" + "=" * 60)
    print("[2/2] 爬取球队薪资数据 (30支球队)")
    print("=" * 60)
    scrape_all_payroll(scraper, conn)

    conn.close()
    elapsed = time.time() - start
    print("\n" + "=" * 60)
    print(f"全部爬取完成! 伤病: {injury_count}条, 薪资: 30队, 耗时: {elapsed:.1f}s")
    print("=" * 60)


if __name__ == '__main__':
    main()