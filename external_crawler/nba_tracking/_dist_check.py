import os
import re

import psycopg2

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
cur.execute("SET statement_timeout='120s'")

print("=== dist_ft distribution for 3PT (shot_value=3), season 2026 RS ===")
cur.execute("""
    SELECT dist_ft, COUNT(*) AS att,
           SUM(CASE WHEN made THEN 1 ELSE 0 END) AS made
    FROM player_shot_chart
    WHERE season = 2026 AND season_type = 'Regular Season' AND shot_value = 3
    GROUP BY dist_ft ORDER BY dist_ft
""")
tot = 0
for d, a, m in cur.fetchall():
    tot += a
    print(f"   dist={d:>3}  att={a:>7}  fg%={m/a:.3f}")
print(f"   total 3PA = {tot}")

print("\n=== corner detection via x_norm (|x| large + short dist) ===")
print("   corner 3 should be: shot_value=3 AND |x_norm| near 1 AND dist<=~22")
cur.execute("""
    SELECT
      SUM(CASE WHEN shot_value=3 AND ABS(x_norm) >= 0.90 THEN 1 ELSE 0 END) AS c3_by_x,
      SUM(CASE WHEN shot_value=3 AND ABS(x_norm) >= 0.90 AND made THEN 1 ELSE 0 END) AS c3_by_x_made,
      SUM(CASE WHEN shot_value=3 AND dist_ft <= 22 THEN 1 ELSE 0 END) AS c3_by_dist,
      SUM(CASE WHEN shot_value=3 THEN 1 ELSE 0 END) AS all3
    FROM player_shot_chart
    WHERE season = 2026 AND season_type = 'Regular Season'
""")
a, am, b, c = cur.fetchone()
print(f"   3PA with |x_norm|>=0.90 : {a} (fg%={am/a:.3f})")
print(f"   3PA with dist_ft<=22    : {b}")
print(f"   total 3PA               : {c}")

print("\n=== x_norm range check (how court x is encoded) ===")
cur.execute("""
    SELECT MIN(x_norm), MAX(x_norm), MIN(y_norm), MAX(y_norm)
    FROM player_shot_chart TABLESAMPLE SYSTEM (0.5)
    WHERE season = 2026
""")
print("   x_norm min/max, y_norm min/max:", cur.fetchone())
conn.close()
