"""Populate action_verb (and subtype detail) for existing BR-keyed PBP rows.

This is a LOCAL, network-free pass: it re-parses the already-stored
`description` text (which preserves the full verb) and writes:
  * action_verb -> the action word (makes/misses/rebound/enters/foul/...)
  * subtype      -> finer action detail (2-pt jump shot / Offensive rebound / ...)

Why this exists: the long BR fetch backfill (ingest_br_pbp.py) was launched
with the OLD script that did not write action_verb. Rather than re-fetch 291
games from Basketball-Reference (~3-4h), we derive the verb locally from the
description that is already in the DB.

Usage:
  python backfill_action_verb.py            # apply to all source='BBRef' rows
  python backfill_action_verb.py --dry-run  # compute + report, no DB writes
"""
from __future__ import annotations

import sys
import psycopg2
from psycopg2.extras import execute_batch, RealDictCursor
from backend.core import config
from br_pbp_parse import extract_action_verb, extract_subtype

DRY = '--dry-run' in sys.argv

conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)
cur = conn.cursor()

cur.execute("SELECT id, description FROM play_by_play WHERE source='BBRef'")
rows = cur.fetchall()
print(f"BR-keyed rows to process: {len(rows)}")

updates = []
null_verb = []
for r in rows:
    desc = r['description'] or ''
    verb = extract_action_verb(desc)
    subtype = extract_subtype(desc, verb)
    if verb is None:
        null_verb.append(desc[:70])
    updates.append((verb, subtype, r['id']))

if DRY:
    print(f"[DRY] would update {len(updates)} rows; verbs None: {len(null_verb)}")
else:
    execute_batch(cur,
        "UPDATE play_by_play SET action_verb=%s, subtype=%s WHERE id=%s",
        updates, page_size=2000)
    conn.commit()
    print(f"Updated {len(updates)} rows (action_verb + subtype).")

with_verb = sum(1 for u in updates if u[0])
print(f"rows with action_verb: {with_verb}/{len(updates)}")
if null_verb:
    print(f"\n=== {len(null_verb)} rows with NULL verb (sample) ===")
    for d in null_verb[:15]:
        print(f"  {d}")

# quick distribution
from collections import Counter
dist = Counter(u[0] for u in updates)
print("\naction_verb distribution:")
for v, c in dist.most_common():
    print(f"  {str(v):14} {c}")

conn.close()
