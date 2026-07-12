"""
EDWARD (QA) independent verification for task #114.
Runs REAL DB queries. Does NOT reuse the engineer's _verify_114.py logic blindly;
re-derives every number from scratch.
"""
import os
import sys

for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

ROOT = 'C:/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                     user='postgres', password='postgres')
cur = c.cursor()
print("== CONNECTION OK ==\n")

def one(sql, params=None):
    cur.execute(sql, params or ())
    return cur.fetchone()[0]

# ---- Q1: BBRef 2026 playerid IS NULL (expect ~101,206) ----
q1 = one(
    "SELECT COUNT(*) FROM play_by_play WHERE source=%s AND season=%s AND playerid IS NULL",
    ('BBRef', 2026),
)
q1_no_name = one(
    "SELECT COUNT(*) FROM play_by_play WHERE source=%s AND season=%s AND playerid IS NULL AND player IS NULL",
    ('BBRef', 2026),
)
q1_name = q1 - q1_no_name
print("[Q1] BBRef 2026 playerid IS NULL = %d  (name-NULL=%d, name-present=%d)" % (q1, q1_no_name, q1_name))

# ---- Q2: nba_api / br_crawler untouched ----
q2_nba_null = one(
    "SELECT COUNT(*) FROM play_by_play WHERE source=%s AND season=%s AND playerid IS NULL",
    ('nba_api', 2026),
)
q2_crawl_null = one(
    "SELECT COUNT(*) FROM play_by_play WHERE source=%s AND season=%s AND playerid IS NULL",
    ('br_crawler', 2026),
)
q2_nba_set = one(
    "SELECT COUNT(*) FROM play_by_play WHERE source=%s AND season=%s AND playerid IS NOT NULL",
    ('nba_api', 2026),
)
q2_crawl_set = one(
    "SELECT COUNT(*) FROM play_by_play WHERE source=%s AND season=%s AND playerid IS NOT NULL",
    ('br_crawler', 2026),
)
print("[Q2] nba_api   2026 playerid NULL=%d / IS NOT NULL=%d" % (q2_nba_null, q2_nba_set))
print("[Q2] br_crawler 2026 playerid NULL=%d / IS NOT NULL=%d" % (q2_crawl_null, q2_crawl_set))

# ---- Q3: residual BBRef 2026 NULL grouped by player (top 30) ----
cur.execute(
    "SELECT player, COUNT(*) FROM play_by_play "
    "WHERE source=%s AND season=%s AND playerid IS NULL AND player IS NOT NULL "
    "GROUP BY player ORDER BY COUNT(*) DESC LIMIT 30",
    ('BBRef', 2026),
)
residual = cur.fetchall()
print("\n[Q3] Top residual BBRef 2026 playerid-NULL names (player, rows):")
for p, n in residual:
    print("    %-22s %d" % (p, n))
print("[Q3] distinct residual name buckets (name-present): %d" % len(residual))

# ---- Q4: clutch aggregation, independent ----
print("\n[Q4] Clutch aggregation (using build_clutch_players_sql if available):")
null_names = []
try:
    from backend.services.clutch_engine.clutch_queries import build_clutch_players_sql
    sql, params = build_clutch_players_sql(season=2026, min_poss=10)
    cur.execute(sql, params)
    rows = cur.fetchall()
    # try to identify columns: assume (player, player_id, poss, ...)
    for r in rows:
        pid = r[1]
        if pid is None:
            null_names.append(r[0])
    print("    total clutch players=%d  player_id=NULL=%d" % (len(rows), len(null_names)))
    for r in rows:
        if r[1] is None:
            print("    STILL_NULL: player=%r  pid=%r  row=%r" % (r[0], r[1], r))
except Exception as e:
    print("    build_clutch_players_sql failed: %s" % e)

# ---- Q5: per the 10 clutch_null names, BBRef 2026 fill status ----
print("\n[Q5] Per clutch_null_players_2026.tsv name -> BBRef 2026 fill status:")
tsv = os.path.join(HERE, 'clutch_null_players_2026.tsv')
with open(tsv, encoding='utf-8') as f:
    next(f)
    names = [ln.rstrip('\n').split('\t')[0] for ln in f]
filled = 0
for nm in names:
    cur.execute(
        "SELECT COUNT(*) FILTER (WHERE playerid IS NOT NULL), "
        "       COUNT(*) FILTER (WHERE br_player_id IS NOT NULL), "
        "       COUNT(*) "
        "FROM play_by_play WHERE source=%s AND season=%s AND player=%s",
        ('BBRef', 2026, nm),
    )
    pid_set, brid_set, total = cur.fetchone()
    status = 'FILLED' if (pid_set > 0 or brid_set > 0) else 'EMPTY'
    if status == 'FILLED':
        filled += 1
    print("    %-14s total=%-6d playerid_set=%-6d br_set=%-6d -> %s" % (nm, total, pid_set, brid_set, status))
print("    => %d/%d FILLED among original clutch-null names" % (filled, len(names)))

c.close()
print("\n== DONE ==")
