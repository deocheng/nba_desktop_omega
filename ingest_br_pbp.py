#!/usr/bin/env python3
"""
Ingest play-by-play for 2026 Regular Season games that lack nba_api_id,
directly from Basketball-Reference PBP pages.

Why BR (primary) and not cdn.nba.com (secondary):
  cdn.nba.com / stats.nba.com are currently blocked (HTTP 403 / timeout),
  so the existing curl_cffi PBP pipeline cannot fetch new games.  BR boxscore
  PBP pages (/boxscores/pbp/{game_id}.html) ARE reachable via the crawler
  browser and contain the full event log.

Keying:
  Rows are inserted with `gameid` = the BR game_id (e.g. '202511010IND').
  The app's data_layer._resolve_join_key() returns the BR game_id itself when
  games.nba_api_id is NULL, so these rows join correctly without any migration
  of the existing (nba_api-keyed) PBP rows.

Parsing (see br_pbp_parse.py):
  We keep THREE separate signals so the verb is never discarded:
    * player      -> clean name only
    * action_verb -> the action word (makes/misses/rebound/enters/...)
    * subtype     -> finer action detail (2-pt jump shot / Offensive rebound)

Usage:
  python ingest_br_pbp.py                 # full run (291 gap games)
  python ingest_br_pbp.py --limit 5       # process only 5 games (smoke test)
  python ingest_br_pbp.py --dry-run       # parse only, no DB writes
  python ingest_br_pbp.py --rate-per-min 15   # hard cap on BR requests/min (default 15)
  python ingest_br_pbp.py --ids-file gaps.tsv # crawl ONLY the listed game ids

IMPORTANT — BR rate limit:
  Basketball-Reference will serve a Cloudflare challenge / soft-block if we hit
  it too hard. User mandate: never exceed 15 requests/minute. The default
  min-interval is 4.5s (≈13/min, safely under the cap) and a rolling 60s window
  hard-caps at --rate-per-min (default 15). Running faster than this is what
  previously got us flagged.
"""
from __future__ import annotations

import sys
import os
import time
import atexit
import logging

# --- path setup (mirrors test_br_pbp.py which worked) ---
CRAWLER_DIR = r'C:/autopick/AutoPick/nba_data'
sys.path.insert(0, CRAWLER_DIR)
os.chdir(CRAWLER_DIR)

from backend.core import config  # works: script dir (omega) is on sys.path[0]
from nba_daily_crawler import BrowserManager, CrawlLogger
from br_pbp_parse import parse_pbp, SEASON
import psycopg2
from psycopg2.extras import execute_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("BRPBP")

DB_CONFIG = config.DB_CONFIG

INSERT_SQL = """
    INSERT INTO play_by_play (
        gameid, season, eventnum, period, clock, clock_seconds,
        h_pts, a_pts, team, playerid, player,
        event_type, subtype, action_verb, result, x, y, dist, description, current_team,
        homedescription, visitordescription, neutraldescription,
        scorehome, scorevisitor, scoremargin, source
    ) VALUES (
        %(gameid)s, %(season)s, %(eventnum)s, %(period)s, %(clock)s, %(clock_seconds)s,
        %(h_pts)s, %(a_pts)s, %(team)s, %(playerid)s, %(player)s,
        %(event_type)s, %(subtype)s, %(action_verb)s, %(result)s, %(x)s, %(y)s, %(dist)s, %(description)s, %(current_team)s,
        %(homedescription)s, %(visitordescription)s, %(neutraldescription)s,
        %(scorehome)s, %(scorevisitor)s, %(scoremargin)s, %(source)s
    )
"""


# --------------------------------------------------------------------------
# Rate limiter — never hammer Basketball-Reference
# --------------------------------------------------------------------------
DEFAULT_RATE_PER_MINUTE = 15


class RateLimiter:
    """Hard cap on outbound Basketball-Reference requests.

    Enforces BOTH a minimum interval between requests AND a rolling
    max-per-minute window, so we never exceed the user-mandated
    15 requests/minute (and stay safely under it with a 4.5s floor).
    """

    def __init__(self, max_per_minute=DEFAULT_RATE_PER_MINUTE, min_interval=4.5):
        self.max_per_minute = max(1, int(max_per_minute))
        self.min_interval = max(1.0, float(min_interval))
        self._times = []
        self._last = 0.0

    def wait(self):
        now = time.time()
        sleep_for = 0.0
        since_last = now - self._last
        if since_last < self.min_interval:
            sleep_for = self.min_interval - since_last
        cutoff = now - 60.0
        self._times = [t for t in self._times if t > cutoff]
        if len(self._times) >= self.max_per_minute:
            sleep_for = max(sleep_for, self._times[0] + 60.0 - now)
        if sleep_for > 0:
            logger.info(f"  [rate-limit] sleeping {sleep_for:.1f}s to stay <= {self.max_per_minute}/min")
            time.sleep(sleep_for)
        now = time.time()
        self._times.append(now)
        self._last = now


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------
def fetch_pbp(browser, br_id):
    url = f"https://www.basketball-reference.com/boxscores/pbp/{br_id}.html"
    soup = browser.fetch_soup(url)
    if soup is None:
        return None
    tbl = soup.find('table', id='pbp') or soup.find('table', id=lambda x: x and 'pbp' in x.lower())
    if tbl is None:
        return None
    return soup


def main():
    dry = '--dry-run' in sys.argv
    limit = None
    ids_file = None
    rate_per_min = DEFAULT_RATE_PER_MINUTE
    for i, a in enumerate(sys.argv):
        if a == '--limit':
            try:
                limit = int(sys.argv[i + 1])
            except (IndexError, ValueError):
                pass
        elif a.startswith('--limit='):
            try:
                limit = int(a.split('=')[1])
            except ValueError:
                pass
        elif a == '--rate-per-min':
            try:
                rate_per_min = int(sys.argv[i + 1])
            except (IndexError, ValueError):
                pass
        elif a.startswith('--rate-per-min='):
            try:
                rate_per_min = int(a.split('=')[1])
            except ValueError:
                pass
        elif a == '--ids-file':
            try:
                ids_file = sys.argv[i + 1]
            except IndexError:
                ids_file = None
        elif a.startswith('--ids-file='):
            ids_file = a.split('=', 1)[1]

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    if ids_file:
        # Targeted backfill: read (gameid, br_id, away, home) rows from a TSV
        # so we crawl ONLY the games listed (e.g. the 241 RS gaps from TASK A),
        # instead of re-scanning every 2026 RS game with nba_api_id IS NULL.
        # Expected columns: ds, away, home, br_id, join_key
        #   br_id    -> basketball-reference URL id (col 4)
        #   join_key -> play_by_play.gameid, the BR game_id (col 5)
        games = []
        with open(ids_file, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.rstrip('\n')
                if not line or line.startswith('#'):
                    continue
                cols = line.split('\t')
                if len(cols) >= 5:
                    gid, br = cols[4].strip(), cols[3].strip()
                    away, home = cols[1].strip(), cols[2].strip()
                elif len(cols) >= 4:
                    gid = br = cols[3].strip()
                    away = home = ''
                else:
                    continue
                if gid:
                    games.append((gid, br, away, home))
        logger.info(f"Targeted run: loaded {len(games)} game ids from {ids_file}")
    else:
        cur.execute("""
            SELECT game_id, br_crawled_id, away_team_abbr, home_team_abbr
            FROM games
            WHERE season=%s AND season_type='Regular Season' AND nba_api_id IS NULL
            ORDER BY game_date, game_id
        """, (SEASON,))
        games = cur.fetchall()
        logger.info(f"Gap games (2026 RS, no nba_api_id): {len(games)}")

    if limit:
        games = games[:limit]
        logger.info(f"Limiting to {limit} games")

    # 单浏览器会话：整批 291 场共用这一个 driver，CF 通过一次后全程复用，
    # 循环里绝不 quit/重开（对齐'CF通过后不要频繁关闭重开浏览器'的要求）。
    # BrowserManager 已在 start() 内注入持久化 cookie，可跳过重新挑战。
    browser = BrowserManager(CrawlLogger())
    browser.start()
    atexit.register(browser.quit)  # 异常退出也回收浏览器，避免孤儿进程

    # BR 速率硬上限：默认 15/min（实际 4.5s 间隔 ≈13/min，留安全余量）。
    # 这是用户明确要求，超出会触发 CF 挑战/封禁。
    limiter = RateLimiter(max_per_minute=rate_per_min)
    logger.info(f"BR rate limiter active: max {rate_per_min}/min (min interval 4.5s)")

    total_events = 0
    ok = failed = 0
    try:
        for gid, br, away, home in games:
            br_id = br or gid
            limiter.wait()  # 严格遵守 ≤15 BR 请求/分钟
            soup = fetch_pbp(browser, br_id)
            if soup is None:
                logger.warning(f"  {br_id}: no PBP page/soup, skipping")
                failed += 1
                continue
            rows = parse_pbp(soup, away, home, gid)
            if not rows:
                logger.warning(f"  {br_id}: parsed 0 events, skipping")
                failed += 1
                continue
            if dry:
                logger.info(f"  [DRY] {br_id}: {len(rows)} events")
                total_events += len(rows)
                ok += 1
                continue
            # idempotent: clear any prior BR-keyed rows for this game
            cur.execute("DELETE FROM play_by_play WHERE gameid=%s", (gid,))
            execute_batch(cur, INSERT_SQL, rows, page_size=200)
            conn.commit()
            total_events += len(rows)
            ok += 1
            logger.info(f"  {br_id}: {len(rows)} events  (cum {total_events})")
            # 速率由 limiter.wait() 在下一轮循环开头统一控制，这里不再 sleep
    finally:
        browser.quit()
        conn.close()

    logger.info(f"DONE: ok={ok} failed={failed} total_events={total_events}")


if __name__ == "__main__":
    main()
