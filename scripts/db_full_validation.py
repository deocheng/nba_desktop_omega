"""NBA 数据库全量校验 v2（只读，OOM 安全，逐表容错，进度落盘）。
- reltuples 近似行数
- season 跨度用 MIN/MAX（若有索引=O(1)），COUNT(DISTINCT season) 改为可选
- max_parallel_workers_per_gather=0
- 每表结果立即写文件 flush，遇错跳过不中断
"""
import re, json, psycopg2, sys

ROOT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
PROG = f"{ROOT}/logs/db_validation_20260810.log"

def g(k):
    m = re.search(r'^%s=(.*)' % k, open(f"{ROOT}/.env").read(), re.I | re.M)
    return m.group(1).strip().strip('"').strip("'") if m else None

def log(s):
    with open(PROG, "a") as f:
        f.write(s + "\n")
        f.flush()

log("="*100)
log("全量校验开始")

conn = psycopg2.connect(host=g('DB_HOST') or '127.0.0.1', port=int(g('DB_PORT') or 5433),
                        user=g('DB_USER') or 'postgres', password=g('DB_PASSWORD'),
                        dbname=g('DB_NAME') or 'nba', connect_timeout=10)
conn.set_session(autocommit=True)
cur = conn.cursor()
cur.execute("SET max_parallel_workers_per_gather=0")

cur.execute("""
SELECT c.relname, c.reltuples::bigint,
       (SELECT COUNT(*) FROM information_schema.columns k
         WHERE k.table_name=c.relname AND k.column_name='season') AS has_season
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind='r' AND n.nspname='public'
ORDER BY c.relname
""")
tables = cur.fetchall()
log(f"总表数 = {len(tables)}")

out = []
for name, approx, has_season in tables:
    info = {"table": name, "approx_rows": int(approx or 0), "has_season": has_season == 1}
    if has_season:
        try:
            cur.execute(f"SELECT MIN(season), MAX(season) FROM {name}")
            lo, hi = cur.fetchone()
            info["season_min"] = lo
            info["season_max"] = hi
            # COUNT(DISTINCT season) 仅在表不太大时做（用 reltuples 阈值防 OOM）
            if (approx or 0) < 5_000_000:
                cur.execute(f"SELECT COUNT(DISTINCT season) FROM {name}")
                info["season_count"] = cur.fetchone()[0]
            else:
                info["season_count"] = "skip(>5M)"
        except Exception as e:
            conn.rollback()
            info["season_err"] = str(e)[:80]
    out.append(info)
    log(f"{name:38} ~{info['approx_rows']:>12,}  season={info.get('season_min')}~{info.get('season_max')} ({info.get('season_count')})")

# PBP 分区覆盖（双键 OR）
log("\n" + "="*60 + " PBP 分区覆盖（双键 OR，已验证方法）")
pbp = []
for y in range(1997, 2027):
    t = f"play_by_play_p_{y}"
    cur.execute(f"SELECT to_regclass('public.{t}')")
    if not cur.fetchone()[0]:
        continue
    try:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        total = cur.fetchone()[0]
        cur.execute(f"SELECT DISTINCT gameid FROM {t}")
        pids = set(r[0] for r in cur.fetchall())
        cur.execute("SELECT nba_api_id::text, game_id FROM dim_games WHERE season=%s", (y,))
        covered = dim_n = 0
        for nid, gid in cur.fetchall():
            dim_n += 1
            if (nid and nid in pids) or (gid and gid in pids):
                covered += 1
        cov = round(covered / dim_n * 100, 1) if dim_n else None
        pbp.append({"partition": t, "rows": total, "distinct_games": len(pids),
                    "dim_games": dim_n, "covered": covered, "coverage_pct": cov})
        log(f"{t:22} rows={total:>9,} games={len(pids):>5,} dim={dim_n:>5,} cov={cov}%")
    except Exception as e:
        conn.rollback()
        log(f"{t:22} ERR {str(e)[:80]}")

empties = [r['table'] for r in out if r['approx_rows'] == 0]
bk = [r['table'] for r in out if '_bak' in r['table']]
f404 = [r['table'] for r in out if '404' in r['table']]
log("\n" + "="*60)
log(f"空表(0行) = {len(empties)}: {empties}")
log(f"_bak 备份表 = {len(bk)}: {bk}")
log(f"_404 残留表 = {len(f404)}: {f404}")

with open(f"{ROOT}/logs/db_validation_20260810.json", "w") as f:
    json.dump({"tables": out, "pbp": pbp}, f, indent=2, default=str)
log("JSON 已写 logs/db_validation_20260810.json")
log("全量校验完成")
print("DONE - 见", PROG)
