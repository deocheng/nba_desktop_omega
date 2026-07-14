"""
Task C: clutch playerid backfill for BBRef rows (ADDITIVE, low-risk).

BBRef-source PBP rows have playerid=NULL. clutch_engine groups by playerid, so
BBRef rows split one real player into phantom groups (e.g. Jokić 203999/DEN vs a
BBRef null-playerid group mislabeled TOR), corrupting clutch FG%.

Build a name->playerid map from rows that DO have playerid (br_crawler + nba_api),
normalizing the 'Initial. Lastname' form. For BBRef rows where playerid IS NULL
(and player IS NOT NULL), match by normalized name -> UPDATE playerid.

Only BBRef rows are touched. Rows that already have playerid are never altered.
Ambiguous names (map has >1 playerid) are left NULL and logged.
"""
import os
import sys
import unicodedata
from collections import defaultdict

for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

COMMIT = '--commit' in sys.argv


def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    return s.lower().replace('.', '').replace("'", '').replace('-', '').replace(' ', '')


def build_map(cur):
    m = defaultdict(set)
    # br_crawler: player is 'Initial. Lastname'
    cur.execute("""SELECT player, playerid FROM play_by_play
                   WHERE source='br_crawler' AND player IS NOT NULL AND playerid IS NOT NULL""")
    for p, pid in cur.fetchall():
        if pid is not None:
            m[norm(p)].add(str(pid))
    # nba_api: player is full 'First Last' -> derive 'Initial. Last'
    cur.execute("""SELECT player, playerid FROM play_by_play
                   WHERE source='nba_api' AND player IS NOT NULL AND playerid IS NOT NULL""")
    for p, pid in cur.fetchall():
        if pid is None:
            continue
        parts = str(p).split()
        if len(parts) >= 2:
            m[norm(parts[0][0].upper() + '.' + parts[-1])].add(str(pid))
    return m


def main():
    c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                         user='postgres', password=os.environ.get('DB_PASSWORD'))
    cur = c.cursor()

    amap = build_map(cur)
    unique = {k: next(iter(v)) for k, v in amap.items() if len(v) == 1}
    ambiguous = {k: v for k, v in amap.items() if len(v) > 1}
    print(f"[map] name entries={len(amap)} unique={len(unique)} ambiguous={len(ambiguous)}")

    # Candidate BBRef rows: playerid NULL, player NOT NULL
    cur.execute("""SELECT id, player FROM play_by_play
                   WHERE source='BBRef' AND playerid IS NULL AND player IS NOT NULL""")
    rows = cur.fetchall()
    print(f"[candidates] BBRef rows playerid NULL & player NOT NULL: {len(rows)}")

    updates = []           # (playerid, id)
    unmatched = defaultdict(int)
    for rid, p in rows:
        pid = unique.get(norm(p))
        if pid is None:
            if norm(p) in ambiguous:
                unmatched[p + ' [AMBIGUOUS]'] += 1
            else:
                unmatched[p + ' [NO-MAP]'] += 1
            continue
        updates.append((pid, rid))

    print(f"[plan] rows to UPDATE playerid: {len(updates)}")
    print(f"[plan] unmatched-name buckets: {len(unmatched)}")
    for nm, cnt in sorted(unmatched.items(), key=lambda x: -x[1])[:15]:
        print(f"    {nm}: {cnt}")

    if not COMMIT:
        print("\n*** DRY RUN (no changes). Re-run with --commit to apply. ***")
        c.close()
        return

    n = 0
    for pid, rid in updates:
        cur.execute("UPDATE play_by_play SET playerid=%s WHERE id=%s", (pid, rid))
        n += 1
    c.commit()
    print(f"\n[APPLIED] playerid set on {n} BBRef rows.")

    # Remaining BBRef null playerid (after)
    cur.execute("""SELECT COUNT(*) FROM play_by_play WHERE source='BBRef' AND playerid IS NULL""")
    still_null = cur.fetchone()[0]
    print(f"[after] BBRef rows still playerid NULL: {still_null}")
    print(f"[unmatched] distinct unmatched name buckets: {len(unmatched)}")
    c.close()


if __name__ == '__main__':
    main()
