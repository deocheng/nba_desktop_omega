"""
Verification for task #114:
1) Re-run the clutch players query (season=2026) -> count players with player_id=NULL.
2) For the 10 previously-null clutch players, check their BBRef 2026 rows now have
   playerid / br_player_id set (at least one non-null, since clutch uses COALESCE).
"""
import os
import sys
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

ROOT = 'C:/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega'
sys.path.insert(0, ROOT)
c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                     user='postgres', password='postgres')
cur = c.cursor()

# 1) clutch players query
from backend.services.clutch_engine.clutch_queries import build_clutch_players_sql
sql, params = build_clutch_players_sql(season=2026, min_poss=10)
cur.execute(sql, params)
rows = cur.fetchall()
null_players = [r for r in rows if r[1] is None]
print("== clutch players (season=2026) total=%d  player_id=NULL=%d ==" % (len(rows), len(null_players)))
for r in null_players:
    print("   STILL_NULL: %r poss=%s" % (r[0], r[3]))

# 2) per-player backfill check
print("\n== per-player BBRef 2026 fill status (clutch-null names) ==")
names = []
tsv = os.path.join(ROOT, 'reconcile_2026-07-10', 'clutch_null_players_2026.tsv')
with open(tsv, encoding='utf-8') as f:
    next(f)
    for line in f:
        names.append(line.rstrip('\n').split('\t')[0])

for nm in names:
    cur.execute(
        """SELECT
             COUNT(*) FILTER (WHERE playerid IS NOT NULL) AS pid_set,
             COUNT(*) FILTER (WHERE br_player_id IS NOT NULL) AS brid_set,
             COUNT(*) AS total
           FROM play_by_play
           WHERE source='BBRef' AND season=2026 AND player=%s""",
        (nm,),
    )
    pid_set, brid_set, total = cur.fetchone()
    filled = pid_set + brid_set
    status = 'FILLED' if (pid_set > 0 or brid_set > 0) else 'EMPTY'
    print("   %-20s total=%-6d playerid_set=%-6d br_set=%-6d -> %s" % (nm, total, pid_set, brid_set, status))

# 3) global residual NULL among name-present rows
cur.execute(
    "SELECT COUNT(*) FROM play_by_play WHERE source='BBRef' AND season=2026 AND playerid IS NULL AND player IS NOT NULL"
)
print("\n[residual] BBRef 2026 playerid NULL & name present: %d" % cur.fetchone()[0])
c.close()
