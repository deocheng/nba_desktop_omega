"""NBACore v8 — B-class recent BR id 11->12 rekey (STRICTLY 2 ids only).

Scope (per host brief):
    old11            -> new12
    20251030CHO      -> 202510300CHO
    20251201LAL      -> 202512010LAL
Rule: new12 = old11[:8] + '0' + old11[8:]   (insert literal '0' at pos 9).

Out of scope (NOT touched this round):
    * The 8 A-class 11-bit ids (PK collisions of different real games; host
      will handle separately).
    * Any historical 11-bit ids (the 26 in season=1950; left intact).
    * games_dup2026_bak and any other *_bak archive (frozen snapshots).
    * views games / game_metadata / v_unified_games (auto-derive from dim_games).
    * NO row deletion — only UPDATE re-key of the 2 target rows.

Safety (v8 §6 compliant):
    * Table name bound with psycopg2.sql.Identifier; all values via %s.
    * Single transaction: autocommit OFF; any hard-gate failure -> ROLLBACK.
    * Backup table dim_games_recent_br_id_fix_bak = the 2 target rows (CTAS),
      used as the rollback point.
    * Validations ①②③④ run in-txn, then COMMIT, then RE-verified post-commit.
"""
from __future__ import annotations

import sys
import os
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

# ── Targets (exactly 2) ──
PAIRS = [
    ("20251030CHO", "202510300CHO"),
    ("20251201LAL", "202512010LAL"),
]
OLD11 = [p[0] for p in PAIRS]
NEW12 = [p[1] for p in PAIRS]

BAK_TABLE = "dim_games_recent_br_id_fix_bak"
BASE_TABLE = "dim_games"

# The 26 historical 11-bit ids live in season=1950 (host's "1949-50/1950-51").
HIST_SEASON = 1950


def connect() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(**config.DB_CONFIG)
    conn.autocommit = False
    return conn


def get_columns(cur: RealDictCursor) -> list[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name=%s ORDER BY ordinal_position",
        (BASE_TABLE,),
    )
    return [r["column_name"] for r in cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# Pre-flight (read-only, inside the open transaction)
# ─────────────────────────────────────────────────────────────────────────────
def preflight(cur: RealDictCursor) -> dict:
    pf: dict = {}

    # a) target rows present, exactly 1 each
    cur.execute(
        "SELECT game_id, br_crawled_id, season, season_type FROM dim_games "
        "WHERE game_id = ANY(%s) ORDER BY game_id",
        (OLD11,),
    )
    rows = cur.fetchall()
    pf["target_rows"] = [dict(r) for r in rows]
    if len(rows) != 2:
        raise RuntimeError(f"expected 2 target rows, found {len(rows)}")

    # b) no 12-bit sibling AND no br_crawled_id collision
    for o, n in PAIRS:
        cur.execute("SELECT count(*) AS c FROM dim_games WHERE game_id=%s", (n,))
        if cur.fetchone()["c"] != 0:
            raise RuntimeError(f"12-bit sibling already exists for {n} (PK collision)")
        cur.execute("SELECT count(*) AS c FROM dim_games WHERE br_crawled_id=%s", (n,))
        if cur.fetchone()["c"] != 0:
            raise RuntimeError(f"br_crawled_id collision for {n}")

    # c) snapshot historical 26 (season=1950, 11-char)
    cur.execute(
        "SELECT game_id FROM dim_games "
        "WHERE length(game_id)=11 AND season=%s ORDER BY game_id",
        (HIST_SEASON,),
    )
    pf["hist_before"] = sorted(r["game_id"] for r in cur.fetchall())
    pf["hist_before_count"] = len(pf["hist_before"])

    # d) snapshot full 11-bit id set (to prove ONLY the 2 targets change)
    cur.execute("SELECT game_id FROM dim_games WHERE length(game_id)=11 ORDER BY game_id")
    pf["all11_before"] = set(r["game_id"] for r in cur.fetchall())

    # e) total row count baseline
    cur.execute("SELECT count(*) AS c FROM dim_games")
    pf["total_before"] = cur.fetchone()["c"]

    return pf


# ─────────────────────────────────────────────────────────────────────────────
# Mutating steps
# ─────────────────────────────────────────────────────────────────────────────
def backup(cur: RealDictCursor) -> None:
    cur.execute("SELECT to_regclass(%s) AS t", (f"public.{BAK_TABLE}",))
    if cur.fetchone()["t"] is not None:
        raise RuntimeError(
            f"backup table {BAK_TABLE} already exists — abort to avoid clobbering "
            f"any prior backup. Inspect/remove it manually if this is intended."
        )
    cur.execute(
        sql.SQL("CREATE TABLE {} AS SELECT * FROM {} WHERE game_id = ANY(%s)").format(
            sql.Identifier(BAK_TABLE), sql.Identifier(BASE_TABLE)
        ),
        (OLD11,),
    )


def apply_updates(cur: RealDictCursor) -> None:
    stmt = sql.SQL(
        "UPDATE {} SET game_id = %s, br_crawled_id = %s WHERE game_id = %s"
    ).format(sql.Identifier(BASE_TABLE))
    for o, n in PAIRS:
        cur.execute(stmt, (n, n, o))
        if cur.rowcount != 1:
            raise RuntimeError(f"UPDATE for {o} affected {cur.rowcount} rows (expected 1)")


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────
def validate(cur: RealDictCursor, columns: list[str], pf: dict) -> dict:
    v: dict = {}

    # ① new12 exist & unique (count=2; each exactly 1)
    cur.execute(
        "SELECT game_id, count(*) AS c FROM dim_games WHERE game_id = ANY(%s) "
        "GROUP BY game_id",
        (NEW12,),
    )
    new_rows = {r["game_id"]: r["c"] for r in cur.fetchall()}
    v["new12_count"] = sum(new_rows.values())
    v["new12_each_unique"] = all(c == 1 for c in new_rows.values())
    v["new12_present"] = set(new_rows.keys()) == set(NEW12)

    # ② old11 gone
    cur.execute("SELECT count(*) AS c FROM dim_games WHERE game_id = ANY(%s)", (OLD11,))
    v["old11_count"] = cur.fetchone()["c"]

    # ③ historical 26 unchanged
    cur.execute(
        "SELECT game_id FROM dim_games "
        "WHERE length(game_id)=11 AND season=%s ORDER BY game_id",
        (HIST_SEASON,),
    )
    hist_after = sorted(r["game_id"] for r in cur.fetchall())
    v["hist_after_count"] = len(hist_after)
    v["hist_unchanged"] = (hist_after == pf["hist_before"])

    # ④ full-row (all columns) duplicates == 0
    ident_cols = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    dup_sql = sql.SQL(
        "SELECT COUNT(*) AS c FROM ("
        "SELECT 1 FROM {} GROUP BY {} HAVING COUNT(*)>1) t"
    ).format(sql.Identifier(BASE_TABLE), ident_cols)
    cur.execute(dup_sql)
    v["full_row_dups"] = cur.fetchone()["c"]

    # bonus: total rows unchanged + 11-bit set diff == exactly the 2 targets
    cur.execute("SELECT count(*) AS c FROM dim_games")
    v["total_after"] = cur.fetchone()["c"]
    cur.execute("SELECT game_id FROM dim_games WHERE length(game_id)=11 ORDER BY game_id")
    all11_after = set(r["game_id"] for r in cur.fetchall())
    v["eleven_bit_removed"] = sorted(pf["all11_before"] - all11_after)
    v["eleven_bit_added"] = sorted(all11_after - pf["all11_before"])
    v["only_targets_changed"] = (
        v["eleven_bit_removed"] == OLD11 and v["eleven_bit_added"] == []
    )

    return v


def hard_gates_ok(v: dict) -> list[str]:
    errors: list[str] = []
    if v["new12_count"] != 2:
        errors.append(f"① new12 total count = {v['new12_count']} (want 2)")
    if not v["new12_each_unique"]:
        errors.append("① new12 not each unique")
    if not v["new12_present"]:
        errors.append(f"① new12 set mismatch: {set(NEW12)} vs {set(...)}")
    if v["old11_count"] != 0:
        errors.append(f"② old11 residual = {v['old11_count']} (want 0)")
    if v["hist_after_count"] != 26:
        errors.append(f"③ historical count = {v['hist_after_count']} (want 26)")
    if not v["hist_unchanged"]:
        errors.append("③ historical 26 ids changed")
    if v["full_row_dups"] != 0:
        errors.append(f"④ full-row duplicates = {v['full_row_dups']} (want 0)")
    if v["total_after"] != 70954:
        errors.append(f"total rows = {v['total_after']} (expected 70954 unchanged)")
    if not v["only_targets_changed"]:
        errors.append(
            f"11-bit set diff unexpected: removed={v['eleven_bit_removed']} "
            f"added={v['eleven_bit_added']}"
        )
    return errors


# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    conn = connect()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        columns = get_columns(cur)

        pf = preflight(cur)
        print("=" * 72)
        print("PRE-FLIGHT (in-txn, read-only)")
        print("=" * 72)
        print(f"  target rows: {pf['target_rows']}")
        print(f"  historical 11-bit (season={HIST_SEASON}) count = {pf['hist_before_count']}")
        print(f"  total dim_games rows = {pf['total_before']}")

        # Backup (CTAS, 2 rows)
        backup(cur)
        cur.execute(f"SELECT count(*) AS c FROM {BAK_TABLE}")
        bak_rows = cur.fetchone()["c"]
        print(f"\n[BACKUP] {BAK_TABLE} created, rows = {bak_rows}")
        if bak_rows != 2:
            raise RuntimeError(f"backup row count = {bak_rows} (want 2)")

        # Apply 2 UPDATEs
        apply_updates(cur)
        print("\n[APPLY] 2 UPDATEs executed (1 row each).")

        # Validate in-txn
        v = validate(cur, columns, pf)
        errors = hard_gates_ok(v)

        print("\n" + "=" * 72)
        print("IN-TRANSACTION VALIDATION")
        print("=" * 72)
        print(f"  ① new12 count={v['new12_count']} each_unique={v['new12_each_unique']} "
              f"present={v['new12_present']}")
        print(f"  ② old11 residual={v['old11_count']}")
        print(f"  ③ historical count={v['hist_after_count']} unchanged={v['hist_unchanged']}")
        print(f"  ④ full-row dups={v['full_row_dups']}")
        print(f"  [bonus] total={v['total_after']} 11bit_removed={v['eleven_bit_removed']} "
              f"11bit_added={v['eleven_bit_added']}")

        if errors:
            print("\nHARD-GATE FAILURES:")
            for e in errors:
                print("  - " + e)
            conn.rollback()
            print("ROLLED BACK — no changes committed.")
            sys.exit(1)

        # All gates passed -> commit
        conn.commit()
        print("\nALL HARD GATES PASSED — COMMITTED.")

        # Post-commit re-verification on a fresh connection.
        # NOTE: do NOT re-run preflight() — it asserts the OLD11 rows still
        # exist, which is false after the rekey. Reuse the in-memory `pf`
        # snapshot (hist_before / all11_before) captured pre-commit.
        conn.close()
        conn = connect()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        columns = get_columns(cur)
        # re-run validations post-commit against the original snapshot
        v2 = validate(cur, columns, pf)
        # backup row count post-commit
        cur.execute(sql.SQL("SELECT count(*) AS c FROM {}").format(sql.Identifier(BAK_TABLE)))
        bak_post = cur.fetchone()["c"]

        print("\n" + "=" * 72)
        print("POST-COMMIT RE-VERIFICATION (fresh connection)")
        print("=" * 72)
        print(f"  backup table {BAK_TABLE} rows = {bak_post}  (want 2)")
        print(f"  ① new12 count={v2['new12_count']} each_unique={v2['new12_each_unique']}")
        print(f"  ② old11 residual={v2['old11_count']}")
        print(f"  ③ historical count={v2['hist_after_count']} unchanged={v2['hist_unchanged']}")
        print(f"  ④ full-row dups={v2['full_row_dups']}")
        err2 = hard_gates_ok(v2)
        if bak_post != 2:
            err2.append(f"backup rows = {bak_post} (want 2)")
        if err2:
            print("\nPOST-COMMIT RE-VERIFICATION FAILED:")
            for e in err2:
                print("  - " + e)
            sys.exit(1)
        print("\nPOST-COMMIT RE-VERIFICATION PASSED.")
        print("\nIS_PASS: YES")
    except Exception as exc:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"\nERROR: {exc}")
        print("ROLLED BACK — no changes committed.")
        sys.exit(1)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
