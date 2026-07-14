#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NBA Data Daily Maintenance Pipeline
====================================
Runs sequentially: data gap scan -> injuries -> transactions -> validation
Each step is wrapped in try/except with rollback to prevent cascade failures.

Usage:
  python crawler/daily_maintenance.py
  python crawler/daily_maintenance.py --skip-injuries
  python crawler/daily_maintenance.py --only injuries
"""
import sys
import os
import time
import logging
import argparse
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("DailyMaintenance")

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}

PSQL = r'"C:\Program Files\PostgreSQL\17\bin\psql.exe"'
PYTHON = sys.executable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def safe_run(label: str, conn, func, *args, **kwargs):
    """Run a task with try/except, log result, never crash the pipeline."""
    logger.info(f"{'=' * 60}")
    logger.info(f"[{label}] Starting...")
    logger.info(f"{'=' * 60}")
    start = time.time()
    try:
        result = func(*args, **kwargs)
        conn.commit()  # close read-only tx / persist changes, avoid blocking DDL
        elapsed = time.time() - start
        logger.info(f"[{label}] Done in {elapsed:.1f}s")
        return result
    except Exception as e:
        conn.rollback()
        elapsed = time.time() - start
        logger.error(f"[{label}] FAILED after {elapsed:.1f}s: {e}")
        return None


def scan_data_gaps(conn):
    """Scan for missing schedules, PBP, and aggregates."""
    cur = conn.cursor()
    logger.info("Scanning data gaps...")

    try:
        cur.execute("""
            SELECT season,
                   COUNT(*) FILTER (WHERE game_id IS NULL) as missing_games,
                   COUNT(*) FILTER (WHERE game_date IS NULL) as missing_dates
            FROM (
                SELECT DISTINCT
                    g.season,
                    g.game_id,
                    g.game_date
                FROM games g
                WHERE g.season BETWEEN 2020 AND 2026
            ) sub
            GROUP BY season
            ORDER BY season DESC
            LIMIT 15
        """)
        rows = cur.fetchall()
        for row in rows:
            sid, mg, md = row
            season_name = f"{sid-1}-{str(sid)[-2:]}"
            logger.info(f"  {season_name} (season={sid}): missing_games={mg}, missing_dates={md}")
    except Exception as e:
        conn.rollback()
        raise
    finally:
        cur.close()
    logger.info("Data gap scan complete.")


def run_injuries(conn):
    """Scrape injuries via Playwright Stealth, write to injuries table."""
    import subprocess

    script = os.path.join(PROJECT_ROOT, "crawler", "br_injuries_playwright.py")
    if not os.path.exists(script):
        logger.warning(f"Injuries script not found: {script}")
        return

    result = subprocess.run(
        [PYTHON, script],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=PROJECT_ROOT,
    )
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            logger.info(f"  [injuries] {line}")
    if result.returncode != 0:
        logger.error(f"[injuries] Script failed: {result.stderr[:500]}")
    else:
        logger.info("[injuries] Script completed successfully")


def run_transactions(conn):
    """Scrape 2025-26 season transactions from BR."""
    import subprocess

    script = os.path.join(PROJECT_ROOT, "crawler", "crawl_br_transactions.py")
    if not os.path.exists(script):
        logger.warning(f"Transactions script not found: {script}")
        return

    result = subprocess.run(
        [PYTHON, script, "--year", "2026"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=PROJECT_ROOT,
    )
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            logger.info(f"  [tx] {line}")
    if result.returncode != 0:
        logger.error(f"[tx] Script failed: {result.stderr[:500]}")
    else:
        logger.info("[tx] Script completed successfully")


def run_validation(conn):
    """Run basic data validation checks."""
    cur = conn.cursor()

    checks = [
        ("Total games", "SELECT COUNT(*) FROM games"),
        ("Total PBP events", "SELECT COUNT(*) FROM play_by_play"),
        ("Total players (per_game)", "SELECT COUNT(DISTINCT player) FROM player_per_game"),
        ("Injuries count", "SELECT COUNT(*) FROM injuries"),
        ("Transactions count", "SELECT COUNT(*) FROM transactions"),
        ("Game metadata coverage",
         "SELECT COUNT(*) FILTER (WHERE arena_name IS NOT NULL)::float / NULLIF(COUNT(*),0) "
         "FROM game_metadata"),
        ("Starting lineups count", "SELECT COUNT(*) FROM starting_lineups"),
        ("Player gamelog count", "SELECT COUNT(*) FROM player_gamelog"),
    ]

    logger.info("Running data validation checks...")
    for label, query in checks:
        try:
            cur.execute(query)
            val = cur.fetchone()[0]
            if isinstance(val, float):
                logger.info(f"  {label}: {val:.1%}")
            else:
                logger.info(f"  {label}: {val:,}")
        except Exception as e:
            logger.error(f"  {label}: ERROR - {e}")
            conn.rollback()  # critical: rollback so next check can run

    cur.close()
    logger.info("Validation complete.")


def run_ingest_nba_api(conn):
    """Run NBA API data ingestion (game_metadata, player_game_details, etc.)."""
    import subprocess

    script = os.path.join(PROJECT_ROOT, "crawler", "ingest_nba_api.py")
    if not os.path.exists(script):
        logger.warning(f"Ingest script not found: {script}")
        return

    result = subprocess.run(
        [PYTHON, script, "--auto"],
        capture_output=True,
        text=True,
        timeout=1200,
        cwd=PROJECT_ROOT,
    )
    if result.stdout:
        for line in result.stdout.strip().split("\n")[-20:]:  # last 20 lines
            logger.info(f"  [ingest] {line}")
    if result.returncode != 0:
        logger.error(f"[ingest] Script failed: {result.stderr[:500]}")
    else:
        logger.info("[ingest] Script completed successfully")


def run_weight_scrape(conn):
    """Run a small batch of player weight scraping (20 players, 12-18s intervals)."""
    import subprocess

    script = os.path.join(PROJECT_ROOT, "crawler", "scrape_player_weight.py")
    if not os.path.exists(script):
        logger.warning(f"Weight scraper not found: {script}")
        return

    result = subprocess.run(
        [PYTHON, script, "--batch", "20", "--min-delay", "12", "--max-delay", "18"],
        capture_output=True,
        text=True,
        timeout=900,  # 15 min max for 20 players
        cwd=PROJECT_ROOT,
    )
    if result.stdout:
        for line in result.stdout.strip().split("\n")[-15:]:
            logger.info(f"  [weight] {line}")
    if result.returncode != 0:
        logger.error(f"[weight] Script failed: {result.stderr[:500]}")
    else:
        logger.info("[weight] Script completed successfully")


def main():
    parser = argparse.ArgumentParser(description="NBA Data Daily Maintenance")
    parser.add_argument("--only", choices=["scan", "injuries", "transactions", "validation", "ingest", "weight"],
                        help="Run only one specific task")
    parser.add_argument("--skip-injuries", action="store_true", help="Skip injuries scraping")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip NBA API ingestion")
    parser.add_argument("--skip-weight", action="store_true", help="Skip weight scraping")
    args = parser.parse_args()

    import psycopg2

    start = time.time()
    logger.info("=" * 60)
    logger.info(f"NBA Data Daily Maintenance - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    logger.info("Database connected.")

    try:
        if args.only:
            if args.only == "scan":
                safe_run("DataGapScan", conn, scan_data_gaps, conn)
            elif args.only == "injuries":
                safe_run("Injuries", conn, run_injuries, conn)
            elif args.only == "transactions":
                safe_run("Transactions", conn, run_transactions, conn)
            elif args.only == "validation":
                safe_run("Validation", conn, run_validation, conn)
            elif args.only == "ingest":
                safe_run("NBAIngest", conn, run_ingest_nba_api, conn)
            elif args.only == "weight":
                safe_run("WeightScrape", conn, run_weight_scrape, conn)
        else:
            # Full pipeline
            safe_run("DataGapScan", conn, scan_data_gaps, conn)

            if not args.skip_injuries:
                safe_run("Injuries", conn, run_injuries, conn)

            safe_run("Transactions", conn, run_transactions, conn)

            if not args.skip_ingest:
                safe_run("NBAIngest", conn, run_ingest_nba_api, conn)

            if not args.skip_weight:
                safe_run("WeightScrape", conn, run_weight_scrape, conn)

            safe_run("Validation", conn, run_validation, conn)

    finally:
        conn.close()
        logger.info("Database connection closed.")

    elapsed = time.time() - start
    logger.info("=" * 60)
    logger.info(f"Daily maintenance complete. Total time: {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
