"""Inspect play_by_play schema + how event_type/subtype/description are used."""
from __future__ import annotations
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.core import config

conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)
cur = conn.cursor()

# columns
cur.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_name='play_by_play' ORDER BY ordinal_position
""")
cols = cur.fetchall()
print("=== play_by_play columns ===")
for c in cols:
    print(f"  {c['column_name']:20} {c['data_type']:12} nullable={c['is_nullable']}")

# subtype usage in existing (non-BR) rows
cur.execute("SELECT COUNT(*) c FROM play_by_play")
print(f"\ntotal rows: {cur.fetchone()['c']}")
cur.execute("SELECT COUNT(*) c FROM play_by_play WHERE subtype IS NOT NULL")
print(f"rows with subtype NOT NULL: {cur.fetchone()['c']}")
cur.execute("SELECT COUNT(*) c FROM play_by_play WHERE source='BBRef'")
print(f"rows source='BBRef': {cur.fetchone()['c']}")

# sample existing (nba_api) event_type/subtype
print("\n=== sample non-BR event_type/subtype (existing nba_api rows) ===")
cur.execute("""
    SELECT event_type, subtype, COUNT(*) c
    FROM play_by_play WHERE source <> 'BBRef' AND subtype IS NOT NULL
    GROUP BY event_type, subtype ORDER BY c DESC LIMIT 15
""")
for r in cur.fetchall():
    print(f"  event_type={r['event_type']!r:18} subtype={r['subtype']!r:14} c={r['c']}")

# sample BR descriptions to design verb extraction
print("\n=== sample BR (BBRef) descriptions (raw, to design verb parse) ===")
cur.execute("""
    SELECT description FROM play_by_play WHERE source='BBRef'
    AND description IS NOT NULL ORDER BY random() LIMIT 25
""")
for r in cur.fetchall():
    print(f"  {r['description'][:80]}")
conn.close()
