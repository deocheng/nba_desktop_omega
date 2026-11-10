import os
import re

import psycopg2
from psycopg2 import sql

ENV_PATH = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env"
cfg = {}
for line in open(ENV_PATH, encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    m = re.match(r"^([A-Z0-9_]+)\s*=\s*(.*)$", line)
    if m:
        cfg[m.group(1)] = m.group(2).strip().strip('"').strip("'")
conn = psycopg2.connect(host=cfg.get("DB_HOST","localhost"), port=int(cfg.get("DB_PORT",5433)),
    user=cfg.get("DB_USER","postgres"), password=cfg.get("DB_PASSWORD",""), dbname=cfg.get("DB_NAME","nba"))
conn.autocommit = True
cur = conn.cursor()
cur.execute("SET max_parallel_workers_per_gather=0")
cur.execute("SET statement_timeout='60s'")

print("=== columns ===")
cur.execute("SELECT attname, atttypid::regtype FROM pg_attribute "
            "WHERE attrelid='player_shot_chart'::regclass AND attnum>0 AND NOT attisdropped ORDER BY attnum")
cols = [c for (c, _) in cur.fetchall()]
print(cols)

cur.execute("SELECT reltuples::bigint, relkind, relpages FROM pg_class WHERE relname='player_shot_chart'")
r = cur.fetchone()
print(f"\napprox rows={r[0]}  relkind={r[1]}  pages={r[2]}")

print("\n=== pg_stats (NO table scan) ===")
cur.execute("""SELECT attname, n_distinct, null_frac, histogram_bounds
               FROM pg_stats WHERE tablename='player_shot_chart'
               ORDER BY attname""")
rows = cur.fetchall()
if not rows:
    print("  (no pg_stats — table never ANALYZEd)")
for a, nd, nf, hb in rows:
    hb_s = str(hb)
    if len(hb_s) > 160:
        hb_s = hb_s[:160] + "..."
    print(f"  {a}: n_distinct={nd} null_frac={nf}")
    print(f"      hist={hb_s}")

print("\n=== sample rows via TABLESAMPLE (bounded) ===")
try:
    cur.execute("SELECT * FROM player_shot_chart TABLESAMPLE SYSTEM (0.05) LIMIT 2")
    desc = [d[0] for d in cur.description]
    for row in cur.fetchall():
        print("  ", dict(zip(desc, row)))
except Exception as e:
    print("  tablesample failed:", type(e).__name__, str(e)[:120])
    conn.rollback()
conn.close()
