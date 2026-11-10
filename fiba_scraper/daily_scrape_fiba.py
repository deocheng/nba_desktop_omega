"""Daily incremental FIBA scraper — capture REAL-TIME data, prioritizing PBP.

Why this exists
--------------
FIBA's play-by-play (and shot chart) is an *ephemeral live feed*: the
`game-live-info` route only serves periodActions for games played within a
short retention window (~17h; it rolls off afterwards and returns
`game.content: null`). Boxscore (`getgdapgamestatisticsbygameid`) is permanent
for all games. So a one-off full load can only ever keep the PBP of games that
happened to be inside the window at scrape time.

This script is meant to run DAILY (or more often): for each recently-played
game it re-loads boxscore + grabs whatever PBP is still in the window, flagging
captured games (`games.pbp_loaded`) so future runs never delete already-captured
PBP after the window closes.

Safety
------
* PBP is only delete+inserted when the live feed actually returns events
  (see batch_scrape_fiba.load_game). If the feed has rolled off, existing PBP
  is preserved — never wiped.
* Boxscore upsert is idempotent.

Usage
-----
    daily_scrape_fiba.py [--competition-id 208943] [--days 2] [--no-archive]
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fiba_db as db
import fiba_api as fa
from batch_scrape_fiba import load_game, ARCHIVE_DIR, _delay

DEFAULT_COMPETITION = 208943
DEFAULT_DAYS = 2  # > retention window (~17h) so we never skip a catchable game

# Local PG cluster is manually started (port 5433). For an unattended daily job
# we try to bring it up if it's down, so the run doesn't silently fail.
PG_START = [
    "/opt/homebrew/opt/postgresql@18/bin/pg_ctl",
    "-D", "/Volumes/12T/NBA/nba_pg",
    "-o", "-p 5433",
    "-l", "/Volumes/12T/NBA/nba_pg/pg.log",
    "start",
]


def ensure_pg() -> None:
    """Connect; if it fails, attempt to start the local PG cluster once, then retry."""
    try:
        c = db.get_conn()
        c.close()
        return
    except Exception:
        print("[daily] PG not reachable — attempting start (pg_ctl)...")
        try:
            subprocess.run(PG_START, check=False, capture_output=True, text=True,
                           timeout=30)
        except Exception as e:
            print(f"[daily] pg_ctl launch error: {e}")
        time.sleep(4)
        # raise if still down — get_conn will surface the real error
        c = db.get_conn()
        c.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily incremental FIBA scrape (PBP priority).")
    ap.add_argument("--competition-id", type=int, default=DEFAULT_COMPETITION)
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help="look-back window in days for 'recent' games")
    ap.add_argument("--no-archive", action="store_true",
                    help="do not write raw JSON to ARCHIVE_DIR")
    ap.add_argument("--dry-run", action="store_true",
                    help="list target games and exit (no network/DB writes)")
    args = ap.parse_args()

    ensure_pg()  # bring local PG up if down; raises if still unreachable
    conn = db.get_conn()
    try:
        db.init_schema(conn)  # ensure pbp_loaded / boxscore_loaded columns exist
        cur = conn.cursor()

        # Recent, played games (status VALID; also catch LIVE in progress).
        cur.execute(
            """
            SELECT game_id, status, game_datetime_utc, pbp_loaded
            FROM games
            WHERE competition_id = %s
              AND status IN ('VALID', 'LIVE', 'PLAYED')
              AND game_datetime_utc >= NOW() - (%s || ' days')::INTERVAL
            ORDER BY game_datetime_utc DESC
            """,
            (args.competition_id, args.days),
        )
        targets = cur.fetchall()
        print(f"[daily] competition={args.competition_id} window={args.days}d "
              f"-> {len(targets)} recent game(s)")

        if args.dry_run:
            for gid, st, dt, pbp in targets:
                print(f"  {gid}  {st}  {dt}  pbp_loaded={pbp}")
            return

        pbp_captured = 0
        box_refreshed = 0
        for gid, st, dt, already_pbp in targets:
            try:
                g = fa.get_game(gid)
                counts = load_game(conn, g, archive=not args.no_archive,
                                   competition_id=args.competition_id)
                box_refreshed += 1
                if counts.get("pbp"):
                    pbp_captured += 1
                    print(f"  [{gid}] PBP captured: {counts['pbp']} events "
                          f"(box={counts['player_stats']} players)")
                else:
                    print(f"  [{gid}] boxscore refreshed; PBP not in window"
                          f"{' (already captured)' if already_pbp else ''}")
            except Exception as e:  # one bad game must not abort the run
                conn.rollback()
                print(f"  [{gid}] ERROR: {repr(e)[:160]}")

        # Summary
        cur.execute(
            "SELECT COUNT(*) FROM games WHERE pbp_loaded",
        )
        total_pbp = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM play_by_play")
        pbp_rows = cur.fetchone()[0]
        print(f"[daily] done. PBP captured this run={pbp_captured}, "
              f"boxscore refreshed={box_refreshed}. "
              f"DB totals: games_with_pbp={total_pbp}, play_by_play_rows={pbp_rows}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
