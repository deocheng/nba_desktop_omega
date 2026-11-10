#!/usr/bin/env python3
"""Recover PBP rows that were archived as raw JSON but never landed in the DB.

Why this exists
---------------
FIBA's play-by-play is an ephemeral live feed (~17h retention). `load_game()`
archives the raw payload to `raw_archive/batch_<gid>/live_detail.json` BEFORE
inserting rows. If that DB write does not persist (crash, wrong cluster,
rolled-back transaction, ...), the archived JSON becomes the ONLY remaining
copy -- the live feed has rolled off and the data cannot be re-fetched.

This script replays archived payloads back into the DB using the exact same
write path as the scraper (`batch_scrape_fiba.insert_pbp_from_live`), so there
is no second implementation that could drift from the scraper's.

It auto-detects the gap: any archived game whose `play_by_play` row count is
zero while the archived payload still contains events.

Safety
------
* Dry run by default -- pass `--apply` to actually write.
* Only touches games genuinely missing rows; never touches games that already
  have PBP (so it can never delete existing data).
* Idempotent: delete+insert per game, safe to re-run any number of times.

Usage
-----
    python recover_pbp_from_archive.py                    # dry run (default)
    python recover_pbp_from_archive.py --apply            # write for real
    python recover_pbp_from_archive.py --game-id 127119 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fiba_api as fa
import fiba_db as db
from batch_scrape_fiba import ARCHIVE_DIR, insert_pbp_from_live


def archived_games():
    """Yield (game_id, path) for every archived live_detail.json payload."""
    if not os.path.isdir(ARCHIVE_DIR):
        return
    for name in sorted(os.listdir(ARCHIVE_DIR)):
        if not name.startswith("batch_"):
            continue
        try:
            gid = int(name[len("batch_"):])
        except ValueError:
            continue
        path = os.path.join(ARCHIVE_DIR, name, "live_detail.json")
        if os.path.isfile(path):
            yield gid, path


def db_row_count(cur, gid: int) -> int:
    cur.execute("SELECT count(*) FROM play_by_play WHERE game_id=%s", (gid,))
    return cur.fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Replay archived FIBA PBP payloads into the DB (dry run by default).")
    ap.add_argument("--apply", action="store_true",
                    help="actually write to the DB (default: dry run)")
    ap.add_argument("--game-id", type=int, action="append", dest="game_ids",
                    help="limit to specific game id(s); repeatable")
    args = ap.parse_args()

    conn = db.get_conn()
    cur = conn.cursor()

    plan, skipped_ok, skipped_empty = [], [], []
    for gid, path in archived_games():
        if args.game_ids and gid not in args.game_ids:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                live = json.load(f)
        except Exception as e:  # noqa: BLE001 - report and keep going
            print(f"  ! {gid}: cannot read {path}: {e}")
            continue

        n_events = len(fa.parse_play_by_play(live))
        have = db_row_count(cur, gid)

        if have > 0:
            skipped_ok.append((gid, have))
        elif n_events == 0:
            skipped_empty.append(gid)
        else:
            plan.append((gid, n_events, live))

    total = sum(n for _, n, _ in plan)
    print(f"archived games scanned : {len(plan) + len(skipped_ok) + len(skipped_empty)}")
    print(f"  already in DB        : {len(skipped_ok)}")
    print(f"  archived but no PBP  : {len(skipped_empty)}")
    print(f"  MISSING -> recover   : {len(plan)} games, {total} events")
    print()
    for gid, n, _ in plan:
        print(f"  - game {gid}: {n} events to write")

    if not plan:
        print("\nnothing to recover.")
        conn.close()
        return 0

    if not args.apply:
        print("\nDRY RUN - no changes written. Re-run with --apply to commit.")
        conn.close()
        return 0

    print("\n--apply: writing...")
    written = 0
    for gid, n, live in plan:
        got = insert_pbp_from_live(conn, gid, live)
        written += got
        flag = "OK " if got == n else "!! "
        print(f"  {flag}game {gid}: wrote {got} rows (expected {n})")

    cur.execute("SELECT count(*) FROM play_by_play")
    total_rows = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM games WHERE pbp_loaded")
    games_loaded = cur.fetchone()[0]
    conn.close()

    print(f"\nrecovered {written} rows across {len(plan)} game(s).")
    print(f"DB totals: games_with_pbp={games_loaded}, play_by_play_rows={total_rows}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
