#!/usr/bin/env python3
"""
2026 季后赛 + Play-In Play-by-Play 数据入库
=============================================
从 CDN PBP API 拉取逐回合数据，写入 play_by_play 表。

数据源: https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{10-digit-game-id}.json

用法:
    python crawler/ingest_2026_pbp.py
    python crawler/ingest_2026_pbp.py --dry-run
    python crawler/ingest_2026_pbp.py --include-regular  # 也重复拉取常规赛
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import random
import re
from datetime import datetime
from typing import Optional, List, Dict

import psycopg2
from psycopg2.extras import execute_batch
from curl_cffi import requests as cffi_requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("PBPIngest")

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}

CDN_PBP = "https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.nba.com/",
}

_last_req = 0.0
RATE_LIMIT = 1.2  # seconds between requests


def _wait():
    global _last_req
    elapsed = time.time() - _last_req
    if elapsed < RATE_LIMIT:
        time.sleep(RATE_LIMIT - elapsed + random.uniform(0, 0.2))
    _last_req = time.time()


def fetch_pbp(game_id_10: str) -> Optional[dict]:
    """Fetch CDN play-by-play JSON."""
    url = CDN_PBP.format(game_id=game_id_10)
    for attempt in range(4):
        try:
            _wait()
            resp = cffi_requests.get(url, headers=HEADERS, impersonate="chrome124", timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                actions = data.get("game", {}).get("actions", [])
                if actions:
                    return data
                logger.warning(f"  Empty actions for {game_id_10}")
                return None
            elif resp.status_code == 404:
                logger.warning(f"  404 Not found: {game_id_10}")
                return None
            elif resp.status_code == 403:
                delay = 4 * (2 ** attempt) + random.uniform(0, 3)
                logger.warning(f"  403 blocked for {game_id_10}, retry in {delay:.1f}s")
                time.sleep(delay)
            else:
                logger.warning(f"  HTTP {resp.status_code} for {game_id_10}")
                if attempt < 3:
                    time.sleep(3 * (2 ** attempt))
        except Exception as e:
            logger.warning(f"  Exception for {game_id_10}: {e}")
            if attempt < 3:
                time.sleep(3 * (2 ** attempt))
    return None


def _safe_int(v) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _safe_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _pt_to_seconds(pt_str: str) -> Optional[float]:
    """Convert PT12M00.00S to seconds."""
    if not pt_str:
        return None
    m = re.match(r"PT(\d+)M([\d.]+)S", pt_str)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    return None


def _pt_to_clock(pt_str: str) -> Optional[str]:
    """Convert PT12M00.00S to '12:00' format."""
    if not pt_str:
        return None
    m = re.match(r"PT(\d+)M([\d.]+)S", pt_str)
    if m:
        return f"{int(m.group(1)):02d}:{int(float(m.group(2))):02d}"
    return pt_str


def convert_actions(data: dict, game_id_8: str) -> List[Dict]:
    """Convert CDN PBP actions to play_by_play row format."""
    game = data.get("game", {})
    actions = game.get("actions", [])
    rows = []
    for a in actions:
        # Skip period start/end markers if they have no real content
        at = a.get("actionType", "")
        if at == "period" and a.get("subType", "") in ("start", "end"):
            continue

        score_home = _safe_int(a.get("scoreHome"))
        score_away = _safe_int(a.get("scoreAway"))

        row = {
            "gameid": game_id_8,
            "season": 2026,
            "eventnum": a.get("actionNumber"),
            "period": a.get("period"),
            "clock": _pt_to_clock(a.get("clock", "")),
            "clock_seconds": _pt_to_seconds(a.get("clock", "")),
            "h_pts": score_home,
            "a_pts": score_away,
            "team": a.get("teamTricode"),
            "playerid": a.get("personId") if a.get("personId") != 0 else None,
            "player": a.get("playerNameI") or a.get("playerName"),
            "event_type": at,
            "subtype": a.get("subType"),
            "result": (a.get("descriptor") or "")[:20],
            "x": _safe_int(a.get("x")) if a.get("x") is not None else None,
            "y": _safe_int(a.get("y")) if a.get("y") is not None else None,
            "dist": None,  # Can compute from x, y later
            "description": a.get("description"),
            "current_team": a.get("teamTricode"),
        }
        rows.append(row)
    return rows


def ingest_game(conn, game_id_8: str) -> int:
    """Fetch and insert PBP for one game. Returns number of rows inserted."""
    gid_10 = game_id_8.zfill(10)

    # Check if already in DB
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM play_by_play WHERE gameid = %s", (game_id_8,))
    existing = cur.fetchone()[0]
    if existing > 0:
        logger.info(f"  {gid_10}: already has {existing} events, skipping")
        return 0

    data = fetch_pbp(gid_10)
    if not data:
        return 0

    rows = convert_actions(data, game_id_8)
    if not rows:
        logger.warning(f"  {gid_10}: no actions after conversion")
        return 0

    # Insert in batches
    cur = conn.cursor()
    execute_batch(cur, """
        INSERT INTO play_by_play (
            gameid, season, eventnum, period, clock, clock_seconds,
            h_pts, a_pts, team, playerid, player,
            event_type, subtype, result, x, y, dist, description, current_team
        ) VALUES (
            %(gameid)s, %(season)s, %(eventnum)s, %(period)s, %(clock)s, %(clock_seconds)s,
            %(h_pts)s, %(a_pts)s, %(team)s, %(playerid)s, %(player)s,
            %(event_type)s, %(subtype)s, %(result)s, %(x)s, %(y)s, %(dist)s, %(description)s, %(current_team)s
        )
    """, rows, page_size=100)
    conn.commit()
    return len(rows)


def get_missing_games(conn, include_regular: bool = False) -> list:
    """Find 2026 games that need PBP data."""
    cur = conn.cursor()
    if include_regular:
        cur.execute("""
            SELECT g.game_id FROM games g
            WHERE g.season = 2026
              AND NOT EXISTS (SELECT 1 FROM play_by_play p WHERE p.gameid = g.game_id)
            ORDER BY g.game_date, g.game_id
        """)
    else:
        cur.execute("""
            SELECT g.game_id FROM games g
            WHERE g.season = 2026
              AND g.season_type IN ('Playoffs', 'Play-In')
              AND NOT EXISTS (SELECT 1 FROM play_by_play p WHERE p.gameid = g.game_id)
            ORDER BY g.game_date, g.game_id
        """)
    return [r[0] for r in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser(description="Ingest 2026 NBA play-by-play data")
    parser.add_argument("--dry-run", action="store_true", help="Print only, no DB writes")
    parser.add_argument("--limit", type=int, default=200, help="Max games to process")
    parser.add_argument("--include-regular", action="store_true", help="Also re-ingest regular season")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)

    games = get_missing_games(conn, include_regular=args.include_regular)
    if args.limit:
        games = games[:args.limit]

    if not games:
        logger.info("All games already have PBP data!")
        conn.close()
        return

    logger.info(f"Found {len(games)} games needing PBP data")
    success = skipped = failed = 0
    total_rows = 0
    start_time = time.time()

    for i, gid_8 in enumerate(games):
        gid_10 = gid_8.zfill(10)
        try:
            if args.dry_run:
                logger.info(f"  [DRY RUN] Would fetch PBP for: {gid_10}")
                success += 1
                continue

            n = ingest_game(conn, gid_8)
            if n > 0:
                logger.info(f"  [{i+1}/{len(games)}] {gid_10}: {n} events")
                success += 1
                total_rows += n
            else:
                skipped += 1

        except Exception as e:
            logger.error(f"  Error on {gid_10}: {e}")
            conn.rollback()
            failed += 1

        if (i + 1) % 15 == 0:
            elapsed = max(time.time() - start_time, 1)
            rate = (i + 1) / elapsed * 60  # games per minute
            remaining = len(games) - i - 1
            eta = remaining / rate if rate > 0 else 0
            logger.info(
                f"  Progress: {i+1}/{len(games)} | "
                f"OK={success} skip={skipped} fail={failed} | "
                f"{rate:.1f} g/min | ETA={eta:.0f}min"
            )

    elapsed = time.time() - start_time
    logger.info(f"\n{'='*60}")
    logger.info(f"DONE: {success} success, {skipped} skipped, {failed} failed")
    logger.info(f"Total rows inserted: {total_rows}")
    logger.info(f"Time: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    logger.info(f"{'='*60}")

    conn.close()


if __name__ == "__main__":
    main()
