"""
Task B: br_crawler assist backfill (ADDITIVE, low-risk).

For br_crawler made shots (event_type IN ('2pt','3pt','Made Shot')) whose
description contains a parenthetical assist like "(N. Jokić 8 AST)", extract the
assister name and UPDATE player2_name (and best-effort player2_id).

Only rows where player2_name IS NULL are touched. nba_api rows are never touched.

Builds a name->playerid map from rows that DO have playerid (br_crawler + nba_api),
normalizing names so "Initial. Lastname" from the description matches.
"""
import os
import re
import sys
import unicodedata
from collections import defaultdict

for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

COMMIT = '--commit' in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))

# Assist pattern (br_crawler real format): (assist by F. Wagner)
AST_RE = re.compile(r"\(assist by ([A-Z][\w.'\- ]+?)\)", re.IGNORECASE)


def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    return s.lower().replace('.', '').replace("'", '').replace('-', '').replace(' ', '')


def build_map(cur):
    """name(normalized 'initial.lastname') -> set(playerid) from rows WITH playerid."""
    m = defaultdict(set)
    # br_crawler: player is already 'Initial. Lastname'
    cur.execute("""SELECT player, playerid FROM play_by_play
                   WHERE source='br_crawler' AND player IS NOT NULL AND playerid IS NOT NULL""")
    for p, pid in cur.fetchall():
        if pid is not None:
            m[norm(p)].add(str(pid))
    # nba_api: player is full name 'First Last' -> derive 'Initial. Last'
    cur.execute("""SELECT player, playerid FROM play_by_play
                   WHERE source='nba_api' AND player IS NOT NULL AND playerid IS NOT NULL""")
    for p, pid in cur.fetchall():
        if pid is None:
            continue
        parts = str(p).split()
        if len(parts) >= 2:
            key = parts[0][0].upper() + '.' + parts[-1]
            m[norm(key)].add(str(pid))
    return m


def main():
    c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                         user='postgres', password='postgres')
    cur = c.cursor()

    amap = build_map(cur)
    unique = {k: next(iter(v)) for k, v in amap.items() if len(v) == 1}
    ambiguous = {k: v for k, v in amap.items() if len(v) > 1}
    print(f"[map] name entries={len(amap)} unique={len(unique)} ambiguous={len(ambiguous)}")

    # Candidate rows: br_crawler made shots, player2_name NULL, description has 'assist by'
    cur.execute("""SELECT id, description FROM play_by_play
                   WHERE source='br_crawler'
                     AND event_type IN ('2pt','3pt','Made Shot')
                     AND player2_name IS NULL
                     AND description LIKE '%assist by%'""")
    rows = cur.fetchall()
    print(f"[candidates] br_crawler made shots with AST description & player2_name NULL: {len(rows)}")

    updates = []          # (player2_name, player2_id_or_None, id)
    unmatched = defaultdict(int)
    for rid, desc in rows:
        m = AST_RE.search(desc or '')
        if not m:
            continue
        name = m.group(1).strip()
        pid = unique.get(norm(name))
        if pid is None:
            if norm(name) in ambiguous:
                unmatched[name + ' [AMBIGUOUS]'] += 1
            else:
                unmatched[name + ' [NO-MAP]'] += 1
            # still set player2_name (the assister name is real), leave player2_id NULL
            updates.append((name, None, rid))
        else:
            updates.append((name, pid, rid))

    print(f"[plan] rows to UPDATE player2_name: {len(updates)}")
    print(f"[plan] of those with resolved player2_id: {sum(1 for _,p,_ in updates if p)}")
    print(f"[plan] unmatched-name buckets: {len(unmatched)}")
    for nm, cnt in sorted(unmatched.items(), key=lambda x: -x[1])[:15]:
        print(f"    {nm}: {cnt}")

    if not COMMIT:
        print("\n*** DRY RUN (no changes). Re-run with --commit to apply. ***")
        c.close()
        return

    # Apply updates
    n_name = n_id = 0
    for name, pid, rid in updates:
        cur.execute("UPDATE play_by_play SET player2_name=%s, player2_id=%s WHERE id=%s",
                    (name, pid, rid))
        n_name += 1
        if pid:
            n_id += 1
    c.commit()
    print(f"\n[APPLIED] player2_name set on {n_name} rows; player2_id resolved on {n_id} rows.")

    # New AST coverage for br_crawler makes
    cur.execute("""SELECT COUNT(*) FROM play_by_play
                   WHERE source='br_crawler' AND event_type IN ('2pt','3pt','Made Shot')""")
    made_total = cur.fetchone()[0]
    cur.execute("""SELECT COUNT(*) FROM play_by_play
                   WHERE source='br_crawler' AND event_type IN ('2pt','3pt','Made Shot')
                     AND player2_name IS NOT NULL""")
    with_name = cur.fetchone()[0]
    print(f"[coverage] br_crawler made shots={made_total} now have player2_name={with_name} "
          f"({100.0*with_name/made_total:.3f}%)")
    print(f"[unmatched] distinct unmatched assister-name buckets logged above: {len(unmatched)}")
    c.close()


if __name__ == '__main__':
    main()
