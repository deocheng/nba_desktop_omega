#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backfill game_date for 2020-2023 seasons.
==========================================
Fetches NBA schedule from data.nba.com, matches by game_id, updates games table.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import logging
import time
import psycopg2
from curl_cffi import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("BackfillDates")

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}

SCHEDULE_URL = "https://data.nba.com/data/10s/v2015/json/mobile_teams/nba/{year}/league/00_full_schedule.json"
HEADERS = {
    "Accept": "application/json",
    "Referer": "https://www.nba.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


def fetch_schedule(year: int) -> dict:
    """Fetch NBA full schedule for a season starting in {year}."""
    url = SCHEDULE_URL.format(year=year)
    resp = requests.get(url, headers=HEADERS, impersonate="chrome124", timeout=25)
    resp.raise_for_status()
    return resp.json()


def extract_game_dates(schedule_json: dict) -> dict:
    """Extract {game_id_10: date} from schedule."""
    dates = {}
    for month_data in schedule_json.get("lscd", []):
        mscd = month_data.get("mscd", {})
        for game in mscd.get("g", []):
            gid = game.get("gid", "")  # 10-digit like "0022200547"
            gdte = game.get("gdte", "")
            if gid and gdte:
                dates[gid] = gdte
    return dates


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    seasons = [
        (2015, 2016),  # 2015-16
        (2016, 2017),  # 2016-17
        (2017, 2018),  # 2017-18
        (2018, 2019),  # 2018-19
        (2019, 2020),  # 2019-20
        (2020, 2021),  # 2020-21
        (2021, 2022),  # 2021-22
        (2022, 2023),  # 2022-23
    ]

    total_updated = 0

    for start_year, season_id in seasons:
        logger.info(f"Processing season {start_year}-{start_year+1} (season={season_id})...")

        # Check how many need dates
        cur.execute("SELECT COUNT(*) FROM games WHERE season = %s AND game_date IS NULL", (season_id,))
        missing = cur.fetchone()[0]
        if missing == 0:
            logger.info(f"  No missing dates, skipping")
            continue
        logger.info(f"  {missing} games need dates")

        # Fetch schedule
        try:
            schedule = fetch_schedule(start_year)
            game_dates = extract_game_dates(schedule)
            logger.info(f"  Schedule has {len(game_dates)} games")
        except Exception as e:
            logger.error(f"  Failed to fetch schedule: {e}")
            continue

        # Get our game IDs that need dates
        cur.execute("SELECT game_id FROM games WHERE season = %s AND game_date IS NULL", (season_id,))
        our_games = cur.fetchall()

        updated = 0
        for (gid_8,) in our_games:
            # Convert 8-digit to 10-digit for matching
            gid_10 = str(gid_8).zfill(10)
            if gid_10 in game_dates:
                cur.execute(
                    "UPDATE games SET game_date = %s WHERE game_id = %s AND game_date IS NULL",
                    (game_dates[gid_10], gid_8)
                )
                updated += cur.rowcount

        conn.commit()
        logger.info(f"  Updated {updated}/{missing} game dates")
        total_updated += updated
        time.sleep(1)  # rate limit between seasons

    logger.info(f"\nTotal game dates backfilled: {total_updated}")

    # Verify
    cur.execute("SELECT season, COUNT(*) FROM games WHERE game_date IS NULL GROUP BY season ORDER BY season")
    remaining = cur.fetchall()
    if remaining:
        logger.info("Remaining missing dates:")
        for r in remaining:
            logger.info(f"  season {r[0]}: {r[1]} games")
    else:
        logger.info("All games have dates now!")

    conn.close()


if __name__ == "__main__":
    main()
