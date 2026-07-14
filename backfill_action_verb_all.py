"""Backfill play_by_play.action_verb for ALL rows (not just BR-keyed).

The action_verb column was added 2026-07-09 and only the 136K BR-backfilled
rows were filled. The 18M existing rows (source=nba_api / br_crawler) carry
action info in event_type / description but not in the normalized action_verb
column. This script derives action_verb from those existing fields — NO network,
NO re-crawl (nba.com is blocked anyway).

Two passes:
  Pass 1: CASE on LOWER(TRIM(event_type)) — covers ~99% of rows.
  Pass 2: description-based fallback for rows still NULL (br_crawler rows
          whose event_type was NULL).
"""
from __future__ import annotations
import psycopg2
from backend.core import config

conn = psycopg2.connect(**config.DB_CONFIG)
conn.autocommit = False
cur = conn.cursor()

# ---- Pass 1: map from event_type (case-insensitive) ----
# 2pt/3pt need description peek: "MISS" prefix => misses, else makes.
SQL_PASS1 = """
UPDATE play_by_play
SET action_verb = CASE
    WHEN LOWER(TRIM(event_type)) IN ('2pt','3pt') THEN
        CASE WHEN description LIKE 'MISS%' THEN 'misses' ELSE 'makes' END
    ELSE CASE LOWER(TRIM(event_type))
        WHEN 'made shot'      THEN 'makes'
        WHEN 'missed shot'    THEN 'misses'
        WHEN 'rebound'        THEN 'rebound'
        WHEN 'turnover'       THEN 'turnover'
        WHEN 'foul'           THEN 'foul'
        WHEN 'violation'      THEN 'violation'
        WHEN 'substitution'   THEN 'enters'
        WHEN 'timeout'        THEN 'timeout'
        WHEN 'jump ball'      THEN 'jump ball'
        WHEN 'jumpball'       THEN 'jump ball'
        WHEN 'instant replay' THEN 'instant replay'
        WHEN 'ejection'       THEN 'ejected'
        WHEN 'period'         THEN 'period'
        WHEN 'start of period' THEN 'period'
        WHEN 'end of period'  THEN 'period'
        WHEN 'end of game'    THEN 'period'
        WHEN 'game'           THEN 'period'
        WHEN 'steal'          THEN 'steal'
        WHEN 'block'          THEN 'block'
        WHEN 'heave'          THEN 'heave'
        WHEN 'freethrow'      THEN 'free throw'
        WHEN 'free throw'     THEN 'free throw'
        WHEN 'other'          THEN 'other'
        ELSE NULL
    END
END
WHERE source IN ('nba_api','br_crawler')
  AND action_verb IS NULL
  AND event_type IS NOT NULL
  AND TRIM(event_type) <> ''
"""
cur.execute(SQL_PASS1)
p1 = cur.rowcount
conn.commit()
print(f"Pass1 (event_type map): updated {p1:,} rows")

# ---- Pass 2: description fallback for still-NULL rows (br_crawler, event_type NULL) ----
SQL_PASS2 = """
UPDATE play_by_play
SET action_verb = CASE
    WHEN description LIKE 'SUB:%'                     THEN 'enters'
    WHEN description LIKE 'MISS%'                     THEN 'misses'
    WHEN description LIKE '%STEAL%'                   THEN 'steal'
    WHEN description LIKE '%BLOCK%'                   THEN 'block'
    WHEN description LIKE '%Free Throw%'              THEN 'free throw'
    WHEN description LIKE '%REBOUND%'
      OR description LIKE '%bounds%'                  THEN 'rebound'
    WHEN description LIKE '%Turnover%'
      OR description LIKE 'TO:%'                      THEN 'turnover'
    WHEN description LIKE '%Timeout%'                 THEN 'timeout'
    WHEN description LIKE '%Jump Ball%'               THEN 'jump ball'
    WHEN description LIKE 'Game End%'
      OR description LIKE 'End of%'                   THEN 'period'
    WHEN description LIKE '%Foul%'                    THEN 'foul'
    WHEN description LIKE '%makes%'
      OR description LIKE '%DUNK%'
      OR description LIKE '%PTS)%'                     THEN 'makes'
    ELSE NULL
END
WHERE source = 'br_crawler'
  AND action_verb IS NULL
  AND event_type IS NULL
  AND description IS NOT NULL
"""
cur.execute(SQL_PASS2)
p2 = cur.rowcount
conn.commit()
print(f"Pass2 (description fallback): updated {p2:,} rows")

# ---- Report coverage ----
cur.execute("""
    SELECT source, COUNT(*) total, COUNT(action_verb) with_verb
    FROM play_by_play GROUP BY source ORDER BY total DESC
""")
print("\n=== action_verb coverage by source (after backfill) ===")
tot = wv = 0
for r in cur.fetchall():
    pct = (r[2] / r[1] * 100) if r[1] else 0
    print(f"  {str(r[0]):14} {r[1]:>13,} {r[2]:>13,} {pct:5.1f}%")
    tot += r[1]; wv += r[2]
print(f"  {'TOTAL':14} {tot:>13,} {wv:>13,} {wv/tot*100:5.1f}%")

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
