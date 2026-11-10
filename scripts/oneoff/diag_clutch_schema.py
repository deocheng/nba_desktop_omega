"""One-off schema introspection for the clutch feature (read-only)."""
from __future__ import annotations
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.core import config

conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)
cur = conn.cursor()

print("=== play_by_play columns ===")
cur.execute(
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_name='play_by_play' ORDER BY ordinal_position"
)
for c in cur.fetchall():
    print(f"  {c['column_name']:22} {c['data_type']}")

print("\n=== distinct source values ===")
cur.execute("SELECT source, COUNT(*) c FROM play_by_play GROUP BY source ORDER BY c DESC")
for r in cur.fetchall():
    print(f"  source={r['source']!r:14} c={r['c']}")

print("\n=== season column present? distinct sample ===")
cur.execute("SELECT COUNT(*) c FROM play_by_play WHERE season IS NULL")
print(f"  season NULL rows: {cur.fetchone()['c']}")
cur.execute("SELECT DISTINCT season FROM play_by_play ORDER BY season DESC LIMIT 10")
print("  seasons:", [r['season'] for r in cur.fetchall()])

print("\n=== games table season sample ===")
cur.execute("SELECT DISTINCT season FROM games ORDER BY season DESC LIMIT 12")
print("  seasons:", [r['season'] for r in cur.fetchall()])

print("\n=== clutch-ish rows sample (period=4, clock<=300) ===")
cur.execute(
    "SELECT source, event_type, subtype, scoremargin, h_pts, a_pts, clock_seconds "
    "FROM play_by_play "
    "WHERE period=4 AND clock_seconds <= 300 AND source='BBRef' "
    "AND scoremargin IS NOT NULL LIMIT 5"
)
for r in cur.fetchall():
    print(f"  BBRef ev={r['event_type']!r} sub={r['subtype']!r} sm={r['scoremargin']!r} h={r['h_pts']} a={r['a_pts']}")

cur.execute(
    "SELECT source, event_type, subtype, scoremargin, h_pts, a_pts "
    "FROM play_by_play "
    "WHERE period=4 AND clock_seconds <= 300 AND source='br_crawler' LIMIT 5"
)
for r in cur.fetchall():
    print(f"  br_crawler ev={r['event_type']!r} sub={r['subtype']!r} sm={r['scoremargin']!r} h={r['h_pts']} a={r['a_pts']}")

cur.execute(
    "SELECT source, event_type, subtype, scoremargin, h_pts, a_pts "
    "FROM play_by_play "
    "WHERE period=4 AND clock_seconds <= 300 AND source='nba_api' LIMIT 5"
)
for r in cur.fetchall():
    print(f"  nba_api ev={r['event_type']!r} sub={r['subtype']!r} sm={r['scoremargin']!r} h={r['h_pts']} a={r['a_pts']}")

print("\n=== finish-type signal check (br_crawler) ===")
cur.execute(
    "SELECT subtype, COUNT(*) c FROM play_by_play "
    "WHERE source='br_crawler' AND subtype IS NOT NULL "
    "GROUP BY subtype ORDER BY c DESC LIMIT 20"
)
for r in cur.fetchall():
    print(f"  sub={r['subtype']!r:40} c={r['c']}")

print("\n=== player / playerid nullness in clutch window ===")
cur.execute(
    "SELECT COUNT(*) c, "
    "SUM(CASE WHEN player IS NULL OR player='' THEN 1 ELSE 0 END) no_player, "
    "SUM(CASE WHEN playerid IS NULL THEN 1 ELSE 0 END) no_pid "
    "FROM play_by_play WHERE period=4 AND clock_seconds <= 300"
)
r = cur.fetchone()
print(f"  clutch rows={r['c']} no_player={r['no_player']} no_playerid={r['no_pid']}")

conn.close()
print("\nDONE")
