"""Read-only post-commit verification of the B-class rekey (evidence for delivery).

Re-checks the 4 validations + backup table against the PERSISTED state.
Uses a hardcoded baseline of the 26 historical ids (season=1950) captured
before the change, for a strict equality comparison.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OMEGA = SCRIPT_DIR.parent
sys.path.insert(0, str(OMEGA))
os.chdir(str(OMEGA))
for _p in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_p, None)

from backend.core import config  # noqa: E402
import psycopg2  # noqa: E402
from psycopg2 import sql  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402

OLD11 = ["20251030CHO", "20251201LAL"]
NEW12 = ["202510300CHO", "202512010LAL"]
BAK_TABLE = "dim_games_recent_br_id_fix_bak"
BASE_TABLE = "dim_games"
HIST_SEASON = 1950

# Baseline captured pre-change (season=1950, 26 historical 11-bit ids).
HIST_BASELINE = [
    "194911250DN", "194911270DN", "194911290DN", "194912020DN", "194912040DN",
    "194912070DN", "194912130DN", "194912160DN", "194912180DN", "194912230DN",
    "194912250DN", "194912300DN", "195001010DN", "195001040DN", "195001050DN",
    "195001100DN", "195001310DN", "195002070DN", "195002110DN", "195002130DN",
    "195002140DN", "195002160DN", "195002190DN", "195002210DN", "195002230DN",
    "195002260DN",
]


def main() -> None:
    conn = psycopg2.connect(**config.DB_CONFIG)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        print("=" * 72)
        print("POST-COMMIT VERIFICATION (read-only)")
        print("=" * 72)

        # backup table exists & has 2 rows
        cur.execute("SELECT to_regclass(%s) AS t", (f"public.{BAK_TABLE}",))
        bak_exists = cur.fetchone()["t"] is not None
        bak_rows = 0
        if bak_exists:
            cur.execute(sql.SQL("SELECT count(*) AS c FROM {}").format(sql.Identifier(BAK_TABLE)))
            bak_rows = cur.fetchone()["c"]
        print(f"\n[BACKUP] {BAK_TABLE}: exists={bak_exists} rows={bak_rows} (want 2)")

        # ① new12 present & unique
        cur.execute(
            "SELECT game_id, count(*) AS c FROM dim_games WHERE game_id = ANY(%s) GROUP BY game_id",
            (NEW12,),
        )
        new_rows = {r["game_id"]: r["c"] for r in cur.fetchall()}
        new12_count = sum(new_rows.values())
        each_unique = all(c == 1 for c in new_rows.values())
        present = set(new_rows.keys()) == set(NEW12)
        print(f"\n① new12: count={new12_count} each_unique={each_unique} present={present}")
        for gid in NEW12:
            cur.execute(
                "SELECT game_id, br_crawled_id, season, season_type FROM dim_games WHERE game_id=%s",
                (gid,),
            )
            print(f"   {gid}: {dict(cur.fetchone())}")

        # ② old11 gone
        cur.execute("SELECT count(*) AS c FROM dim_games WHERE game_id = ANY(%s)", (OLD11,))
        old11_count = cur.fetchone()["c"]
        print(f"\n② old11 residual: {old11_count} (want 0)")

        # ③ historical 26 unchanged
        cur.execute(
            "SELECT game_id FROM dim_games WHERE length(game_id)=11 AND season=%s ORDER BY game_id",
            (HIST_SEASON,),
        )
        hist_now = sorted(r["game_id"] for r in cur.fetchall())
        hist_count = len(hist_now)
        hist_unchanged = (hist_now == HIST_BASELINE)
        print(f"\n③ historical (season={HIST_SEASON}): count={hist_count} unchanged={hist_unchanged}")

        # ④ full-row duplicates
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name=%s ORDER BY ordinal_position",
            (BASE_TABLE,),
        )
        cols = [r["column_name"] for r in cur.fetchall()]
        ident = sql.SQL(", ").join(sql.Identifier(c) for c in cols)
        cur.execute(
            sql.SQL("SELECT COUNT(*) AS c FROM (SELECT 1 FROM {} GROUP BY {} HAVING COUNT(*)>1) t").format(
                sql.Identifier(BASE_TABLE), ident
            )
        )
        full_dups = cur.fetchone()["c"]
        print(f"\n④ full-row duplicates: {full_dups} (want 0)")

        # total rows
        cur.execute("SELECT count(*) AS c FROM dim_games")
        total = cur.fetchone()["c"]
        print(f"\n[total] dim_games rows={total} (want 70954)")

        # gates
        errors = []
        if not (bak_exists and bak_rows == 2):
            errors.append(f"backup rows={bak_rows} (want 2)")
        if new12_count != 2 or not each_unique or not present:
            errors.append("① new12 check failed")
        if old11_count != 0:
            errors.append(f"② old11={old11_count}")
        if hist_count != 26 or not hist_unchanged:
            errors.append("③ historical 26 changed")
        if full_dups != 0:
            errors.append(f"④ dups={full_dups}")
        if total != 70954:
            errors.append(f"total={total}")

        print("\n" + "=" * 72)
        if errors:
            print("IS_PASS: NO")
            for e in errors:
                print("  - " + e)
            sys.exit(1)
        print("IS_PASS: YES")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
