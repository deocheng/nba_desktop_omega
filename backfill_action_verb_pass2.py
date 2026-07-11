"""Pass 2 only: backfill action_verb for br_crawler rows whose event_type is NULL
but description is present. Idempotent — only touches rows still NULL.

Run after backfill_action_verb_all.py Pass1 (or standalone re-run; safe).
"""
from __future__ import annotations
import sys
import psycopg2
from backend.core import config

SQL_PASS2 = """
UPDATE play_by_play
SET action_verb = CASE
    WHEN description ILIKE 'SUB:%'                     THEN 'enters'
    WHEN description ILIKE 'MISS%'                     THEN 'misses'
    WHEN description ILIKE '%misses%'                  THEN 'misses'
    WHEN description ILIKE '%steal%'                   THEN 'steal'
    WHEN description ILIKE '%block%'                   THEN 'block'
    WHEN description ILIKE '%free throw%'              THEN 'free throw'
    WHEN description ILIKE '%rebound%'
      OR description ILIKE '%bounds%'                  THEN 'rebound'
    WHEN description ILIKE '%turnover%'
      OR description ILIKE 'TO:%'                      THEN 'turnover'
    WHEN description ILIKE '%timeout%'                 THEN 'timeout'
    WHEN description ILIKE '%jump ball%'               THEN 'jump ball'
    WHEN description ILIKE 'Game End%'
      OR description ILIKE 'End of%'                   THEN 'period'
    WHEN description ILIKE '%foul%'                    THEN 'foul'
    WHEN description ILIKE '%makes%'
      OR description ILIKE '%dunk%'
      OR description ILIKE '%pts)%'                     THEN 'makes'
    ELSE NULL
END
WHERE source = 'br_crawler'
  AND action_verb IS NULL
  AND event_type IS NULL
  AND description IS NOT NULL
"""

def main():
    conn = psycopg2.connect(**config.DB_CONFIG)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute(SQL_PASS2)
    p2 = cur.rowcount
    conn.commit()
    print(f"Pass2 (description fallback): updated {p2:,} rows", flush=True)

    cur.execute("""
        SELECT source, COUNT(*) total, COUNT(action_verb) with_verb
        FROM play_by_play GROUP BY source ORDER BY total DESC
    """)
    print("\n=== action_verb coverage by source ===")
    tot = wv = 0
    for r in cur.fetchall():
        pct = (r[2] / r[1] * 100) if r[1] else 0
        print(f"  {str(r[0]):14} {r[1]:>13,} {r[2]:>13,} {pct:6.2f}%")
        tot += r[1]; wv += r[2]
    print(f"  {'TOTAL':14} {tot:>13,} {wv:>13,} {wv/tot*100:6.2f}%")

    cur.execute("SELECT COUNT(*) FROM play_by_play WHERE action_verb IS NULL")
    print(f"\nRows still NULL: {cur.fetchone()[0]:,}")

    cur.execute("""
        SELECT action_verb, COUNT(*) c FROM play_by_play
        WHERE action_verb IS NOT NULL GROUP BY action_verb ORDER BY c DESC
    """)
    print("\nVerb distribution (all sources):")
    for e in cur.fetchall():
        print(f"  {str(e[0]):14} {e[1]:>13,}")
    conn.close()

if __name__ == '__main__':
    main()
