#!/usr/bin/env python3
"""Export all DB tables to CSV in /Volumes/12T/NBA/backups/csv/.

- Regular tables (relkind='r') and partitioned parents (relkind='p') are exported.
- Partition children are skipped (parent SELECT covers them).
- Uses server-side COPY TO STDOUT streaming (no temp memory blowup).
"""
import csv
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
from dotenv import load_dotenv

load_dotenv()
import psycopg2

OUT_DIR = Path("/Volumes/12T/NBA/backups/csv")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DSN = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres",
           password=os.environ["DB_PASSWORD"])

def get_tables(cur):
    """All standalone tables + partitioned parents, exclude partition children."""
    cur.execute("""
        SELECT n.nspname, c.relname, c.reltuples::bigint,
               pg_total_relation_size(c.oid) AS bytes
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p')
          AND n.nspname IN ('public', 'analytics')
          AND NOT EXISTS (
              SELECT 1 FROM pg_inherits inh
              WHERE inh.inhrelid = c.oid
          )
        ORDER BY pg_total_relation_size(c.oid) DESC
    """)
    return cur.fetchall()

def human_size(n):
    for unit in ('B','KB','MB','GB'):
        if n < 1024: return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

def export_table(conn, schema, table):
    fname = f"{schema}.{table}.csv"
    fpath = OUT_DIR / fname
    cur = conn.cursor()
    # Quote schema.table for SQL safety
    ident = f'"{schema}"."{table}"'
    sql = f"COPY {ident} TO STDOUT WITH (FORMAT CSV, HEADER TRUE)"
    t0 = time.time()
    with open(fpath, 'wb') as f:
        cur.copy_expert(sql, f)
    elapsed = time.time() - t0
    fsize = fpath.stat().st_size
    cur.close()
    return fsize, elapsed

def main():
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    tables = get_tables(cur)
    print(f"Total tables to export: {len(tables)}")
    print(f"Output dir: {OUT_DIR}")
    print(f"{'#':>3} {'schema.table':<45} {'rows':>12} {'db_size':>10} {'csv_size':>10} {'time':>8}")
    print("-" * 95)

    total_db_bytes = 0
    total_csv_bytes = 0
    total_time = 0
    errors = []

    for i, (schema, table, rows, db_bytes) in enumerate(tables, 1):
        total_db_bytes += db_bytes
        name = f"{schema}.{table}"
        try:
            csv_bytes, elapsed = export_table(conn, schema, table)
            total_csv_bytes += csv_bytes
            total_time += elapsed
            print(f"{i:>3} {name:<45} {rows:>12,} {human_size(db_bytes):>10} "
                  f"{human_size(csv_bytes):>10} {elapsed:>7.1f}s", flush=True)
        except Exception as e:
            errors.append((name, str(e)))
            print(f"{i:>3} {name:<45} {rows:>12,} {human_size(db_bytes):>10} "
                  f"ERROR: {e}", flush=True)
            conn.rollback()

    print("-" * 95)
    print(f"Done: {len(tables)} tables, DB size {human_size(total_db_bytes)}, "
          f"CSV total {human_size(total_csv_bytes)}, time {total_time:.0f}s")
    if errors:
        print(f"Errors: {len(errors)}")
        for name, err in errors:
            print(f"  {name}: {err}")
    # Write manifest
    manifest_path = OUT_DIR / "_manifest.txt"
    with open(manifest_path, 'w') as f:
        f.write(f"Export date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Tables: {len(tables)}\n")
        f.write(f"DB total: {human_size(total_db_bytes)}\n")
        f.write(f"CSV total: {human_size(total_csv_bytes)}\n")
        f.write(f"Errors: {len(errors)}\n\n")
        for i, (schema, table, rows, db_bytes) in enumerate(tables, 1):
            fname = f"{schema}.{table}.csv"
            fsize = (OUT_DIR / fname).stat().st_size if (OUT_DIR / fname).exists() else 0
            f.write(f"{i:>3} {fname:<50} {rows:>12,} rows  {human_size(fsize):>10}\n")
    conn.close()

if __name__ == "__main__":
    main()
