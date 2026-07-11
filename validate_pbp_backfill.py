"""Validate 2026 Regular Season PBP coverage after the BR backfill.

Uses Python set logic + indexed ANY() lookups (avoids slow cross-table joins):
  - nba_api-keyed games -> play_by_play.gameid = str(games.nba_api_id)  (unpadded bigint)
  - BR-keyed gap games  -> play_by_play.gameid = games.game_id          (e.g. '202511010IND')

Also reports parsing quality (player fill, event_type + action_verb coverage)
for the BR-keyed rows, and playoff coverage.
"""
from __future__ import annotations
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.core import config

conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)
cur = conn.cursor()


def _check_coverage(season: int, season_type: str) -> None:
    cur.execute(
        "SELECT game_id, nba_api_id FROM games WHERE season=%s AND season_type=%s",
        (season, season_type),
    )
    rows = cur.fetchall()
    total = len(rows)

    nba_keys: set[str] = set()
    br_keys: set[str] = set()
    for r in rows:
        if r['nba_api_id'] is not None:
            nba_keys.add(str(r['nba_api_id']))  # unpadded bigint string
        br_keys.add(r['game_id'])

    gap = total - len(nba_keys)

    # Indexed lookups via ANY()
    cur.execute(
        'SELECT COUNT(DISTINCT gameid) c FROM play_by_play WHERE gameid = ANY(%s)',
        (list(nba_keys),),
    )
    nba_covered = cur.fetchone()['c']

    cur.execute(
        'SELECT COUNT(DISTINCT gameid) c FROM play_by_play WHERE gameid = ANY(%s)',
        (list(br_keys),),
    )
    br_covered = cur.fetchone()['c']

    all_keys = list(nba_keys | br_keys)
    cur.execute(
        'SELECT COUNT(DISTINCT gameid) c FROM play_by_play WHERE gameid = ANY(%s)',
        (all_keys,),
    )
    with_pbp = cur.fetchone()['c']

    cur.execute(
        'SELECT COUNT(*) c FROM play_by_play WHERE gameid = ANY(%s)',
        (all_keys,),
    )
    events = cur.fetchone()['c']

    print(f"=== {season} {season_type} PBP Coverage ===")
    print(f"  total games           : {total}")
    print(f"  nba_api-keyed covered : {nba_covered}")
    print(f"  gap (nba_api_id NULL) : {gap}")
    print(f"  BR-keyed covered      : {br_covered}")
    print(f"  TOTAL with PBP        : {with_pbp}")
    print(f"  missing PBP           : {total - with_pbp}")
    if total:
        print(f"  coverage              : {with_pbp / total * 100:.1f}%")
    print(f"  total PBP events      : {events:,}")
    print()


_check_coverage(2026, 'Regular Season')
_check_coverage(2026, 'Playoffs')

# BR-keyed row quality (gameid contains non-digit chars)
cur.execute("""
    SELECT COUNT(*) total,
           COUNT(player) with_player,
           COUNT(*) FILTER (WHERE event_type IS NOT NULL) with_type,
           COUNT(*) FILTER (WHERE action_verb IS NOT NULL) with_verb
    FROM play_by_play WHERE gameid ~ '[^0-9]'
""")
q = cur.fetchone()
print("=== BR-keyed PBP Quality ===")
print(f"  rows              : {q['total']:,}")
if q['total']:
    print(f"  with player       : {q['with_player']:,} ({q['with_player'] / q['total'] * 100:.1f}%)")
    print(f"  with event_type   : {q['with_type']:,} ({q['with_type'] / q['total'] * 100:.1f}%)")
    print(f"  with action_verb  : {q['with_verb']:,} ({q['with_verb'] / q['total'] * 100:.1f}%)")
    cur.execute("""
        SELECT action_verb, COUNT(*) c FROM play_by_play
        WHERE gameid ~ '[^0-9]' GROUP BY action_verb ORDER BY c DESC
    """)
    print("  action_verb distribution:")
    for e in cur.fetchall():
        print(f"    {str(e['action_verb']):16} {e['c']:,}")
print()

# Overall table stats
cur.execute('SELECT COUNT(*) c FROM play_by_play')
all_pbp = cur.fetchone()['c']
cur.execute("SELECT source, COUNT(*) c FROM play_by_play GROUP BY source ORDER BY c DESC")
sources = cur.fetchall()
print("=== Overall play_by_play ===")
print(f"  total rows: {all_pbp:,}")
print("  by source:")
for s in sources:
    print(f"    {str(s['source']):16} {s['c']:,}")

conn.close()
