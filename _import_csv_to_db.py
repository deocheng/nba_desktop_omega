"""
Mac 端数据装载器: 把 nba_csv/*.csv 导入已建好表结构的 Postgres 库。

前置: 先执行 `psql -U postgres -d nba -f nba_schema_only.sql` 建表
       (nba_schema_only.sql 由 Windows 端 pg_dump --schema-only 生成，含 #105 的 weight 列)

用法:
    /path/to/.venv/bin/python _import_csv_to_db.py \
        [--csv-dir nba_csv] [--host localhost --port 5433 --db nba --user postgres --password postgres]

特性:
- 表名取自文件名；库里没有对应表则跳过(提示先建表)
- 表名/列名经 psycopg2.sql.Identifier 参数化，§6 合规
- 逐表 COPY FROM STDIN，大表(play_by_play 1837万行)也稳
"""
import os
import sys
import glob
import argparse
import psycopg2
from psycopg2 import sql


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--csv-dir", default=os.path.join(here, "nba_csv"))
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", default=5433, type=int)
    ap.add_argument("--db", default="nba")
    ap.add_argument("--user", default="postgres")
    ap.add_argument("--password", default="postgres")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.csv_dir, "*.csv")))
    print(f"Found {len(files)} CSV files in {args.csv_dir}", flush=True)

    conn = psycopg2.connect(host=args.host, port=args.port, dbname=args.db,
                            user=args.user, password=args.password)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE';"
    )
    existing = set(r[0] for r in cur.fetchall())

    ok = err = skip = 0
    for f in files:
        tbl = os.path.splitext(os.path.basename(f))[0]
        if tbl not in existing:
            print(f"SKIP {tbl:35} (表不在库中 — 先 psql 执行 nba_schema_only.sql)", flush=True)
            skip += 1
            continue
        q = sql.SQL("COPY {t} FROM STDIN WITH (FORMAT CSV, HEADER)").format(t=sql.Identifier(tbl))
        try:
            with open(f, "r", newline="", encoding="utf-8") as fh:
                cur.copy_expert(q, fh)
            print(f"OK   {tbl}", flush=True)
            ok += 1
        except Exception as e:
            print(f"ERR  {tbl:35} {type(e).__name__}: {str(e)[:160]}", flush=True)
            conn.rollback()
            err += 1

    conn.close()
    print(f"=== DONE === ok={ok} err={err} skip={skip}", flush=True)


if __name__ == "__main__":
    main()
