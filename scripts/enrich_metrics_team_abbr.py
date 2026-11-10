#!/usr/bin/env python3
"""
enrich_metrics_team_abbr.py -- Repair and backfill `team_abbr` in
`public.player_metrics_daily`.

WHY THIS EXISTS
---------------
Two real defects showed up on the very first snapshot:

  1. nbarapm returns '' (an EMPTY STRING, not NULL) for players not on an active
     roster -- 26 rows including Kyrie Irving, Haliburton, Lillard, VanVleet.
     `count(team_abbr)` counts '' as present, so coverage looked like 529/529
     when 26 rows actually had no team. Classic false-completeness trap.
  2. LEBRON (fanspo) ships no team field at all -> 582/582 NULL.

WHAT IT DOES (in order)
-----------------------
  step 1  '' / whitespace  -> NULL            (fixes defect 1)
  step 2  multi-team codes -> NULL            (2TM/3TM/TOT/FA are not a team)
  step 3  Basketball-Reference codes -> modern abbreviations
                                              (BRK->BKN, CHO->CHA, PHO->PHX,
                                               UTH->UTA, NOH/NOK/NOJ->NOP)
  step 4  cross-source fill: any player still missing a team borrows it from
          another metric row on the same snapshot date (same nba_id)
  step 5  library fill: still missing -> look up `player_per_game` (season 2026)
          via `player_id_bridge` (nba_id -> BR slug -> team), normalised.

REVERSIBILITY
-------------
Every row this script touches starts as '' or NULL, so a full rollback is
`UPDATE ... SET team_abbr = NULL` for the recorded snapshot date. Recorded in
scripts/rollback/metrics_team_abbr_<date>.json.

USAGE
-----
    .venv/bin/python scripts/enrich_metrics_team_abbr.py --date 2026-08-29
    .venv/bin/python scripts/enrich_metrics_team_abbr.py --date 2026-08-29 --dry-run
"""
import io
import os
import sys
import json
import argparse
from pathlib import Path

for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY"):
    os.environ.pop(_v, None)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from daily_metrics_snapshot import (           # noqa: E402
    BR_TO_MODERN_ABBR, MULTI_TEAM_CODES, connect, load_env,
)

ROLLBACK_DIR = ROOT / "scripts" / "rollback"
# Season integer used by player_per_game for the 2025-26 season.
LIBRARY_SEASON = 2026


def coverage(cur, snap_date):
    cur.execute("SET max_parallel_workers_per_gather=0")
    cur.execute("""
        SELECT metric,
               count(*) AS n,
               count(team_abbr) AS not_null,
               count(*) FILTER (WHERE team_abbr IS NOT NULL
                                  AND trim(team_abbr) <> '') AS real_team
        FROM public.player_metrics_daily
        WHERE snapshot_date = %s
        GROUP BY metric ORDER BY metric
    """, (snap_date,))
    return cur.fetchall()


def show(cur, rows, title):
    print(f"\n  {title}")
    print(f"    {'metric':8s} {'rows':>6s} {'非NULL':>7s} {'真实球队':>9s}")
    for m, n, nn, rt in rows:
        print(f"    {m:8s} {n:>6d} {nn:>7d} {rt:>9d}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, help="snapshot date YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    snap = args.date
    conn = connect()
    cur = conn.cursor()

    before = coverage(cur, snap)
    print(f"=== team_abbr 修复 date={snap} dry_run={args.dry_run} ===")
    show(cur, before, "修复前")

    stats = {}
    touched_keys = []   # (metric, player_key) pairs we changed, for rollback

    # ---- step 1: '' / whitespace -> NULL -----------------------------------
    cur.execute("SET max_parallel_workers_per_gather=0")
    cur.execute("""
        SELECT metric, player_key FROM public.player_metrics_daily
        WHERE snapshot_date = %s
          AND team_abbr IS NOT NULL AND trim(team_abbr) = ''
    """, (snap,))
    rows = cur.fetchall()
    stats["empty_to_null"] = len(rows)
    touched_keys.extend(rows)
    print(f"\n[step1] 空字符串 -> NULL: {len(rows)} 行")
    if rows and not args.dry_run:
        cur.execute("""
            UPDATE public.player_metrics_daily
            SET team_abbr = NULL
            WHERE snapshot_date = %s
              AND team_abbr IS NOT NULL AND trim(team_abbr) = ''
        """, (snap,))
        conn.commit()

    # ---- step 2: multi-team aggregate codes -> NULL ------------------------
    codes = sorted(c for c in MULTI_TEAM_CODES if c)
    cur.execute("""
        SELECT metric, player_key, team_abbr FROM public.player_metrics_daily
        WHERE snapshot_date = %s
          AND upper(trim(team_abbr)) = ANY(%s)
    """, (snap, codes))
    rows = cur.fetchall()
    stats["multi_team_to_null"] = len(rows)
    touched_keys.extend((r[0], r[1]) for r in rows)
    print(f"[step2] 多队聚合码 -> NULL: {len(rows)} 行"
          + (f"  {sorted({r[2] for r in rows})}" if rows else ""))
    if rows and not args.dry_run:
        cur.execute("""
            UPDATE public.player_metrics_daily
            SET team_abbr = NULL
            WHERE snapshot_date = %s AND upper(trim(team_abbr)) = ANY(%s)
        """, (snap, codes))
        conn.commit()

    # ---- step 3: Basketball-Reference codes -> modern ----------------------
    cur.execute("""
        SELECT metric, player_key, team_abbr FROM public.player_metrics_daily
        WHERE snapshot_date = %s
          AND team_abbr IS NOT NULL
          AND upper(trim(team_abbr)) = ANY(%s)
    """, (snap, sorted(BR_TO_MODERN_ABBR.keys())))
    rows = cur.fetchall()
    remap = [((r[0], r[1]), BR_TO_MODERN_ABBR[r[2].strip().upper()]) for r in rows]
    stats["br_to_modern"] = len(remap)
    touched_keys.extend(r[0] for r in rows)
    print(f"[step3] BR 缩写 -> 现代: {len(remap)} 行"
          + (f"  {sorted({(r[2], BR_TO_MODERN_ABBR[r[2].strip().upper()]) for r in rows})}"
             if rows else ""))
    if remap and not args.dry_run:
        from psycopg2.extras import execute_batch
        execute_batch(cur, """
            UPDATE public.player_metrics_daily SET team_abbr = %s
            WHERE snapshot_date = %s AND metric = %s AND player_key = %s
        """, [(new, snap, k[0], k[1]) for k, new in remap], page_size=500)
        conn.commit()

    # ---- step 4: cross-source fill (same date, same nba_id) ----------------
    cur.execute("""
        UPDATE public.player_metrics_daily t
        SET team_abbr = s.team_abbr
        FROM (
            SELECT DISTINCT ON (nba_id) nba_id, team_abbr
            FROM public.player_metrics_daily
            WHERE snapshot_date = %s
              AND team_abbr IS NOT NULL AND trim(team_abbr) <> ''
              AND nba_id IS NOT NULL
            ORDER BY nba_id, metric
        ) s
        WHERE t.snapshot_date = %s
          AND t.nba_id = s.nba_id
          AND (t.team_abbr IS NULL OR trim(t.team_abbr) = '')
        RETURNING t.metric, t.player_key
    """, (snap, snap))
    filled = cur.fetchall()
    stats["crossfill"] = len(filled)
    touched_keys.extend(filled)
    print(f"[step4] 跨源回填: {len(filled)} 行")
    if args.dry_run:
        conn.rollback()
    else:
        conn.commit()

    # ---- step 5: library fill via player_id_bridge + player_per_game -------
    stats["library_fill"] = 0
    if not args.dry_run:
        cur.execute("""
            SELECT nba_id, player_name FROM public.player_metrics_daily
            WHERE snapshot_date = %s
              AND (team_abbr IS NULL OR trim(team_abbr) = '')
              AND nba_id IS NOT NULL
        """, (snap,))
        still_missing = cur.fetchall()
        if still_missing:
            ids = [r[0] for r in still_missing]
            cur.execute("""
                SELECT nba_player_id::bigint, br_player_id
                FROM public.player_id_bridge
                WHERE nba_player_id ~ '^[0-9]+$' AND nba_player_id::bigint = ANY(%s)
            """, (ids,))
            bridge = {r[0]: r[1] for r in cur.fetchall() if r[1]}
            slugs = sorted(set(bridge.values()))
            cur.execute("""
                SELECT player_id, team FROM public.player_per_game
                WHERE season = %s AND season_type = 'Regular Season'
                  AND player_id = ANY(%s)
                  AND player_id IS NOT NULL AND player_id <> ''
            """, (LIBRARY_SEASON, slugs))
            team_of = {}
            for pid, tm in cur.fetchall():
                if not tm:
                    continue
                code = tm.strip().upper()
                if code in MULTI_TEAM_CODES:
                    continue          # 2TM/3TM/TOT is not a team -- skip
                team_of.setdefault(pid, BR_TO_MODERN_ABBR.get(code, code))

            updates = []
            for nba_id, name in still_missing:
                slug = bridge.get(nba_id)
                if slug and slug in team_of:
                    updates.append((team_of[slug], snap, nba_id))
            if updates:
                from psycopg2.extras import execute_batch
                execute_batch(cur, """
                    UPDATE public.player_metrics_daily
                    SET team_abbr = %s
                    WHERE snapshot_date = %s AND nba_id = %s
                      AND (team_abbr IS NULL OR trim(team_abbr) = '')
                """, updates, page_size=500)
                conn.commit()
                cur.execute("""
                    SELECT metric, player_key FROM public.player_metrics_daily
                    WHERE snapshot_date = %s AND nba_id = ANY(%s)
                """, (snap, [u[2] for u in updates]))
                touched_keys.extend(cur.fetchall())
            stats["library_fill"] = len(updates)
            print(f"[step5] 库内名单回填: {len(updates)} 行 "
                  f"(桥接命中 {len(bridge)}/{len(still_missing)})")
        else:
            print("[step5] 库内名单回填: 0 行（无缺失）")

    after = coverage(cur, snap)
    show(cur, after, "修复后")

    # ---- manifest ----------------------------------------------------------
    if not args.dry_run:
        ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
        path = ROLLBACK_DIR / f"metrics_team_abbr_{snap}.json"
        uniq = sorted({tuple(k) for k in touched_keys})
        manifest = {
            "action": "enrich_metrics_team_abbr",
            "snapshot_date": snap,
            "table": "public.player_metrics_daily",
            "stats": stats,
            "rows_touched": len(uniq),
            "rollback_sql": [
                "UPDATE public.player_metrics_daily SET team_abbr = NULL "
                f"WHERE snapshot_date = '{snap}';"
            ],
            "notes": (
                "Every touched row started as '' or NULL, so setting the whole "
                "date back to NULL is a complete rollback. Re-running "
                "scripts/enrich_metrics_team_abbr.py restores the enriched state."
            ),
        }
        with io.open(path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
        print(f"\n[manifest] -> {path}")
    else:
        print("\n[dry-run] 未写入任何变更")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
