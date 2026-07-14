"""
Export every base table in the `public` schema of the nba DB to a CSV file
under nba_csv/ (project root). Same-named files are overwritten.

Usage:
    env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
        .venv/Scripts/python.exe _export_tables_to_csv.py [--out DIR]

Notes:
- Uses PostgreSQL server-side COPY (SELECT * FROM {table}) TO STDOUT WITH (FORMAT CSV, HEADER)
  for maximum throughput on large tables (play_by_play ~18M rows).
- Table name is injected via psycopg2.sql.Identifier (parameterized -> no SQL injection, §6 compliant).
- Encoding utf-8, Unix newlines (\n). One file per table, overwritten if present.
"""
import os
import sys
import time
import psycopg2
from psycopg2 import sql

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(PROJECT_ROOT, "nba_csv")

DB = dict(host="localhost", port=5433, dbname="nba", user="postgres", password=os.environ.get("DB_PASSWORD"))


def main():
    out_dir = DEFAULT_OUT
    if "--out" in sys.argv:
        out_dir = sys.argv[sys.argv.index("--out") + 1]
    os.makedirs(out_dir, exist_ok=True)

    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name;"
    )
    tables = [r[0] for r in cur.fetchall()]
    print(f"Found {len(tables)} base tables in public. Export dir = {out_dir}", flush=True)

    total_start = time.time()
    ok, err = 0, 0
    for t in tables:
        path = os.path.join(out_dir, t + ".csv")
        q = sql.SQL("COPY (SELECT * FROM {t}) TO STDOUT WITH (FORMAT CSV, HEADER)").format(
            t=sql.Identifier(t)
        )
        try:
            start = time.time()
            with open(path, "w", newline="", encoding="utf-8") as f:
                cur.copy_expert(q, f)
            size = os.path.getsize(path)
            ok += 1
            print(f"OK   {t:35} {size/1e6:9.1f} MB  {round(time.time()-start,1):5.1f}s", flush=True)
        except Exception as e:
            err += 1
            # cleanup partial file on failure
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            print(f"ERR  {t:35} {type(e).__name__}: {str(e)[:160]}", flush=True)

    conn.close()
    elapsed = round(time.time() - total_start, 1)
    print("=== DONE ===", flush=True)
    print(f"tables={len(tables)} ok={ok} err={err} elapsed={elapsed}s", flush=True)


if __name__ == "__main__":
    main()
