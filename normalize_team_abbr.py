import os
"""
Normalize NBA team abbreviations to the canonical (NBA API) style.

Mapping (user-specified 2026-07-10):
  BKN -> BRK   (篮网 Nets)
  CHA -> CHO   (黄蜂 Hornets)
  PHX -> PHO   (太阳 Suns)

Scope:
  - Only BASE TABLES (excludes VIEWs and *_bak / *dup* snapshots).
  - Only exact-value matches (col IN ('BKN','CHA','PHX')); no substring replace.
  - Idempotent: after one run no BKN/CHA/PHX remain, so re-running touches 0 rows.

Tables with a PK that includes the abbreviation (player_contracts, team_payroll)
may contain TRUE DUPLICATES: an old-abbr row plus a canonical-abbr twin for the
same entity. For those we DELETE the redundant old-abbr row (the canonical twin
already carries the data) instead of renaming into a PK collision.

Each table is committed independently so a failure on one table cannot roll back
the others.

Run:
  cd <project root>
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
      .venv/Scripts/python.exe normalize_team_abbr.py
"""
import psycopg2

DB = dict(host="localhost", port=5433, dbname="nba", user="postgres", password=os.environ.get("DB_PASSWORD"))
MAPPING = [("BKN", "BRK"), ("CHA", "CHO"), ("PHX", "PHO")]
OLD = [o for o, _ in MAPPING]
TEXT_TYPES = ("character varying", "character", "text")

# Tables whose PK includes the abbreviation -> old-abbr rows can collide with a
# canonical twin. Key columns (excluding the abbreviation) identify the entity.
DEDUP_KEYS = {
    "player_contracts": ["season", "player_id"],
    "team_payroll": ["season"],
}


def case_expr(operand):
    return "(CASE " + operand + " " + " ".join(
        f"WHEN '{o}' THEN '{n}'" for o, n in MAPPING
    ) + " END)"


def dedup_and_normalize(cur, t):
    """For a PK-on-abbr table: delete redundant old-abbr rows that have a
    canonical twin, then rename any remaining old-abbr rows."""
    keys = DEDUP_KEYS.get(t)
    if not keys:
        return 0
    new_abbr = case_expr("d.team_abbr")
    key_eq = " AND ".join(f"b.{k} = d.{k}" for k in keys)
    del_sql = f"""
        DELETE FROM {t} d
        WHERE d.team_abbr IN ('BKN','CHA','PHX')
          AND EXISTS (
            SELECT 1 FROM {t} b
            WHERE {key_eq}
              AND b.team_abbr = {new_abbr}
          )
    """
    cur.execute(del_sql)
    n_del = cur.rowcount
    upd_sql = f"UPDATE {t} SET team_abbr = {case_expr('team_abbr')} WHERE team_abbr IN ('BKN','CHA','PHX')"
    cur.execute(upd_sql)
    n_upd = cur.rowcount
    return n_del + n_upd


def main():
    conn = psycopg2.connect(**DB)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("""
        SELECT c.table_name, c.column_name, c.data_type
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = 'public'
          AND t.table_type = 'BASE TABLE'
          AND (c.column_name ILIKE '%abbr%' OR c.column_name = 'team'
               OR c.column_name ILIKE '%_team' OR c.column_name ILIKE '%team_name%')
          AND c.table_name NOT LIKE '%_bak%'
          AND c.table_name NOT LIKE '%dup%'
        ORDER BY c.table_name, c.column_name
    """)
    raw = cur.fetchall()

    from collections import defaultdict
    bytable = defaultdict(list)
    skipped_type = []
    for t, c, dt in raw:
        if dt not in TEXT_TYPES:
            skipped_type.append((t, c, dt))
            continue
        bytable[t].append(c)

    if skipped_type:
        print("Skipped non-text columns (safe):")
        for t, c, dt in skipped_type:
            print(f"  {t}.{c} ({dt})")

    total = 0
    report = []
    failed = []
    for t, cols in sorted(bytable.items()):
        try:
            if t in DEDUP_KEYS:
                n = dedup_and_normalize(cur, t)
            else:
                sets = []
                wheres = []
                for c in cols:
                    sets.append(f"{c} = {case_expr(c)}")
                    wheres.append(f"{c} IN ('BKN','CHA','PHX')")
                sql = f"UPDATE {t} SET {', '.join(sets)} WHERE {' OR '.join(wheres)}"
                cur.execute(sql)
                n = cur.rowcount
        except psycopg2.errors.IntegrityError as e:
            conn.rollback()
            failed.append((t, "IntegrityError: " + str(e).splitlines()[0]))
            continue
        except Exception as e:
            conn.rollback()
            failed.append((t, str(e).splitlines()[0] if str(e) else str(e)))
            continue
        conn.commit()
        if n > 0:
            total += n
            report.append((t, n, list(cols)))

    print(f"\nTOTAL rows affected: {total}\n")
    for t, n, cols in report:
        print(f"  {t:40} rows={n:9,}  cols={cols}")
    if failed:
        print("\nFAILED tables (need manual review):")
        for t, msg in failed:
            print(f"  {t:40} {msg}")

    # verification
    cur.execute("""
        SELECT c.table_name, c.column_name
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = 'public'
          AND t.table_type = 'BASE TABLE'
          AND (c.column_name ILIKE '%abbr%' OR c.column_name = 'team'
               OR c.column_name ILIKE '%_team' OR c.column_name ILIKE '%team_name%')
          AND c.data_type IN ('character varying', 'character', 'text')
          AND c.table_name NOT LIKE '%_bak%'
          AND c.table_name NOT LIKE '%dup%'
    """)
    remain = []
    for (t, c) in cur.fetchall():
        cur.execute(f"SELECT count(*) FROM {t} WHERE {c} IN ('BKN','CHA','PHX')")
        n = cur.fetchone()[0]
        if n > 0:
            remain.append((t, c, n))
    print("\n=== REMAINING BKN/CHA/PHX in base tables ===")
    if not remain:
        print("  NONE - all unified to BRK/CHO/PHO.")
    else:
        for t, c, n in remain:
            print(f"  {t}.{c} = {n}")
    conn.close()


if __name__ == "__main__":
    main()
