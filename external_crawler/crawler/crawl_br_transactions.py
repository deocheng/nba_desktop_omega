import os
"""
BR Transactions 爬虫
数据源: https://www.basketball-reference.com/leagues/NBA_{year}_transactions.html
写入: transactions 表

用法:
  python crawl_br_transactions.py --year 2026          # 爬 2025-26 赛季
  python crawl_br_transactions.py --year 2026 --dry-run # 测试
  python crawl_br_transactions.py --year 2026 --year 2025 # 多赛季
"""
import requests
from bs4 import BeautifulSoup
import psycopg2
import argparse
import re
import time
from datetime import datetime

try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

DB_CONFIG = dict(host='localhost', port=5433, dbname='nba', user='postgres', password=os.environ.get('DB_PASSWORD'))
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.basketball-reference.com/',
}

# Full team name → abbrev mapping
TEAM_NAME_MAP = {
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

# Transaction type keywords
TX_KEYWORDS = {
    'signed': 'Signed',
    'waived': 'Waived',
    'converted': 'Contract Converted',
    'traded': 'Traded',
    'claimed': 'Claimed off Waivers',
    'released': 'Released',
    'retired': 'Retired',
    'suspended': 'Suspended',
    'fired': 'Coach Fired',
    'hired': 'Coach Hired',
    'contract': 'Contract',
    '10-day': '10-Day Contract',
    'two-way': 'Two-Way Contract',
    'free agent': 'Free Agent',
    'draft rights': 'Draft Rights',
    'renounced': 'Renounced',
    'exercised': 'Option Exercised',
    'declined': 'Option Declined',
    'waiver': 'Waiver',
    'buyout': 'Buyout',
    'amnestied': 'Amnestied',
}


def classify_transaction(text: str) -> str:
    """Classify transaction type from description text"""
    text_lower = text.lower()
    for keyword, label in TX_KEYWORDS.items():
        if keyword in text_lower:
            return label
    return 'Other'


def parse_date(date_str: str, year: int) -> str:
    """Parse BR date like 'April 12, 2026' → '2026-04-12'"""
    try:
        dt = datetime.strptime(date_str, '%B %d, %Y')
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        # Try without year
        try:
            dt = datetime.strptime(date_str + f', {year}', '%B %d, %Y')
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            return None


def extract_team_abbr(p_tag) -> str:
    """Extract team abbreviation from a <p> tag"""
    team_link = p_tag.find('a')
    if team_link:
        # Try data-attr-to or data-attr-from
        abbr = team_link.get('data-attr-to') or team_link.get('data-attr-from')
        if abbr:
            return abbr.upper()
        
        # Try team page URL: /teams/BRK/2026.html
        href = team_link.get('href', '')
        m = re.search(r'/teams/(\w+)/', href)
        if m:
            return m.group(1).upper()
        
        # Try full team name
        team_name = team_link.get_text(strip=True)
        if team_name in TEAM_NAME_MAP:
            return TEAM_NAME_MAP[team_name]
    
    return None


def fetch_with_playwright(url: str) -> str:
    """Fetch page HTML using Playwright Stealth to bypass Cloudflare."""
    import random
    import time as _time
    from playwright.sync_api import sync_playwright

    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    ]
    ua = random.choice(user_agents)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox',
                  '--disable-blink-features=AutomationControlled'],
        )
        context = browser.new_context(
            user_agent=ua,
            locale='en-US',
            viewport={'width': 1440, 'height': 900},
            extra_http_headers={
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            },
        )
        page = context.new_page()

        # Full stealth config (same as br_injuries_playwright.py)
        try:
            from playwright_stealth import Stealth
            stealth = Stealth(
                navigator_webdriver=True,
                webgl_vendor=True,
                chrome_app=True,
                chrome_csi=True,
                chrome_load_times=True,
                chrome_runtime=True,
                iframe_content_window=True,
                media_codecs=True,
                navigator_languages=True,
                navigator_permissions=True,
                navigator_plugins=True,
                navigator_hardware_concurrency=True,
                navigator_platform=True,
                navigator_user_agent=True,
                navigator_vendor=True,
                hairline=True,
                sec_ch_ua=True,
                error_prototype=True,
            )
            stealth.apply_stealth_sync(page)
        except ImportError:
            pass

        resp = page.goto(url, wait_until='domcontentloaded', timeout=30000)
        _time.sleep(3)

        # Cloudflare challenge detection
        title = page.title()
        if 'Just a moment' in title or 'Checking your browser' in title:
            print('  Cloudflare challenge detected, waiting 15s...')
            _time.sleep(15)
            page.reload(wait_until='domcontentloaded', timeout=30000)
            _time.sleep(5)
            title = page.title()
            if 'Just a moment' in title:
                print('  Cloudflare still blocking after reload')

        html = page.content()
        browser.close()
        return html


def scrape_season(year: int) -> list:
    """Scrape one season of transactions"""
    url = f'https://www.basketball-reference.com/leagues/NBA_{year}_transactions.html'
    print(f'Fetching: {url}')

    # Try curl_cffi first, fall back to Playwright
    html = None
    if HAS_CFFI:
        try:
            resp = cffi_requests.get(url, headers=HEADERS, timeout=30,
                                     impersonate="chrome124")
            if resp.status_code == 200:
                html = resp.text
                print(f'  curl_cffi: OK ({len(html)} chars)')
            else:
                print(f'  curl_cffi HTTP {resp.status_code}')
        except Exception as e:
            print(f'  curl_cffi error: {e}')

    if not html:
        print(f'  Falling back to Playwright...')
        try:
            html = fetch_with_playwright(url)
            print(f'  Playwright: OK ({len(html)} chars)')
        except Exception as e:
            print(f'  Playwright error: {e}')
            return []

    if not html:
        return []

    time.sleep(1)
    soup = BeautifulSoup(html, 'html.parser')
    
    # Find the transaction ul (the one with 100+ li elements)
    transactions = []
    for ul in soup.find_all('ul'):
        lis = ul.find_all('li')
        if len(lis) < 50:
            continue
        
        print(f'  Found {len(lis)} transaction dates')
        
        for li in lis:
            # Get date from span
            date_span = li.find('span')
            if not date_span:
                continue
            date_str = date_span.get_text(strip=True)
            parsed_date = parse_date(date_str, year)
            
            # Get each transaction p
            for p in li.find_all('p'):
                text = p.get_text(strip=True)
                if len(text) < 10:
                    continue
                
                team_abbr = extract_team_abbr(p)
                tx_type = classify_transaction(text)
                
                transactions.append({
                    'transaction_date': parsed_date,
                    'team_abbr': team_abbr,
                    'transaction_type': tx_type,
                    'description': text,
                    'source': 'basketball-reference.com',
                })
        
        break  # Only process the main transaction ul
    
    return transactions


def insert_transactions(conn, transactions: list, dry_run: bool = False):
    """Insert transactions into DB"""
    if dry_run:
        print(f'  [DRY RUN] Would insert {len(transactions)} rows')
        for t in transactions[:5]:
            print(f'    {t["transaction_date"]} | {t["team_abbr"]:4s} | {t["transaction_type"]:20s} | {t["description"][:80]}')
        return
    
    cur = conn.cursor()
    inserted = 0
    skipped = 0
    
    for t in transactions:
        if not t['transaction_date'] or not t['team_abbr']:
            skipped += 1
            continue
        
        try:
            cur.execute("""
                INSERT INTO transactions (transaction_date, team_abbr, transaction_type, description, source, created_at, crawl_date)
                VALUES (%s, %s, %s, %s, %s, NOW(), CURRENT_DATE)
                ON CONFLICT DO NOTHING
            """, (t['transaction_date'], t['team_abbr'], t['transaction_type'], 
                  t['description'], t['source']))
            inserted += 1
        except Exception as e:
            print(f'    DB Error: {e}')
            skipped += 1
    
    conn.commit()
    cur.close()
    print(f'  写入: {inserted}, 跳过: {skipped}')


def run_pipeline(years: list, dry_run: bool = False):
    """Main pipeline"""
    conn = psycopg2.connect(**DB_CONFIG)
    
    total = 0
    for year in years:
        transactions = scrape_season(year)
        insert_transactions(conn, transactions, dry_run)
        total += len(transactions)
    
    if not dry_run:
        print(f'\n总计 {total} 条交易入库')
    
    conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='BR 交易数据爬取')
    parser.add_argument('--year', type=int, nargs='+', required=True, help='赛季结束年 (如 2026 2025)')
    parser.add_argument('--dry-run', action='store_true', help='只测试不写库')
    args = parser.parse_args()
    
    run_pipeline(args.year, args.dry_run)
