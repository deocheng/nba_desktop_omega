"""NBACore v8 — Fix #46: normalize 241 2026 Regular Season BR ids 11->12 chars.

BACKGROUND
----------
TASK A backfill stored 241 Basketball-Reference boxscore ids in the 11-char form
(``YYYYMMDD + HHH``) in ``dim_games.game_id`` / ``dim_games.br_crawled_id``. The
correct BR form is 12 chars with a literal '0' after the 8-digit date
(``YYYYMMDD + '0' + HHH``). 91 of the 241 games also have a *legitimate* 12-char
sibling row in ``dim_games`` (from nba_api). The crawler later wrote 114,287 PBP
rows keyed on the 11-char id.

IMPORTANT (discovered via dry-run): the 241 games do NOT fall into a clean
"sibling vs not" split. For 57 games WITH NO dim_games sibling, the 12-char
``new12`` id *already carries orphan PBP* (the backfill wrote some PBP to the
12-char id too). Therefore the correct split is ORTHOGONAL, on two axes:

  AXIS 1 — PBP target: does the 12-char ``new12`` id already have PBP?
      NO  -> plain re-key:  UPDATE play_by_play SET gameid=new12 WHERE gameid=old11
      YES -> anti-join MERGE: copy old11 PBP rows whose event (NULL-safe natural
             key) is NOT already on new12 into new12; then delete old11 PBP.

  AXIS 2 — dim_games target: does a 12-char sibling dim_games row exist?
      NO  -> re-key the 11-char dim_games row to new12 (becomes canonical).
      YES -> DELETE the 11-char dim_games row (keep the sibling).

This yields four combinations (counts from dry-run):
  (PBP rekey,  dim rekey)  ~ 93 games  (clean re-key)
  (PBP merge,  dim rekey)  ~ 57 games  (orphan-PBP, no sibling)
  (PBP rekey,  dim delete) ~ 76 games  (sibling, no PBP on it)
  (PBP merge,  dim delete) ~ 15 games  (sibling, PBP on both)

NULL-SAFE DEDUP: the natural key (eventnum, period, clock_seconds, team, player,
action_verb) contains NULLs in some rows, so a plain ``=`` fails to match them.
The anti-join therefore uses ``(p2.cols) IS NOT DISTINCT FROM (p1.cols)`` so
NULLs compare equal and true duplicates are not re-inserted.

SAFETY INVARIANTS (preserved)
-----------------------------
* Single transaction: autocommit OFF. Any hard-gate failure or exception ->
  ROLLBACK + sys.exit(1).
* Idempotent backup: CREATE TABLE IF NOT EXISTS dim_games_br_id_fix_bak AS
  SELECT * FROM dim_games WHERE <241-row predicate>  (real run only, pre-write).
* INSERT column list introspected from information_schema at runtime and asserted
  == (all play_by_play columns - serial 'id'), so no NOT NULL column is omitted.
* Commit-time validation (validate()): hard gates ① 11-char residual==0,
  ② old11 PBP residual==0, ③ new12 PBP >= 114287 AND 100% JOIN dim_games (no
  orphan), ④ canonical 12-char rows == 241, ⑤ no full-row (excl id/gameid)
  duplicate among the 241 new12 ids. The exact ==115021 and br_crawled_id-12-char
  sub-assertions are RELAXED to report-only (per TL).

USAGE
-----
    python reconcile_2026-07-10/fix_br_id_11to12.py --dry-run   # txn, ROLLBACK
    python reconcile_2026-07-10/fix_br_id_11to12.py             # real run (COMMIT)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPT_DIR: Path = Path(__file__).resolve().parent
OMEGA: Path = SCRIPT_DIR.parent
sys.path.insert(0, str(OMEGA))
os.chdir(str(OMEGA))

for _p in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_p, None)

from backend.core import config  # noqa: E402

import psycopg2  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402

SEASON: int = 2026
SEASON_TYPE: str = "Regular Season"

OLD_ID_RE: str = r"^[0-9]{8}[A-Z]{3}$"
NEW_ID_RE: str = r"^[0-9]{8}0[A-Z]{3}$"

PREDICATE: str = (
    "season = %(season)s "
    "AND season_type = %(season_type)s "
    "AND nba_api_id IS NULL "
    "AND game_id ~ %(old_id_re)s"
)

BAK_TABLE: str = "dim_games_br_id_fix_bak"

EXPECTED_DIM_ROWS: int = 241
EXPECTED_PBP_ROWS: int = 114287

# Natural key (NULL-safe) used for the anti-half-join dedup.
NK_COLS = ["eventnum", "period", "clock_seconds", "team", "player", "action_verb"]


def connect() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(**config.DB_CONFIG)
    conn.autocommit = False
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Identify + convert
# ─────────────────────────────────────────────────────────────────────────────
def fetch_old_ids(cur: RealDictCursor) -> list[str]:
    cur.execute(
        "SELECT game_id FROM dim_games WHERE " + PREDICATE + " ORDER BY game_id",
        {"season": SEASON, "season_type": SEASON_TYPE, "old_id_re": OLD_ID_RE},
    )
    return [r["game_id"] for r in cur.fetchall()]


def convert(old11: str) -> str:
    if len(old11) != 11 or not old11[:8].isdigit() or not old11[8:].isalpha():
        raise ValueError(f"not an 11-char BR id: {old11!r}")
    return old11[:8] + "0" + old11[8:]


def introspect_pbp_columns(cur: RealDictCursor):
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='play_by_play' ORDER BY ordinal_position"
    )
    all_cols = [r["column_name"] for r in cur.fetchall()]
    if "id" not in all_cols:
        raise RuntimeError("play_by_play has no 'id' column")
    insert_cols = [c for c in all_cols if c != "id"]
    fr_cols = [c for c in all_cols if c not in ("id", "gameid")]
    assert set(insert_cols) == set(all_cols) - {"id"}, "insert_cols != all - {id}"
    return all_cols, insert_cols, fr_cols


def classify(cur: RealDictCursor, old11: list[str]):
    """Orthogonal split on (has PBP on new12) x (has dim_games sibling).

    Returns a dict keyed by (pbp_merge:bool, dim_delete:bool) -> list[(o,n)].
    pbp_merge True  => anti-join merge; False => plain re-key.
    dim_delete True => delete 11-char dim_games row; False => re-key dim row.
    """
    buckets: dict = {(False, False): [], (True, False): [],
                     (False, True): [], (True, True): []}
    for o in old11:
        n = convert(o)
        cur.execute("SELECT count(*) AS c FROM dim_games WHERE game_id=%s", (n,))
        has_sib = cur.fetchone()["c"] > 0
        cur.execute("SELECT count(*) AS c FROM play_by_play WHERE gameid=%s", (n,))
        has_pbp12 = cur.fetchone()["c"] > 0
        buckets[(has_pbp12, has_sib)].append((o, n))
    return buckets


def pbp_count_on(cur: RealDictCursor, ids: list[str]) -> int:
    if not ids:
        return 0
    cur.execute("SELECT count(*) AS c FROM play_by_play WHERE gameid = ANY(%s)", (ids,))
    return cur.fetchone()["c"]


# ─────────────────────────────────────────────────────────────────────────────
# Mutating steps (all run inside the open transaction)
# ─────────────────────────────────────────────────────────────────────────────
def backup(cur: RealDictCursor) -> None:
    cur.execute(
        "CREATE TABLE IF NOT EXISTS " + BAK_TABLE + " AS "
        "SELECT * FROM dim_games WHERE " + PREDICATE,
        {"season": SEASON, "season_type": SEASON_TYPE, "old_id_re": OLD_ID_RE},
    )


def apply_all(cur: RealDictCursor, buckets: dict, insert_cols: list) -> dict:
    """Execute the 2x2 migration. Returns per-bucket rowcount tallies."""
    col_list = ", ".join(insert_cols)
    select_list = ", ".join(
        "%(n)s" if c == "gameid" else f"p1.{c}" for c in insert_cols
    )
    nk_p1 = "(" + ",".join(f"p1.{c}" for c in NK_COLS) + ")"
    nk_p2 = "(" + ",".join(f"p2.{c}" for c in NK_COLS) + ")"
    # NULL-safe anti-join: IS NOT DISTINCT FROM treats NULLs as equal.
    ins_sql = (
        f"INSERT INTO play_by_play ({col_list}) "
        f"SELECT {select_list} FROM play_by_play p1 "
        f"WHERE p1.gameid=%(o)s AND NOT EXISTS ("
        f"SELECT 1 FROM play_by_play p2 WHERE p2.gameid=%(n)s AND "
        f"{nk_p2} IS NOT DISTINCT FROM {nk_p1})"
    )

    tally = {}
    for (pbp_merge, dim_delete), pairs in buckets.items():
        t = {"pbp_rekeyed": 0, "pbp_inserted": 0, "pbp_deleted": 0,
             "dim_rekeyed": 0, "dim_deleted": 0, "games": len(pairs)}
        for o, n in pairs:
            if pbp_merge:
                cur.execute(ins_sql, {"n": n, "o": o})
                t["pbp_inserted"] += cur.rowcount if cur.rowcount >= 0 else 0
                cur.execute("DELETE FROM play_by_play WHERE gameid=%s", (o,))
                t["pbp_deleted"] += cur.rowcount if cur.rowcount >= 0 else 0
            else:
                cur.execute("UPDATE play_by_play SET gameid=%s WHERE gameid=%s", (n, o))
                t["pbp_rekeyed"] += cur.rowcount if cur.rowcount >= 0 else 0
            if dim_delete:
                cur.execute("DELETE FROM dim_games WHERE game_id=%s", (o,))
                t["dim_deleted"] += cur.rowcount if cur.rowcount >= 0 else 0
            else:
                cur.execute(
                    "UPDATE dim_games SET game_id=%s, br_crawled_id=%s WHERE game_id=%s",
                    (n, n, o),
                )
                t["dim_rekeyed"] += cur.rowcount if cur.rowcount >= 0 else 0
        tally[(pbp_merge, dim_delete)] = t
    return tally


def validate(cur: RealDictCursor, old11: list, new12_all: list, fr_cols: list) -> dict:
    cur.execute("SELECT count(*) AS c FROM dim_games WHERE game_id = ANY(%s)", (old11,))
    residual11 = cur.fetchone()["c"]
    cur.execute("SELECT count(*) AS c FROM play_by_play WHERE gameid = ANY(%s)", (old11,))
    pbp_old11 = cur.fetchone()["c"]

    cur.execute("SELECT count(*) AS c FROM play_by_play WHERE gameid = ANY(%s)", (new12_all,))
    pbp_new12 = cur.fetchone()["c"]
    cur.execute(
        "SELECT count(*) AS c FROM play_by_play p "
        "JOIN dim_games g ON p.gameid = g.game_id WHERE p.gameid = ANY(%s)",
        (new12_all,),
    )
    pbp_joined = cur.fetchone()["c"]

    cur.execute("SELECT count(*) AS c FROM dim_games WHERE game_id = ANY(%s)", (new12_all,))
    canon = cur.fetchone()["c"]
    cur.execute(
        "SELECT count(*) AS c FROM dim_games WHERE game_id = ANY(%s) AND br_crawled_id ~ %s",
        (new12_all, NEW_ID_RE),
    )
    br12 = cur.fetchone()["c"]

    # ⑤ full-row (excl id/gameid) duplicate guard across ALL 241 new12 ids.
    fr_sql = ", ".join(fr_cols)
    full_dups = 0
    for n in new12_all:
        cur.execute(
            f"SELECT count(*) AS c FROM ("
            f"SELECT {fr_sql} FROM play_by_play WHERE gameid=%s "
            f"GROUP BY {fr_sql} HAVING count(*)>1) t",
            (n,),
        )
        full_dups += cur.fetchone()["c"]

    return {
        "residual11": residual11,
        "pbp_old11": pbp_old11,
        "pbp_new12": pbp_new12,
        "pbp_joined": pbp_joined,
        "canon": canon,
        "br12": br12,
        "full_dups": full_dups,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix #46: normalize 241 2026 RS BR ids 11->12 chars (2x2 scheme)."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Transactional dry-run: write in txn, validate, ROLL BACK.")
    args = parser.parse_args()

    conn = connect()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        old11 = fetch_old_ids(cur)
        if len(old11) != EXPECTED_DIM_ROWS:
            print(f"[WARN] dim_games target rows = {len(old11)} "
                  f"(expected {EXPECTED_DIM_ROWS}).")
        new12_all = [convert(o) for o in old11]

        all_cols, insert_cols, fr_cols = introspect_pbp_columns(cur)
        buckets = classify(cur, old11)
        n_rekey_pbp = len(buckets[(False, False)]) + len(buckets[(False, True)])
        n_merge_pbp = len(buckets[(True, False)]) + len(buckets[(True, True)])
        n_dim_rekey = len(buckets[(False, False)]) + len(buckets[(True, False)])
        n_dim_del = len(buckets[(False, True)]) + len(buckets[(True, True)])

        print("=" * 64)
        print(f"PRE-CHECK (#46 / {SEASON} {SEASON_TYPE})")
        print("=" * 64)
        print(f"  play_by_play columns      : {len(all_cols)} "
              f"(insert excl 'id' = {len(insert_cols)})")
        print(f"  dim_games rows to migrate : {len(old11)}")
        print(f"  PBP axis  : rekey={n_rekey_pbp}  merge={n_merge_pbp}")
        print(f"  DIM axis  : rekey={n_dim_rekey}  delete={n_dim_del}")
        print(f"  buckets:")
        for k, v in buckets.items():
            print(f"    pbp_merge={k[0]} dim_delete={k[1]} : {len(v)} games")

        if not args.dry_run:
            backup(cur)

        tally = apply_all(cur, buckets, insert_cols)
        v = validate(cur, old11, new12_all, fr_cols)

        print("=" * 64)
        banner = ("DRY-RUN (transaction ROLLED BACK — nothing committed)"
                  if args.dry_run else "EXECUTION RESULT (pre-commit validate)")
        print(banner)
        print("=" * 64)
        for k, t in tally.items():
            print(f"  [pbp_merge={k[0]} dim_delete={k[1]}] games={t['games']} "
                  f"pbp_rekey={t['pbp_rekeyed']} pbp_ins={t['pbp_inserted']} "
                  f"pbp_del={t['pbp_deleted']} dim_rekey={t['dim_rekeyed']} "
                  f"dim_del={t['dim_deleted']}")
        print("  --- validate ---")
        print(f"  ① 11-char residual       : {v['residual11']}  (hard == 0)")
        print(f"  ② old11 PBP residual     : {v['pbp_old11']}  (hard == 0)")
        print(f"  ③ new12 PBP total        : {v['pbp_new12']}  (hard >= {EXPECTED_PBP_ROWS})")
        print(f"     100%-JOIN             : {v['pbp_joined']}/{v['pbp_new12']}")
        print(f"  ④ canonical rows (==241) : {v['canon']}  (hard == 241)")
        print(f"     br_crawled_id 12-char : {v['br12']}  (report-only)")
        print(f"  ⑤ full-row dup (all 241) : {v['full_dups']}  (hard == 0)")

        errors: list[str] = []
        if v["residual11"] != 0:
            errors.append(f"① 11-char residual = {v['residual11']}")
        if v["pbp_old11"] != 0:
            errors.append(f"② old11 PBP residual = {v['pbp_old11']}")
        if v["pbp_new12"] < EXPECTED_PBP_ROWS:
            errors.append(f"③ new12 PBP = {v['pbp_new12']} < {EXPECTED_PBP_ROWS}")
        if v["pbp_joined"] != v["pbp_new12"]:
            errors.append(f"③ orphan PBP: joined {v['pbp_joined']} != total {v['pbp_new12']}")
        if v["canon"] != EXPECTED_DIM_ROWS:
            errors.append(f"④ canonical rows = {v['canon']} (want {EXPECTED_DIM_ROWS})")
        if v["full_dups"] != 0:
            errors.append(f"⑤ full-row duplicate = {v['full_dups']} (want 0)")

        if args.dry_run:
            status = "PASS" if not errors else "FAIL -> " + "; ".join(errors)
            print(f"\n[DRY-RUN] Hard-gate check (informational): {status}")
            print("[DRY-RUN] ROLLING BACK — no changes committed.")
            conn.rollback()
            return

        if errors:
            print("\nVALIDATION FAILED:")
            for e in errors:
                print("  - " + e)
            conn.rollback()
            print("ROLLED BACK — no changes committed.")
            sys.exit(1)
        conn.commit()
        print("\nVALIDATION PASSED — committed.")
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"\nERROR during migration: {exc}")
        print("ROLLED BACK — no changes committed.")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
