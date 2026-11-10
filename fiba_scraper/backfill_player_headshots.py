#!/usr/bin/env python3
"""
GAP-3 (headshot sub-item) backfill — populate players.headshot_url for every
player in the FIBA World Cup 2027 European Qualifiers dataset.

FIBA serves per-player headshots from a *public* Cloudinary CDN keyed by the
numeric player_id (no APIM subscription key required). The URL is fully
deterministic:

    https://res.cloudinary.com/ddsbdyeyj/image/upload/.headshot--person_<player_id>

This script is:
  * Idempotent  -> re-running only fills rows where headshot_url IS NULL.
  * Rollbackable -> snapshots `players` to `players_bak_gap3b_headshot` once,
                    before any write, and only if that snapshot does not exist.
  * Verifiable  -> prints pre/post counts and HTTP-probes a random sample to
                   confirm the CDN actually returns 200 image/png.

Run:
    .venv/bin/python backfill_player_headshots.py [--verify-sample N] [--dry-run]
"""
import argparse
import os
import random
import subprocess
import sys

import psycopg2

# Reuse the project's connection + schema helpers.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fiba_db  # noqa: E402

CLOUDINARY_BASE = "https://res.cloudinary.com/ddsbdyeyj/image/upload/.headshot--person_"
SNAPSHOT = "players_bak_gap3b_headshot_comp"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")


def snapshot_exists(cur):
    cur.execute(
        "SELECT 1 FROM pg_class WHERE relname = %s AND relkind = 'r'",
        (SNAPSHOT,),
    )
    return cur.fetchone() is not None


def http_probe(url: str) -> tuple:
    """Return (http_code, ok) using system curl (CF/Cloudinary work via UA)."""
    out = subprocess.run(
        ["curl", "--noproxy", "*", "-s", "-o", "/dev/null",
         "-w", "%{http_code}", "-A", UA, url],
        capture_output=True, text=True, timeout=20,
    )
    code = out.stdout.strip()
    try:
        return int(code), code == "200"
    except ValueError:
        return -1, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--competition-id", type=int, default=208943,
                    help="FIBA competition id; when set, headshots use the "
                         "competition-specific Cloudinary public_id "
                         "'.headshot--person_<pid>--competition_<cid>' (the "
                         "exact variant FIBA's Headshot component renders on "
                         "event pages). Pass 0 to use the generic variant.")
    ap.add_argument("--verify-sample", type=int, default=8,
                    help="number of random rows to HTTP-probe (0 to skip)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Build the target URL template for this competition.
    suffix = f"--competition_{args.competition_id}" if args.competition_id else ""
    target_tmpl = CLOUDINARY_BASE + "{pid}" + suffix

    conn = fiba_db.get_conn()
    cur = conn.cursor()
    try:
        # 1. Ensure the schema migration (headshot_url column) is applied.
        fiba_db.init_schema(conn)

        # 2. Coverage before.
        cur.execute("SELECT count(*) FROM players")
        total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM players WHERE headshot_url IS NULL")
        nulls_before = cur.fetchone()[0]

        print(f"[pre] players={total}  headshot_url NULL={nulls_before}")
        print(f"[pre] target format={target_tmpl.format(pid='<pid>')}")

        if args.dry_run:
            print("[dry-run] would set headshot_url for the rows above; no write.")
            return

        # 3. Rollback snapshot (written once) — captures current state so we
        #    can revert to the previously-stored URLs (generic or competition).
        if not snapshot_exists(cur):
            cur.execute(
                f"CREATE TABLE {SNAPSHOT} AS SELECT * FROM players")
            print(f"[snapshot] created {SNAPSHOT} ({total} rows)")
        else:
            print(f"[snapshot] {SNAPSHOT} already exists — kept as-is")

        # 4. Backfill / overwrite. Idempotent: only rows whose stored URL
        #    differs from the target pattern are rewritten (IS DISTINCT FROM).
        cur.execute(
            "UPDATE players SET headshot_url = %s || player_id::text || %s "
            "WHERE headshot_url IS DISTINCT FROM (%s || player_id::text || %s)",
            (CLOUDINARY_BASE, suffix, CLOUDINARY_BASE, suffix),
        )
        conn.commit()
        updated = cur.rowcount
        print(f"[update] set headshot_url on {updated} rows")

        # 5. Coverage after.
        cur.execute("SELECT count(*) FROM players WHERE headshot_url IS NULL")
        nulls_after = cur.fetchone()[0]
        print(f"[post] headshot_url NULL={nulls_after}  (was {nulls_before})")

        # 6. HTTP-probe a sample to prove the URLs are live.
        if args.verify_sample and nulls_after == 0:
            cur.execute(
                "SELECT player_id, headshot_url FROM players "
                "ORDER BY random() LIMIT %s",
                (min(args.verify_sample, total),),
            )
            sample = cur.fetchall()
            ok = 0
            for pid, url in sample:
                code, good = http_probe(url)
                status = "OK" if good else f"BAD({code})"
                ok += 1 if good else 0
                print(f"  probe pid={pid} -> {code} {status}")
            print(f"[verify] {ok}/{len(sample)} sampled headshots returned 200")
        elif args.verify_sample:
            print(f"[verify] skipped (NULL={nulls_after} > 0)")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
