"""Feasibility: fetch a BR PBP page via crawler browser; inspect table + nba_api_id."""
from __future__ import annotations
import sys, os, re
sys.path.insert(0, r'C:/autopick/AutoPick/nba_data')
os.chdir(r'C:/autopick/AutoPick/nba_data')
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.core import config
from nba_daily_crawler import BrowserManager, CrawlLogger

# get one BR game_id from the 291 gap games
conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)
cur = conn.cursor()
cur.execute("""SELECT br_crawled_id, game_id, game_date, home_team_abbr, away_team_abbr
FROM games WHERE season=2026 AND season_type='Regular Season'
AND nba_api_id IS NULL AND br_crawled_id IS NOT NULL LIMIT 3""")
samples = cur.fetchall()
conn.close()
print("gap samples:", [(s['br_crawled_id'], s['game_date']) for s in samples])
if not samples:
    print("NO sample with br_crawled_id — pick any 2026 RS game")
    sys.exit(1)

gid = samples[0]['br_crawled_id']
print("using BR game_id:", gid)

browser = BrowserManager(CrawlLogger())
browser.start()
url = f"https://www.basketball-reference.com/boxscores/pbp/{gid}.html"
print("fetch:", url)
soup = browser.fetch_soup(url)
print("soup obtained:", soup is not None)
if soup:
    tbl = soup.find('table', id=lambda x: x and 'pbp' in x.lower())
    print("PBP table found:", tbl is not None, "->", getattr(tbl, 'get', lambda k:None)('id') if tbl else None)
    text = soup.get_text()
    ids = sorted(set(re.findall(r'002\d{8}', text)))
    print("10-digit nba ids in page text:", ids[:5], "(total", len(ids), ")")
    # also search raw html for data-game-id
    raw = str(soup)
    dg = re.findall(r'data-game-id["\s:=]+["\']?(\d{10})', raw)
    print("data-game-id matches:", dg[:5])
    with open('br_pbp_sample.html', 'w', encoding='utf-8') as f:
        f.write(raw)
    print("saved br_pbp_sample.html (bytes=%d)" % len(raw))
else:
    print("FAILED to get soup")
browser.quit()
