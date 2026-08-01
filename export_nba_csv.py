#!/usr/bin/env python3
"""
全量导出 nba(5433) 库中 public 模式所有 BASE TABLE 为独立 CSV。
- 每张表 -> <outdir>/<table>.csv（含表头）
- 流式 COPY TO STDOUT，不占内存
- 输出 manifest.csv（表名 / 行估算 / 文件字节 / 状态）
"""
import os
import sys
import time
import psycopg2

DB = dict(host="127.0.0.1", port=5433, dbname="nba",
          user="postgres", password=os.environ["DB_PASSWORD"])
OUTDIR = "/Volumes/12T/NBA/csv_export_2026-07-23"
MANIFEST = os.path.join(OUTDIR, "manifest.csv")


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public' AND table_type='BASE TABLE'
        ORDER BY table_name
    """)
    tables = [r[0] for r in cur.fetchall()]
    print(f"[info] 共 {len(tables)} 张表待导出", flush=True)

    manifest_rows = []
    total_bytes = 0
    ok = 0
    fail = 0

    for i, t in enumerate(tables, 1):
        path = os.path.join(OUTDIR, f"{t}.csv")
        t0 = time.time()
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                sql = f'COPY (SELECT * FROM public."{t}") TO STDOUT WITH (FORMAT CSV, HEADER)'
                cur.copy_expert(sql, f)
            size = os.path.getsize(path)
            total_bytes += size
            dur = time.time() - t0
            manifest_rows.append((t, "OK", size, f"{dur:.1f}s"))
            ok += 1
            print(f"[{i}/{len(tables)}] ✅ {t}  {size/1024/1024:.1f} MB  ({dur:.1f}s)", flush=True)
        except Exception as e:
            manifest_rows.append((t, f"FAIL: {e}", 0, ""))
            fail += 1
            print(f"[{i}/{len(tables)}] ❌ {t}  {e}", flush=True)

    cur.close()
    conn.close()

    with open(MANIFEST, "w", encoding="utf-8", newline="") as f:
        f.write("table,status,bytes,seconds\n")
        for r in manifest_rows:
            f.write(",".join(str(x) for x in r) + "\n")
        f.write(f"\n# total_csv_bytes,{total_bytes}\n")
        f.write(f"# tables_ok,{ok}\n")
        f.write(f"# tables_fail,{fail}\n")

    print(f"\n[done] 导出完成：OK={ok} FAIL={fail}  CSV总大小={total_bytes/1024/1024/1024:.2f} GB", flush=True)
    print(f"[done] 清单：{MANIFEST}", flush=True)


if __name__ == "__main__":
    main()
