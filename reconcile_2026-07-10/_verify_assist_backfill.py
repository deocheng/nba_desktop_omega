"""Independent verification of the br_crawler assist backfill (TASK B).
Checks whether player2_name was actually populated for the '(assist by X)' rows,
which is the format the user confirmed (NOT the '(N. Jokic 8 AST)' nba_api format).
"""
import os
import re
import psycopg2

for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)

c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                     user='postgres', password='postgres')
cur = c.cursor()

# 1. br_crawler made shots: total / with player2_name / null
cur.execute("""SELECT count(*) FROM play_by_play
               WHERE source='br_crawler' AND event_type IN ('2pt','3pt','Made Shot')""")
total = cur.fetchone()[0]
cur.execute("""SELECT count(*) FROM play_by_play
               WHERE source='br_crawler' AND event_type IN ('2pt','3pt','Made Shot')
                 AND player2_name IS NOT NULL""")
with_name = cur.fetchone()[0]
cur.execute("""SELECT count(*) FROM play_by_play
               WHERE source='br_crawler' AND event_type IN ('2pt','3pt','Made Shot')
                 AND player2_name IS NULL""")
null_name = cur.fetchone()[0]
print(f"[br_crawler makes] total={total} with_player2_name={with_name} null_player2_name={null_name}")

# 2. Of the NULL player2_name rows, how many have the confirmed '(assist by X)' format?
cur.execute("""SELECT count(*) FROM play_by_play
               WHERE source='br_crawler' AND event_type IN ('2pt','3pt','Made Shot')
                 AND player2_name IS NULL AND description LIKE '%assist by%'""")
null_assist_by = cur.fetchone()[0]
print(f"[gap] null player2_name AND description LIKE '%assist by%' = {null_assist_by}")

# 3. How many br_crawler made shots have the OLD 'N AST' format (what the agent's regex targeted)?
cur.execute("""SELECT count(*) FROM play_by_play
               WHERE source='br_crawler' AND event_type IN ('2pt','3pt','Made Shot')
                 AND description ~ '\\([A-Z]\\.? .*\\d+ AST\\)'""")
old_fmt = cur.fetchone()[0]
print(f"[old fmt] br_crawler made shots with '(N. X N AST)' = {old_fmt}")

# 4. Sample of backfilled rows: does player2_name match the 'assist by X' name in description?
ASSIST_RE = re.compile(r"assist by ([A-Z][\w.\'-]+(?:\s+[A-Z][\w.\'-]+)*)", re.IGNORECASE)
cur.execute("""SELECT player2_name, description FROM play_by_play
               WHERE source='br_crawler' AND event_type IN ('2pt','3pt','Made Shot')
                 AND player2_name IS NOT NULL
               ORDER BY id LIMIT 15""")
print("\n[sample backfilled rows] player2_name | description")
mismatch = 0
for name, desc in cur.fetchall():
    m = ASSIST_RE.search(desc or '')
    expected = m.group(1).strip() if m else None
    flag = '' if (expected and name and expected.lower() in name.lower()) else '  <-- MISMATCH?'
    if flag:
        mismatch += 1
    print(f"  {name!r:24} | {desc!r}{flag}")
print(f"[sample] mismatches in first 15: {mismatch}")

c.close()
