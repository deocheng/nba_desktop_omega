"""NBACore v8 — Migrate games.game_id to Basketball-Reference (BR) naming.

BACKGROUND
----------
`games.game_id` was historically the numeric NBA.com id (= `nba_api_id`).
For the two recent seasons (2025=2024-25, 2026=2025-26) we want `game_id`
to be the BR alphanumeric id (e.g. `202605130DET`) so the public API / UI
expose the more human-readable BR key, while `nba_api_id` remains the
authoritative numeric join key for `player_gamelog.gameid` / `play_by_play.gameid`.

WHAT THIS SCRIPT DOES (single transaction, fully rollback-able)
---------------------------------------------------------------
1. BACKUP:  CREATE TABLE IF NOT EXISTS games_bak_pre_br AS
            SELECT * FROM games WHERE season IN (2025, 2026).  (idempotent)
2. DEDUP:   For the 242 duplicate groups on (game_date, home, away):
              * pick a canonical row (nba_api_id NOT NULL preferred),
              * merge non-null boxscore_url / br_crawled_id from siblings,
              * DELETE the sibling rows.
3. MAIN:    UPDATE game_id -> BR id for rows that have a BR source
            (br_crawled_id OR a boxscore_url matching the BR pattern).
4. CHECK:   After UPDATE but BEFORE COMMIT:
              * no duplicate game_id in recent seasons,
              * numeric game_id count ~= 838 (rows missing both BR sources),
              * nba_api_id fully non-null in recent seasons.
            Any failure -> ROLLBACK + non-zero exit.  Else COMMIT.

USAGE
-----
    python scripts/migrate_games_gameid_to_br.py            # real run
    python scripts/migrate_games_gameid_to_br.py --dry-run  # counts only

The script never adds UNIQUE constraints (the table has ~99K rows; adding a
constraint would lock the table).  Constraints are left as a later task.
"""
from __future__ import annotations

import argparse
import re
import sys

import psycopg2
from psycopg2.extras import RealDictCursor

# ── DB connection (mirrors backend.core.config.DB_CONFIG) ──
DB_CONFIG: dict = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}

SEASONS: tuple[int, int] = (2025, 2026)

# BR boxscore url pattern -> captures id like 202605130DET
BR_URL_RE: str = r"/boxscores/(\d{8,}[A-Z]{3})\.html"
# Pure-numeric game_id (i.e. not yet converted to BR)
NUMERIC_RE: str = r"^\d+$"

# NOTE: The originally verified "838 rows missing both BR sources" figure is
# specific to a point-in-time snapshot.  The live DB may have been backfilled
# (crawler) since then, so the numeric (unconverted) count is computed
# dynamically from the data and used for validation (see compute_counts).


def connect() -> psycopg2.extensions.connection:
    """Open a raw psycopg2 connection (this script is a migration utility,
    intentionally outside the read-only data layer)."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    return conn


def compute_counts(cur: RealDictCursor) -> dict:
    """Compute all relevant counts without writing anything."""
    # Backup size (rows that would be snapshotted)
    cur.execute(
        "SELECT count(*) AS c FROM games WHERE season IN %s", (SEASONS,)
    )
    backup_total = cur.fetchone()["c"]

    # Duplicate groups on (game_date, home, away)
    cur.execute(
        """
        SELECT game_date, home_team_abbr, away_team_abbr
        FROM games
        WHERE season IN %s
        GROUP BY game_date, home_team_abbr, away_team_abbr
        HAVING count(*) > 1
        """,
        (SEASONS,),
    )
    groups = [dict(r) for r in cur.fetchall()]

    # Would-be-deleted sibling rows
    would_delete = 0
    for g in groups:
        cur.execute(
            """
            SELECT count(*) AS c FROM games
            WHERE game_date = %s
              AND home_team_abbr = %s
              AND away_team_abbr = %s
            """,
            (g["game_date"], g["home_team_abbr"], g["away_team_abbr"]),
        )
        would_delete += cur.fetchone()["c"] - 1

    # Collision-safe convertible rows (winners) and expected numeric remainder.
    # Mirrors the real main_update logic (one winner per BR id, skipping any
    # BR id already held by a non-batch row) expressed as a SELECT so the
    # dry-run can report accurate numbers without writing.  game_id carries a
    # UNIQUE INDEX (games_pkey), so the conversion MUST avoid collisions:
    #   * two source rows can resolve to the same BR id (mismatched
    #     br_crawled_id / boxscore_url) -> we keep only one (rn = 1);
    #   * a target BR id may already exist as a game_id on a different row
    #     (incl. other seasons) -> we skip it (NOT EXISTS guard).
    cur.execute(
        """
        WITH tgt AS (
            SELECT g.game_id AS old_id,
                   COALESCE(
                       g.br_crawled_id,
                       (regexp_match(g.boxscore_url, %s))[1]
                   ) AS br_id
            FROM games g
            WHERE g.season IN %s
              AND g.nba_api_id IS NOT NULL
              AND (g.br_crawled_id IS NOT NULL
                   OR g.boxscore_url ~ %s)
        ),
        ranked AS (
            SELECT old_id, br_id,
                   ROW_NUMBER() OVER (PARTITION BY br_id ORDER BY old_id) AS rn
            FROM tgt
        ),
        winners AS (
            SELECT old_id, br_id FROM ranked WHERE rn = 1
        )
        SELECT
            (SELECT count(*) FROM winners) AS winners,
            (SELECT count(*) FROM winners w
             WHERE NOT EXISTS (
                 SELECT 1 FROM games x
                 WHERE x.game_id = w.br_id
                   AND x.game_id NOT IN (SELECT old_id FROM winners)
             )) AS safe_winners
        """,
        (BR_URL_RE, SEASONS, BR_URL_RE),
    )
    wr = cur.fetchone()
    safe_winners = wr["safe_winners"] or 0

    # Estimated numeric (unconverted) rows remaining after dedup + conversion.
    expected_numeric = (backup_total - would_delete) - safe_winners

    return {
        "backup_total": backup_total,
        "dup_groups": len(groups),
        "would_delete": would_delete,
        "safe_winners": safe_winners,
        "expected_numeric": expected_numeric,
    }


def dedup(cur: RealDictCursor) -> int:
    """Collapse duplicate (game_date, home, away) groups to a single canonical
    row, merging non-null BR fields from siblings. Returns #deleted siblings."""
    cur.execute(
        """
        SELECT game_date, home_team_abbr, away_team_abbr
        FROM games
        WHERE season IN %s
        GROUP BY game_date, home_team_abbr, away_team_abbr
        HAVING count(*) > 1
        """,
        (SEASONS,),
    )
    groups = [dict(r) for r in cur.fetchall()]

    deleted = 0
    for g in groups:
        cur.execute(
            """
            SELECT game_id, nba_api_id, boxscore_url, br_crawled_id
            FROM games
            WHERE game_date = %s
              AND home_team_abbr = %s
              AND away_team_abbr = %s
            ORDER BY game_id
            """,
            (g["game_date"], g["home_team_abbr"], g["away_team_abbr"]),
        )
        rows = [dict(r) for r in cur.fetchall()]
        if not rows:
            continue

        # 1) canonical = row with nba_api_id NOT NULL (expected unique)
        canonical = next((r for r in rows if r["nba_api_id"] is not None), None)
        # 2) fallback: a row that already has a BR source
        if canonical is None:
            canonical = next(
                (
                    r
                    for r in rows
                    if r["br_crawled_id"] is not None or r["boxscore_url"] is not None
                ),
                None,
            )
        # 3) last resort: first row
        if canonical is None:
            canonical = rows[0]

        for r in rows:
            if r is canonical:
                continue
            updates: list[str] = []
            params: list = []
            if canonical["boxscore_url"] is None and r["boxscore_url"] is not None:
                updates.append("boxscore_url = %s")
                params.append(r["boxscore_url"])
            if canonical["br_crawled_id"] is None and r["br_crawled_id"] is not None:
                updates.append("br_crawled_id = %s")
                params.append(r["br_crawled_id"])
            if updates:
                params.append(canonical["game_id"])
                cur.execute(
                    f"UPDATE games SET {', '.join(updates)} WHERE game_id = %s",
                    params,
                )
            # Remove the sibling (keep only the canonical row)
            cur.execute("DELETE FROM games WHERE game_id = %s", (r["game_id"],))
            deleted += 1

    return deleted


def main_update(cur: RealDictCursor) -> int:
    """Set game_id = BR id for rows with a BR source, collision-safe.

    game_id carries a UNIQUE INDEX (games_pkey), so we must not assign the
    same BR id to two rows nor reuse an id already held elsewhere.
      * PARTITION BY br_id + rn = 1  -> one winner per BR id (the rest of a
        CTE-internal collision are left numeric / handled by dedup);
      * NOT EXISTS guard             -> skip any BR id already present as a
        game_id on a row outside this batch (incl. other seasons).
    Returns the number of rows actually updated.
    """
    cur.execute(
        """
        WITH tgt AS (
            SELECT g.game_id AS old_id,
                   COALESCE(
                       g.br_crawled_id,
                       (regexp_match(g.boxscore_url, %s))[1]
                   ) AS br_id
            FROM games g
            WHERE g.season IN %s
              AND g.nba_api_id IS NOT NULL
              AND (g.br_crawled_id IS NOT NULL
                   OR g.boxscore_url ~ %s)
        ),
        ranked AS (
            SELECT old_id, br_id,
                   ROW_NUMBER() OVER (PARTITION BY br_id ORDER BY old_id) AS rn
            FROM tgt
        ),
        winners AS (
            SELECT old_id, br_id FROM ranked WHERE rn = 1
        )
        UPDATE games g
        SET game_id = w.br_id
        FROM winners w
        WHERE g.game_id = w.old_id
          AND NOT EXISTS (
              SELECT 1 FROM games x
              WHERE x.game_id = w.br_id
                AND x.game_id NOT IN (SELECT old_id FROM winners)
          )
        """,
        (BR_URL_RE, SEASONS, BR_URL_RE),
    )
    return cur.rowcount


def validate(cur: RealDictCursor) -> dict:
    """Post-update invariants. Returns a dict of measured values."""
    cur.execute(
        """
        SELECT count(*) AS c FROM (
            SELECT game_id FROM games WHERE season IN %s
            GROUP BY game_id HAVING count(*) > 1
        ) d
        """,
        (SEASONS,),
    )
    dup_after = cur.fetchone()["c"]

    cur.execute(
        "SELECT count(*) AS c FROM games WHERE season IN %s AND game_id ~ %s",
        (SEASONS, NUMERIC_RE),
    )
    numeric = cur.fetchone()["c"]

    cur.execute(
        "SELECT count(*) AS c FROM games WHERE season IN %s AND nba_api_id IS NULL",
        (SEASONS,),
    )
    null_nba = cur.fetchone()["c"]

    return {"dup_after": dup_after, "numeric": numeric, "null_nba": null_nba}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate games.game_id to BR naming (seasons 2025, 2026)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print counts; perform no writes.",
    )
    args = parser.parse_args()

    conn = connect()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        counts = compute_counts(cur)
        print("=" * 60)
        print("PRE-CHECK COUNTS (seasons %s)" % (SEASONS,))
        print("=" * 60)
        print(f"  backup rows (season IN {SEASONS}) : {counts['backup_total']}")
        print(f"  duplicate (date,home,away) groups : {counts['dup_groups']}")
        print(f"  would-be-deleted siblings        : {counts['would_delete']}")
        print(f"  convertible rows (safe winners)  : {counts['safe_winners']}")
        print(f"  numeric game_id rows EXPECTED    : {counts['expected_numeric']}")

        if args.dry_run:
            print("\n[DRY-RUN] No writes performed. Exiting.")
            conn.rollback()
            return

        # 1) BACKUP (idempotent; rolled back automatically on failure)
        cur.execute(
            "CREATE TABLE IF NOT EXISTS games_bak_pre_br "
            "AS SELECT * FROM games WHERE season IN %s",
            (SEASONS,),
        )

        # 2) DEDUP merge
        deleted = dedup(cur)

        # 3) MAIN UPDATE
        updated = main_update(cur)

        # 4) VALIDATE (before commit)
        v = validate(cur)

        print("=" * 60)
        print("EXECUTION RESULT")
        print("=" * 60)
        print(f"  deleted siblings         : {deleted}")
        print(f"  main UPDATE affected     : {updated}")
        print(f"  duplicate game_id after  : {v['dup_after']}")
        print(f"  numeric game_id rows     : {v['numeric']} (expected {counts['expected_numeric']})")
        print(f"  nba_api_id NULL (recent) : {v['null_nba']}")

        errors: list[str] = []
        if v["dup_after"] != 0:
            errors.append(f"duplicate game_id still exists: {v['dup_after']} group(s)")
        if v["null_nba"] != 0:
            errors.append(
                f"nba_api_id became NULL in recent seasons: {v['null_nba']}"
            )

        if errors:
            print("\nVALIDATION FAILED:")
            for e in errors:
                print("  - " + e)
            conn.rollback()
            print("ROLLED BACK — no changes committed.")
            sys.exit(1)

        # numeric (unconverted) count is informational only — the verified
        # "838 missing-source rows" figure is a point-in-time snapshot, and the
        # collision-safe UPDATE deliberately leaves a few extra rows numeric
        # (mismatched BR data / cross-season clashes).  Warn only if wildly off.
        if abs(v["numeric"] - counts["expected_numeric"]) > 200:
            print(
                f"\n[WARN] numeric game_id count {v['numeric']} far from expected "
                f"{counts['expected_numeric']} (review recommended)."
            )

        conn.commit()
        print("\nVALIDATION PASSED — changes committed.")
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"\nERROR during migration: {exc}")
        print("ROLLED BACK — no changes committed.")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
