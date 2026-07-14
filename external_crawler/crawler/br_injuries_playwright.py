"""
BR 伤病数据爬虫 — Playwright Stealth 版本
绕过 Cloudflare 反爬，爬取 basketball-reference.com/friv/injuries.fcgi
"""
import time
import re
import random
import logging
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("br_injuries_pw")

DB_CONFIG = {
    'host': 'localhost', 'port': 5433,
    'dbname': 'nba', 'user': 'postgres', 'password': 'postgres'
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


def fetch_injuries_page():
    """Playwright + playwright_stealth 获取伤病页面 HTML"""
    from playwright_stealth import Stealth

    ua = random.choice(USER_AGENTS)
    url = "https://www.basketball-reference.com/friv/injuries.fcgi"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
            ],
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

        # playwright_stealth 全量注入（含 chrome_runtime, navigator_webdriver 等 20+ 项绕过）
        stealth_config = Stealth(
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
        stealth_config.apply_stealth_sync(page)

        logger.info(f"导航到: {url}")

        resp = page.goto(url, wait_until='domcontentloaded', timeout=30000)
        logger.info(f"HTTP Status: {resp.status}")

        # 检测 Cloudflare challenge
        time.sleep(3)
        cf = page.evaluate("""
            () => document.body.innerText.includes('Checking your browser') ||
                 document.body.innerText.includes('Just a moment')
        """)
        if cf:
            logger.info("检测到 Cloudflare 挑战，额外等待 15s...")
            time.sleep(15)

        # 等待表格出现或重新检查
        page_title = page.title()
        if 'Just a moment' in page_title:
            logger.error("Cloudflare 拦截未通过，尝试 reload...")
            page.reload(wait_until='domcontentloaded', timeout=30000)
            time.sleep(5)

        try:
            page.wait_for_selector('#injuries tbody tr', timeout=15000)
            logger.info("伤病表格加载完成")
        except Exception as e:
            logger.warning(f"等待表格超时: {e}")

        html = page.content()
        logger.info(f"获取 HTML: {len(html)} 字符")
        browser.close()
        return html


def parse_and_store(html, conn):
    """解析伤病表格并写入数据库"""
    soup = BeautifulSoup(html, 'lxml')
    table = soup.find('table', id='injuries')

    if not table:
        logger.error("未找到伤病表格")
        return 0

    rows = []
    scraped_at = datetime.now()
    source_url = "https://www.basketball-reference.com/friv/injuries.fcgi"

    tbody = table.find('tbody')
    if not tbody:
        logger.error("表格无 tbody")
        return 0

    for tr in tbody.find_all('tr'):
        th = tr.find('th', {'data-stat': 'player'})
        if not th:
            continue
        a = th.find('a')
        player_name = a.get_text(strip=True) if a else th.get_text(strip=True)

        # 跳过表头伪装行（无链接、名为 "Player"）
        if not a or player_name == 'Player':
            continue

        # team_abbr 从 <a href="/teams/BRK/2026.html"> 中提取
        td_team = tr.find('td', {'data-stat': 'team_name'})
        team_abbr = ''
        if td_team:
            team_link = td_team.find('a')
            if team_link and team_link.get('href'):
                # /teams/BRK/2026.html → BRK
                m2 = re.search(r'/teams/(\w+)/', team_link['href'])
                if m2:
                    team_abbr = m2.group(1)

        td_date = tr.find('td', {'data-stat': 'date_update'})
        update_date_raw = td_date.get_text(strip=True) if td_date else ''

        # BR 页面实际 data-stat="note"
        td_note = tr.find('td', {'data-stat': 'note'})
        description = td_note.get_text(strip=True) if td_note else ''

        # 解析: "Out For Season (Foot) - ..." → status="Out For Season"
        status = None
        m = re.match(r'^(.+?)\s*\((.+?)\)', description)
        if m:
            status = m.group(1).strip()

        # 解析日期
        update_date = datetime.now().date()
        if update_date_raw:
            try:
                from dateutil import parser as dtparser
                update_date = dtparser.parse(update_date_raw).date()
            except Exception:
                try:
                    update_date = datetime.strptime(update_date_raw, '%a, %b %d, %Y').date()
                except Exception:
                    pass

        # 适配 injuries 表结构: report_date, player_name, team_abbr, injury, status, source, created_at, crawl_date
        rows.append((
            update_date, player_name, team_abbr, description, status,
            source_url, scraped_at, scraped_at.date()
        ))

    # Upsert: 如果已有 (report_date, player_name, team_abbr) 则更新状态，否则插入
    cur = conn.cursor()
    if rows:
        execute_values(cur, """
            INSERT INTO injuries (report_date, player_name, team_abbr, injury, status, source, created_at, crawl_date)
            VALUES %s
            ON CONFLICT (report_date, player_name, team_abbr) DO UPDATE SET
                injury = EXCLUDED.injury,
                status = EXCLUDED.status,
                source = EXCLUDED.source,
                created_at = EXCLUDED.created_at,
                crawl_date = EXCLUDED.crawl_date
        """, rows)
    conn.commit()
    cur.close()

    logger.info(f"伤病数据写入完成: {len(rows)} 条")
    return len(rows)


def main():
    start = time.time()

    # Step 1: Playwright 获取页面
    logger.info("=" * 60)
    logger.info("[Step 1/2] Playwright Stealth 爬取伤病页面")
    logger.info("=" * 60)
    html = fetch_injuries_page()

    # Step 2: 解析入库
    logger.info("=" * 60)
    logger.info("[Step 2/2] 解析并写入数据库")
    logger.info("=" * 60)
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        count = parse_and_store(html, conn)
    finally:
        conn.close()

    elapsed = time.time() - start
    logger.info("=" * 60)
    logger.info(f"完成! 伤病记录: {count} 条, 耗时: {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
