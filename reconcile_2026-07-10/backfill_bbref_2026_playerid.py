"""
Task #114: backfill BBRef 2026 play_by_play playerid (and br_player_id).

CONTEXT
=======
NBACore v8 clutch engine groups by ``COALESCE(playerid, br_player_id)`` (see
backend/services/clutch_engine/clutch_queries.py, already fixed in #109). For
BBRef 2026 source rows the upstream ETL left ``playerid``/``br_player_id``/
``player1_id`` ALL NULL, so some clutch players still surface with player_id=NULL.

This script backfills those rows by matching the BBRef ``player`` name
('Initial. Lastname' form) to canonical IDs:

  * ``playerid``  (NBA.com numeric id)  <- built from br_crawler / nba_api rows
    that already carry a numeric playerid for the same normalized name.
    (dim_players.player_id stores the BBRef *slug*, not the NBA numeric id, so
     it cannot feed the numeric ``playerid`` column; the proven reference
     script backfill_bbref_playerid.py sources the numeric id from other PBP
     sources, which we reuse here.)
  * ``br_player_id`` (BBRef slug)        <- built from TWO canonical sources:
       (a) br_crawler.br_player_id  -- the authoritative BBRef slug, already in
           the SAME 'Initial. Lastname' name-space as BBRef PBP (exact match);
       (b) dim_players.player_id    -- the canonical BBRef slug, indexed BOTH by
           exact full name AND by a derived 'Initial. Lastname' key so abbreviated
           BBRef names (e.g. 'J. Jaquez') match full dim names ('Jaime Jaquez').
    dim_players has NO br_player_id column; its player_id IS the BBRef slug,
    so it is the right table for the slug, just needs the abbrev bridge.

Both columns are set when resolvable; ambiguous names (map has >1 id) and
name-NULL rows are left NULL and logged. Names with Cyrillic letters
(e.g. 'E. Dёmin') are transliterated before normalization so they match
their Latin canonical forms.

COMPLIANCE (§6 red line)
========================
* Parameterized SQL only (psycopg2 %s placeholders). Table/column identifiers
  are fixed literals, never concatenated from data. No eval/exec, no f-string SQL.
* Only BBRef + season=2026 rows are touched (WHERE source='BBRef' AND
  season=2026 AND playerid IS NULL). nba_api / br_crawler are read-only sources.
* clutch_queries.py is NOT modified.

USAGE
=====
  python backfill_bbref_2026_playerid.py            # dry-run (default)
  python backfill_bbref_2026_playerid.py --execute  # apply + commit
"""
import os
import sys
import unicodedata
from collections import defaultdict

for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
EXECUTE = '--execute' in sys.argv

# Fixed values used as SQL parameters (never concatenated into SQL text).
SOURCE_VAL = 'BBRef'
SEASON_VAL = 2026

# Minimal Cyrillic -> Latin transliteration for NBA player names.
_CYR = {
    'ё': 'e', 'е': 'e', 'а': 'a', 'о': 'o', 'р': 'p', 'с': 'c', 'у': 'y',
    'к': 'k', 'х': 'x', 'в': 'b', 'м': 'm', 'н': 'n', 'т': 't', 'д': 'd',
    'и': 'i', 'г': 'r', 'з': 'z', 'л': 'l', 'б': 'b', 'ю': 'yu', 'я': 'ya',
    'ш': 'sh', 'щ': 'sch', 'ж': 'zh', 'ч': 'ch', 'й': 'i', 'ы': 'y',
    'ъ': '', 'ь': '', 'ф': 'f', 'э': 'e', 'п': 'p',
}


def strip_suffix(name):
    """Drop a trailing generational suffix (Jr/Sr/II/III/IV/V) so that
    'Jaime Jaquez Jr.' and 'J. Jaquez' reduce to the same comparable key."""
    if name is None:
        return None
    tokens = str(name).split()
    while tokens and tokens[-1].strip('.').upper() in ('JR', 'SR', 'II', 'III', 'IV', 'V'):
        tokens = tokens[:-1]
    return ' '.join(tokens)


def norm(s):
    """Normalize a player name to a comparable key.

    Strips generational suffixes, transliterates Cyrillic, then NFKD +
    ASCII-folds, lowercases, and strips punctuation/spaces so that
    'J. Jaquez', 'Jaime Jaquez Jr.' and 'E. Dёmin' all reduce to stable
    comparable keys.
    """
    if s is None:
        return None
    s = strip_suffix(s)
    if any(ord(ch) > 127 for ch in s):
        s = ''.join(_CYR.get(ch, ch) for ch in s)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    return s.lower().replace('.', '').replace("'", '').replace('-', '').replace(' ', '')


def derived_key(full_name):
    """From a full name ('Jaime Jaquez Jr.') produce the 'Initial.Lastname' key ('jjaquez')."""
    base = strip_suffix(full_name)
    parts = str(base).split()
    if len(parts) < 2:
        return None
    return norm(parts[0][0] + '.' + parts[-1])


def build_nba_map(cur):
    """name -> set of NBA.com numeric playerids, from br_crawler + nba_api rows that have one."""
    m = defaultdict(set)
    for src in ('br_crawler', 'nba_api'):
        cur.execute(
            "SELECT player, playerid FROM play_by_play "
            "WHERE source=%s AND player IS NOT NULL AND playerid IS NOT NULL",
            (src,),
        )
        for p, pid in cur.fetchall():
            if pid is not None:
                m[norm(p)].add(str(pid))
    return m


def build_br_map(cur):
    """name -> set of BBRef slugs, from br_crawler.br_player_id (exact abbrev space)
    merged with dim_players.player_id (exact full name + derived 'Initial.Lastname')."""
    m = defaultdict(set)
    # (a) br_crawler carries the authoritative BBRef slug in the same abbrev space.
    cur.execute(
        "SELECT player, br_player_id FROM play_by_play "
        "WHERE source='br_crawler' AND player IS NOT NULL AND br_player_id IS NOT NULL"
    )
    for p, brid in cur.fetchall():
        if brid is not None:
            m[norm(p)].add(str(brid))
    # (b) dim_players.player_id IS the BBRef slug; index by exact + derived abbrev.
    #     For hyphenated surnames (e.g. 'Alexander-Walker') also index the first
    #     part so BBRef's truncated 'N. Alexander' can match 'Nickeil Alexander-Walker'.
    cur.execute("SELECT player_name, player_id FROM dim_players")
    for nm, pid in cur.fetchall():
        if nm is None or pid is None:
            continue
        m[norm(nm)].add(str(pid))
        dk = derived_key(nm)
        if dk:
            m[dk].add(str(pid))
        parts = strip_suffix(nm).split()
        if len(parts) >= 2:
            last = parts[-1]
            if '-' in last:
                first_part = last.split('-')[0]
                hk = norm(parts[0][0] + '.' + first_part)
                if hk:
                    m[hk].add(str(pid))
    return m


def main():
    c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                         user='postgres', password='postgres')
    cur = c.cursor()

    nba_map = build_nba_map(cur)
    br_map = build_br_map(cur)
    nba_unique = {k: next(iter(v)) for k, v in nba_map.items() if len(v) == 1}
    nba_amb = {k: v for k, v in nba_map.items() if len(v) > 1}
    br_unique = {k: next(iter(v)) for k, v in br_map.items() if len(v) == 1}
    br_amb = {k: v for k, v in br_map.items() if len(v) > 1}
    print("[map] nba(numeric) entries=%d unique=%d ambiguous=%d"
          % (len(nba_map), len(nba_unique), len(nba_amb)))
    print("[map] br(slug)     entries=%d unique=%d ambiguous=%d"
          % (len(br_map), len(br_unique), len(br_amb)))

    # Totals (for the report)
    cur.execute(
        "SELECT COUNT(*) FROM play_by_play WHERE source=%s AND season=%s AND playerid IS NULL",
        (SOURCE_VAL, SEASON_VAL),
    )
    total_null = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FILTER (WHERE player IS NULL) AS no_name, "
        "COUNT(*) FILTER (WHERE player IS NOT NULL) AS with_name "
        "FROM play_by_play WHERE source=%s AND season=%s AND playerid IS NULL",
        (SOURCE_VAL, SEASON_VAL),
    )
    no_name_rows, with_name_rows = cur.fetchone()
    print("[totals] BBRef season=%d playerid NULL: %d (name-NULL=%d, name-present=%d)"
          % (SEASON_VAL, total_null, no_name_rows, with_name_rows))

    # Candidate distinct names with their row counts
    cur.execute(
        "SELECT player, COUNT(*) FROM play_by_play "
        "WHERE source=%s AND season=%s AND playerid IS NULL AND player IS NOT NULL "
        "GROUP BY player",
        (SOURCE_VAL, SEASON_VAL),
    )
    name_rows = cur.fetchall()

    updates = []           # (nba_id_or_None, br_id_or_None, player_name)
    unresolved = {}        # "player_name [REASON]" -> row_count
    for pname, rcnt in name_rows:
        k = norm(pname)
        nba_id = nba_unique.get(k) if k in nba_unique else None
        br_id = br_unique.get(k) if k in br_unique else None
        if nba_id is None and br_id is None:
            reason = 'AMBIGUOUS' if (k in nba_amb or k in br_amb) else 'NO-MAP'
            unresolved["%s [%s]" % (pname, reason)] = rcnt
            continue
        updates.append((nba_id, br_id, pname))

    # Map each candidate name to its row count for quick aggregation.
    name_count = {p: rc for p, rc in name_rows}
    resolvable_rows = sum(name_count[p] for (_n, _b, p) in updates)
    unresolvable_rows = no_name_rows + sum(unresolved.values())

    print("[plan] distinct names with player: %d" % len(name_rows))
    print("[plan] resolvable names: %d  -> rows to UPDATE: %d" % (len(updates), resolvable_rows))
    print("[plan] unresolvable rows: %d (name-NULL=%d + ambiguous/no-map=%d)"
          % (unresolvable_rows, no_name_rows, sum(unresolved.values())))
    print("[plan] unresolved distinct name buckets: %d" % len(unresolved))
    for nm, cnt in sorted(unresolved.items(), key=lambda x: -x[1])[:25]:
        print("    UNRESOLVED: %s : %d" % (nm, cnt))

    # Report resolution specifically for the known clutch-null players (verification aid)
    try:
        tsv = os.path.join(HERE, 'clutch_null_players_2026.tsv')
        if os.path.exists(tsv):
            print("[check] clutch-null player name resolution:")
            with open(tsv, encoding='utf-8') as f:
                next(f)
                for line in f:
                    nm = line.rstrip('\n').split('\t')[0]
                    k = norm(nm)
                    nid = nba_unique.get(k)
                    bid = br_unique.get(k)
                    if nid or bid:
                        status = 'OK'
                    elif k in nba_amb or k in br_amb:
                        status = 'AMBIGUOUS'
                    else:
                        status = 'NO-MAP'
                    print("    %-20s nba=%s br=%s -> %s" % (nm, nid, bid, status))
    except Exception as e:
        print("[check] could not read clutch_null_players_2026.tsv: %s" % e)

    if not EXECUTE:
        print("\n*** DRY RUN (no changes). Re-run with --execute to apply. ***")
        c.close()
        return

    # ---- EXECUTE ----
    n_rows = 0
    for nba_id, br_id, pname in updates:
        cur.execute(
            "UPDATE play_by_play SET playerid=%s, br_player_id=%s "
            "WHERE source=%s AND season=%s AND playerid IS NULL AND player=%s",
            (nba_id, br_id, SOURCE_VAL, SEASON_VAL, pname),
        )
        n_rows += cur.rowcount
    c.commit()
    print("\n[APPLIED] UPDATE statements issued for %d names; rows affected=%d" % (len(updates), n_rows))

    cur.execute(
        "SELECT COUNT(*) FROM play_by_play WHERE source=%s AND season=%s AND playerid IS NULL",
        (SOURCE_VAL, SEASON_VAL),
    )
    still_null = cur.fetchone()[0]
    print("[after] BBRef season=%d rows still playerid NULL: %d (was %d)" % (SEASON_VAL, still_null, total_null))

    # Write unresolved list
    out_tsv = os.path.join(HERE, 'unresolved_2026_bbref_playerid.tsv')
    with open(out_tsv, 'w', encoding='utf-8') as f:
        f.write("player_name\treason\trow_count\n")
        for nm, cnt in sorted(unresolved.items(), key=lambda x: -x[1]):
            reason = nm.split('[')[-1].rstrip(']')
            f.write("%s\t%s\t%d\n" % (nm, reason, cnt))
    print("[log] wrote %s (%d buckets)" % (out_tsv, len(unresolved)))

    c.close()


if __name__ == '__main__':
    main()
