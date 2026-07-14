#!/usr/bin/env python3
"""
2026赛季季后赛 + Play-In 数据入库
=====================================
从 NBA CDN scheduleLeagueV2.json 提取 2025-26赛季季后赛/Play-In 比赛信息，
入库到 games 表，然后运行 ingest_nba_api.py 补全球员统计数据。

用法:
    python crawler/import_2026_playoffs.py
    python crawler/import_2026_playoffs.py --dry-run
    python crawler/import_2026_playoffs.py --ingest   # 入库完后自动跑 ingest
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import psycopg2
from curl_cffi import requests as cffi_requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("PlayoffImport")

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}

CDN_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.nba.com/",
}

# Game ID prefixes for 2025-26 season
PLAYOFF_PREFIX = "0042500"     # Regular playoffs
PLAYIN_PREFIX  = "0052500"     # Play-In tournament
PRESEASON_PREFIX = "0012500"   # Preseason (skip)


def fetch_schedule() -> list[dict]:
    """Download CDN schedule and return list of all playoff/playin games."""
    logger.info(f"Fetching CDN schedule from {CDN_URL}")
    resp = cffi_requests.get(CDN_URL, headers=HEADERS, impersonate="chrome124", timeout=60)
    resp.raise_for_status()
    data = resp.json()
    
    game_dates = data["leagueSchedule"]["gameDates"]
    
    all_games = []
    for gd in game_dates:
        for g in gd.get("games", []):
            gid = g.get("gameId", "")
            if gid.startswith("004") or gid.startswith("005"):
                all_games.append(g)
    
    logger.info(f"Found {len(all_games)} playoff/playin games in CDN schedule")
    return all_games


def get_season_type(game_id: str) -> str:
    """Determine season_type from game_id prefix."""
    if game_id.startswith("0042"):
        return "Playoffs"
    elif game_id.startswith("0052"):
        return "Play-In"
    return "Unknown"


def get_team_mapping(conn) -> dict[str, str]:
    """Get team_id → abbr mapping from DB."""
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT home_team_id, home_team_abbr FROM games WHERE home_team_id IS NOT NULL")
    mapping = {str(r[0]): r[1] for r in cur.fetchall() if r[1]}
    return mapping


def parse_game(g: dict, team_mapping: dict) -> dict | None:
    """Parse CDN game object into games table row dict."""
    gid = g.get("gameId", "")
    if not gid:
        return None

    # game_id format: strip leading zeros → 8-digit for consistency
    # But this is 10-digit (0042500xxx), keep as-is (games table uses text)
    # Strip leading "00" → 8-digit
    gid_8 = gid.lstrip("0") or "0"

    # Parse date (gameDateEst like "2026-04-18T00:00:00Z")
    try:
        game_date = g.get("gameDateEst", "")[:10]  # "2026-04-18"
    except Exception:
        game_date = None

    home = g.get("homeTeam", {})
    away = g.get("awayTeam", {})

    home_tid = str(home.get("teamId", ""))
    away_tid = str(away.get("teamId", ""))

    home_abbr = home.get("teamTricode", team_mapping.get(home_tid, ""))
    away_abbr = away.get("teamTricode", team_mapping.get(away_tid, ""))
    home_name = f"{home.get('teamCity','')} {home.get('teamName','')}".strip()
    away_name = f"{away.get('teamCity','')} {away.get('teamName','')}".strip()

    home_pts = home.get("score")
    away_pts = away.get("score")
    
    # Only accept Final games (gameStatus==3)
    if g.get("gameStatus") != 3:
        return None

    season_type = get_season_type(gid)

    return {
        "game_id": gid_8,
        "game_date": game_date,
        "season": 2026,
        "season_type": season_type,
        "home_team_id": home_tid,
        "home_team_abbr": home_abbr,
        "home_team_name": home_name,
        "home_pts": int(home_pts) if home_pts is not None else None,
        "away_team_id": away_tid,
        "away_team_abbr": away_abbr,
        "away_team_name": away_name,
        "away_pts": int(away_pts) if away_pts is not None else None,
    }


def upsert_games(conn, rows: list[dict], dry_run: bool = False) -> int:
    """Insert playoff games into games table. Returns count inserted."""
    if not rows:
        return 0

    if dry_run:
        for r in rows[:5]:
            logger.info(f"  [DRY RUN] {r['game_id']} {r['game_date']} "
                        f"{r['away_team_abbr']}({r['away_pts']}) @ "
                        f"{r['home_team_abbr']}({r['home_pts']}) [{r['season_type']}]")
        logger.info(f"[DRY RUN] Would insert {len(rows)} rows total")
        return len(rows)

    cur = conn.cursor()
    inserted = 0
    skipped = 0

    for r in rows:
        try:
            cur.execute("""
                INSERT INTO games (
                    game_id, game_date, season, season_type,
                    home_team_id, home_team_abbr, home_team_name, home_pts,
                    away_team_id, away_team_abbr, away_team_name, away_pts
                ) VALUES (
                    %(game_id)s, %(game_date)s, %(season)s, %(season_type)s,
                    %(home_team_id)s, %(home_team_abbr)s, %(home_team_name)s, %(home_pts)s,
                    %(away_team_id)s, %(away_team_abbr)s, %(away_team_name)s, %(away_pts)s
                )
                ON CONFLICT (game_id) DO UPDATE SET
                    game_date = EXCLUDED.game_date,
                    season_type = EXCLUDED.season_type,
                    home_pts = COALESCE(EXCLUDED.home_pts, games.home_pts),
                    away_pts = COALESCE(EXCLUDED.away_pts, games.away_pts)
            """, r)
            inserted += 1
        except Exception as e:
            logger.error(f"Error inserting {r['game_id']}: {e}")
            conn.rollback()
            skipped += 1
            continue

    conn.commit()
    logger.info(f"Inserted/updated: {inserted}, skipped: {skipped}")
    return inserted


def verify_insert(conn):
    """Verify the inserted data."""
    cur = conn.cursor()
    cur.execute("""
        SELECT season_type, COUNT(*), 
               MIN(game_date), MAX(game_date),
               COUNT(CASE WHEN home_pts IS NOT NULL THEN 1 END) as with_score
        FROM games 
        WHERE season=2026 AND season_type IN ('Playoffs', 'Play-In')
        GROUP BY season_type
        ORDER BY season_type
    """)
    rows = cur.fetchall()
    logger.info("=== Verification ===")
    for r in rows:
        logger.info(f"  {r[0]}: {r[1]} games ({r[4]} with scores), {r[2]} to {r[3]}")


def main():
    parser = argparse.ArgumentParser(description="Import 2026 NBA playoff data")
    parser.add_argument("--dry-run", action="store_true", help="Print only, don't write DB")
    parser.add_argument("--ingest", action="store_true", help="Run ingest_nba_api.py after import")
    parser.add_argument("--ingest-limit", type=int, default=200, 
                        help="Max games for ingest (default: 200)")
    args = parser.parse_args()

    # 1. Fetch schedule
    all_games = fetch_schedule()
    if not all_games:
        logger.error("No games found!")
        sys.exit(1)

    # 2. Connect to DB
    conn = psycopg2.connect(**DB_CONFIG)
    team_mapping = get_team_mapping(conn)

    # 3. Parse games
    rows = []
    skipped_pending = 0
    for g in all_games:
        row = parse_game(g, team_mapping)
        if row:
            rows.append(row)
        else:
            skipped_pending += 1

    logger.info(f"Parsed: {len(rows)} final games, {skipped_pending} pending/not-final skipped")

    # Summary
    playoffs = [r for r in rows if r["season_type"] == "Playoffs"]
    playin = [r for r in rows if r["season_type"] == "Play-In"]
    logger.info(f"Breakdown: {len(playoffs)} Playoffs, {len(playin)} Play-In")

    # Show sample
    if rows:
        logger.info("Sample (first 5):")
        for r in sorted(rows, key=lambda x: x["game_date"] or "")[:5]:
            logger.info(f"  {r['game_id']} {r['game_date']} "
                        f"{r['away_team_abbr']}({r['away_pts']}) @ "
                        f"{r['home_team_abbr']}({r['home_pts']}) [{r['season_type']}]")

    # 4. Insert
    inserted = upsert_games(conn, rows, dry_run=args.dry_run)

    if not args.dry_run:
        verify_insert(conn)

    conn.close()

    # 5. Run ingest if requested
    if args.ingest and not args.dry_run and inserted > 0:
        logger.info(f"\n{'='*60}")
        logger.info(f"Starting ingest_nba_api.py for 2026 season (limit={args.ingest_limit})...")
        logger.info(f"{'='*60}")
        
        python = sys.executable
        script = str(Path(__file__).parent / "ingest_nba_api.py")
        cmd = [python, script, "--season", "2026", "--resume", "--limit", str(args.ingest_limit)]
        
        logger.info(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=False)


if __name__ == "__main__":
    main()
