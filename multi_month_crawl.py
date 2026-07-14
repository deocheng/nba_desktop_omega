"""Multi-month crawler - one browser session, crawl many months.

Usage:
    python multi_month_crawl.py 2025-10 2025-11 2025-12 2026-01 2026-02
"""
from __future__ import annotations

import sys
import os
import time
import re
from datetime import datetime, date

CRAWLER_DIR = r'C:/autopick/AutoPick/nba_data'
sys.path.insert(0, CRAWLER_DIR)
os.chdir(CRAWLER_DIR)

from nba_daily_crawler import (
    BrowserManager, CrawlLogger, Config,
    get_season_for_date, to_int, extract_db_abbr_from_cell,
)
import psycopg2


def crawl_month(browser, logger, conn, year: int, month: int) -> tuple[int, int, list]:
    target = date(year, month, 1)
    season = get_season_for_date(target)
    month_name = target.strftime('%B').lower()
    url = f'{Config.BASE_URL}/leagues/NBA_{season}_games-{month_name}.html'

    logger.info(f'=== Crawling games: {year}-{month:02d} ===')

    soup = browser.fetch_soup(url)
    if soup is None:
        return 0, 0, ['fetch failed']

    table = soup.find('table', id='schedule')
    if not table:
        return 0, 0, ['schedule table not found']

    imported = 0
    skipped = 0
    errors = []

    cur = conn.cursor()
    tbody = table.find('tbody')
    if not tbody:
        return 0, 0, ['no tbody']

    for tr in tbody.find_all('tr'):
        if tr.get('class') and 'over_header' in tr.get('class', []):
            continue

        cell_map = {}
        visitor_cell = None
        home_cell = None
        for cell in tr.find_all(['td', 'th']):
            stat = cell.get('data-stat', '')
            if stat:
                cell_map[stat] = cell.get_text(strip=True)
                if stat == 'visitor_team_name':
                    visitor_cell = cell
                elif stat == 'home_team_name':
                    home_cell = cell

        game_date_str = cell_map.get('date_game', '')
        if not game_date_str:
            continue

        game_date = None
        for fmt in ['%a, %b %d, %Y', '%Y-%m-%d']:
            try:
                game_date = datetime.strptime(game_date_str, fmt).strftime('%Y-%m-%d')
                break
            except ValueError:
                continue

        if game_date is None:
            continue

        boxscore_link = tr.find(
            'a', href=lambda x: x and re.search(
                r'/boxscores/\d{8,}[A-Z]{3}\.html$', x))
        boxscore_url = ''
        game_id = ''
        if boxscore_link:
            boxscore_url = boxscore_link['href']
            game_id = boxscore_url.split('/')[-1].replace('.html', '')

        if not game_id:
            continue

        away_team_abbr = extract_db_abbr_from_cell(visitor_cell)
        away_pts = to_int(cell_map.get('visitor_pts'))
        home_team_abbr = extract_db_abbr_from_cell(home_cell)
        home_pts = to_int(cell_map.get('home_pts'))

        cur.execute(
            "SELECT game_id, nba_api_id FROM games "
            "WHERE game_date = %s AND home_team_abbr = %s "
            "AND away_team_abbr = %s",
            (game_date, home_team_abbr, away_team_abbr))
        row = cur.fetchone()
        if row:
            try:
                cur.execute(
                    "UPDATE games SET game_id = %s, boxscore_url = %s, "
                    "br_crawled_id = %s "
                    "WHERE game_date = %s AND home_team_abbr = %s "
                    "AND away_team_abbr = %s",
                    (game_id, boxscore_url, game_id, game_date,
                     home_team_abbr, away_team_abbr))
                skipped += 1
            except Exception as e:
                errors.append(f'{game_id}: {str(e)[:60]}')
                conn.rollback()
        else:
            try:
                cur.execute(
                    "INSERT INTO games "
                    "(game_id, game_date, season, season_type, "
                    "away_team_abbr, home_team_abbr, away_pts, home_pts, "
                    "boxscore_url, br_crawled_id, source) "
                    "VALUES (%s, %s, %s, 'Regular Season', %s, %s, %s, %s, "
                    "%s, %s, 'BBRef')",
                    (game_id, game_date, season,
                     away_team_abbr, home_team_abbr, away_pts, home_pts,
                     boxscore_url, game_id))
                imported += 1
            except Exception as e:
                errors.append(f'{game_id}: {str(e)[:60]}')
                conn.rollback()

    conn.commit()
    cur.close()

    logger.info(f'  Done: imported={imported}, updated={skipped}, errors={len(errors)}')
    return imported, skipped, errors


def main():
    months = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not months:
        print("Usage: python multi_month_crawl.py YYYY-MM [YYYY-MM ...]")
        print("Example: python multi_month_crawl.py 2025-10 2025-11 2025-12")
        sys.exit(1)

    logger = CrawlLogger()
    browser = BrowserManager(logger)
    conn = psycopg2.connect(
        host=Config.DB_HOST, port=Config.DB_PORT, dbname=Config.DB_NAME,
        user=Config.DB_USER, password=Config.DB_PASSWORD)

    try:
        browser.start()
        total_imported = 0
        total_skipped = 0

        for i, month_str in enumerate(months):
            try:
                y, m = map(int, month_str.split('-'))
            except ValueError:
                logger.error(f'Invalid month: {month_str}, skipping')
                continue

            logger.info(f'--- [{i+1}/{len(months)}] {month_str} ---')

            try:
                imp, skip, errs = crawl_month(browser, logger, conn, y, m)
                total_imported += imp
                total_skipped += skip
                if errs:
                    for e in errs[:5]:
                        logger.error(f'  ERROR: {e}')
            except Exception as e:
                logger.error(f'Error crawling {month_str}: {e}')
                import traceback
                traceback.print_exc()

            if i < len(months) - 1:
                time.sleep(3)

        logger.info(f'\n=== All done ===')
        logger.info(f'Total imported: {total_imported}')
        logger.info(f'Total updated: {total_skipped}')

    finally:
        browser.quit()
        conn.close()


if __name__ == '__main__':
    main()
