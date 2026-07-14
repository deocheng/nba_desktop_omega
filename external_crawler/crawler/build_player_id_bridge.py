#!/usr/bin/env python3
import os
"""
Build comprehensive player ID bridge v2:
- Collect names from BOTH player_gamelog AND play_by_play
- Match to dim_players using multi-strategy chain
- Output: player_id_bridge table with (nba_player_id, player_name, br_player_id, match_strategy)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import psycopg2
import re
from collections import defaultdict

DB_CONFIG = dict(host='localhost', port=5433, dbname='nba', user='postgres', password=os.environ.get('DB_PASSWORD'))

TEAM_NAMES_LOWER = {
    '76ers', 'blazers', 'nuggets', 'warriors', 'lakers', 'clippers', 'suns', 'kings',
    'mavericks', 'rockets', 'grizzlies', 'pelicans', 'spurs', 'jazz', 'thunder',
    'timberwolves', 'bucks', 'bulls', 'cavaliers', 'pistons', 'pacers', 'hawks',
    'hornets', 'heat', 'magic', 'wizards', 'knicks', 'nets', 'celtics', 'raptors',
    'supersonics', 'bullets', 'bobcats', 'trail blazers', 'trailblazers',
}

def is_team_name(name):
    if not name:
        return False
    return name.lower() in TEAM_NAMES_LOWER

def connect():
    return psycopg2.connect(**DB_CONFIG)

def build_bridge():
    conn = connect()
    cur = conn.cursor()

    # ============================================================
    # Step 1: Load dim_players
    # ============================================================
    print("=" * 60)
    print("Step 1: Loading dim_players")
    print("=" * 60)

    name_to_br = {}          # exact name → BR ID
    lower_name_to_br = {}    # lowercase → BR ID
    last_name_to_candidates = defaultdict(list)  # last_name → [(br_id, name, yr_from, yr_to)]
    full_name_to_br = {}     # lowercase full_name → BR ID

    cur.execute("SELECT player_id, player_name, full_name, year_from, year_to FROM dim_players")
    for br_id, pname, fname, yr_from, yr_to in cur.fetchall():
        if pname:
            name_to_br[pname] = br_id
            lower_name_to_br[pname.lower()] = br_id
            parts = pname.split()
            if len(parts) >= 2:
                last_name_to_candidates[parts[-1].lower()].append((br_id, pname, yr_from, yr_to))
        if fname and fname != pname:
            full_name_to_br[fname.lower()] = br_id
            # Also add full name parts
            if fname not in name_to_br:
                name_to_br[fname] = br_id
                lower_name_to_br[fname.lower()] = br_id

    print(f"  {len(name_to_br)} names, {len(last_name_to_candidates)} last names")

    # ============================================================
    # Step 2: Load fact_player_season_stats bridge
    # ============================================================
    fps_name_to_br = {}
    cur.execute("SELECT DISTINCT player, player_id FROM fact_player_season_stats WHERE player IS NOT NULL AND player_id IS NOT NULL")
    for pname, br_id in cur.fetchall():
        if pname and br_id:
            fps_name_to_br[pname] = br_id
            fps_name_to_br[pname.lower()] = br_id
    print(f"  fps bridge: {len(fps_name_to_br)} entries")

    # ============================================================
    # Step 3: Load draft_combine NBA ID → name
    # ============================================================
    dc_nba_to_name = {}
    cur.execute("SELECT nba_player_id, player_name FROM draft_combine WHERE nba_player_id IS NOT NULL AND player_name IS NOT NULL")
    for nba_id, pname in cur.fetchall():
        dc_nba_to_name[str(nba_id)] = pname
    print(f"  draft_combine: {len(dc_nba_to_name)} entries")

    # ============================================================
    # Step 4: Collect ALL distinct (name, nba_id, season) from BOTH tables
    # ============================================================
    print("\n" + "=" * 60)
    print("Step 4: Collecting identifiers from gamelog + PBP")
    print("=" * 60)

    # From gamelog
    cur.execute("""
        SELECT DISTINCT player, player_id::text, season::int
        FROM player_gamelog
        WHERE player IS NOT NULL
    """)
    all_entries = cur.fetchall()
    print(f"  From player_gamelog: {len(all_entries)} entries")

    # From PBP (only short numeric IDs that look like player IDs, not team IDs)
    cur.execute("""
        SELECT DISTINCT player, playerid,
               CASE 
                   WHEN gameid ~ '^2[0-9]{2}' THEN SUBSTRING(gameid FROM 2 FOR 2)::int + 2000
                   WHEN gameid ~ '^4[0-9]{2}' THEN SUBSTRING(gameid FROM 2 FOR 2)::int + 2000
                   WHEN gameid ~ '^5[0-9]{2}' THEN SUBSTRING(gameid FROM 2 FOR 2)::int + 2000
                   ELSE NULL
               END as season
        FROM play_by_play
        WHERE player IS NOT NULL
          AND playerid IS NOT NULL
          AND playerid ~ '^[0-9]+$'
          AND LENGTH(playerid) <= 7
    """)
    pbp_entries = cur.fetchall()
    print(f"  From play_by_play: {len(pbp_entries)} entries")

    all_entries.extend(pbp_entries)
    print(f"  Combined: {len(all_entries)} entries")

    # ============================================================
    # Step 5: Match using strategy chain
    # ============================================================
    print("\n" + "=" * 60)
    print("Step 5: Matching")
    print("=" * 60)

    # player_name → (br_id, strategy, nba_id)
    name_to_result = {}
    # nba_id → br_id
    nba_to_br = {}
    stats = defaultdict(int)

    for pname, nba_id_str, season in all_entries:
        if is_team_name(pname):
            continue
        if not pname or pname.strip() == '':
            continue

        # Skip if already matched
        if pname in name_to_result:
            br_id = name_to_result[pname][0]
            if nba_id_str and nba_id_str not in nba_to_br:
                nba_to_br[nba_id_str] = br_id
            continue

        br_id = None
        strategy = None

        # S1: Exact name
        if pname in name_to_br:
            br_id, strategy = name_to_br[pname], 'exact_name'

        # S2: Case-insensitive
        if not br_id and pname.lower() in lower_name_to_br:
            br_id, strategy = lower_name_to_br[pname.lower()], 'case_insensitive'

        # S3: Via fps
        if not br_id and pname in fps_name_to_br:
            br_id, strategy = fps_name_to_br[pname], 'fps_bridge'

        # S4: Abbreviated name ("A. Abrines")
        if not br_id and '.' in pname:
            m = re.match(r'^([A-Z])\.\s*(.+)', pname)
            if m:
                first_init = m.group(1)
                rest = m.group(2).strip()
                last_name = rest.split()[-1].rstrip('.') if ' ' in rest else rest.rstrip('.')
                candidates = last_name_to_candidates.get(last_name.lower(), [])
                matches = [(bid, bn, yf, yt) for bid, bn, yf, yt in candidates
                          if bn.upper().startswith(first_init)]
                if len(matches) == 1:
                    br_id, strategy = matches[0][0], 'abbrev_unique'
                elif len(matches) > 1 and season is not None:
                    sy = season if season >= 2000 else 2000 + season
                    sm = [(bid, bn, yf, yt) for bid, bn, yf, yt in matches
                          if yf is None or yt is None or (yf <= sy <= (yt or 9999))]
                    if len(sm) == 1:
                        br_id, strategy = sm[0][0], 'abbrev_season'
                    elif len(sm) > 1:
                        br_id, strategy = sm[0][0], 'abbrev_season_best'

        # S5: Last name only
        if not br_id and ' ' not in pname and '.' not in pname and len(pname) >= 3:
            candidates = last_name_to_candidates.get(pname.lower(), [])
            if len(candidates) == 1:
                br_id, strategy = candidates[0][0], 'lastname_unique'
            elif len(candidates) > 1 and season is not None:
                sy = season if season >= 2000 else 2000 + season
                sm = [(bid, bn, yf, yt) for bid, bn, yf, yt in candidates
                      if yf is None or yt is None or (yf <= sy <= (yt or 9999))]
                if len(sm) == 1:
                    br_id, strategy = sm[0][0], 'lastname_season'

        # S6: NBA numeric ID via draft_combine
        if not br_id and nba_id_str:
            dc_name = dc_nba_to_name.get(nba_id_str)
            if dc_name:
                if dc_name in name_to_br:
                    br_id, strategy = name_to_br[dc_name], 'nba_id_combine'
                elif dc_name.lower() in lower_name_to_br:
                    br_id, strategy = lower_name_to_br[dc_name.lower()], 'nba_id_combine_ci'

        # S7: Full name lookup
        if not br_id and pname.lower() in full_name_to_br:
            br_id, strategy = full_name_to_br[pname.lower()], 'full_name'

        if br_id:
            name_to_result[pname] = (br_id, strategy, nba_id_str)
            stats[strategy] += 1
            if nba_id_str and nba_id_str not in nba_to_br:
                nba_to_br[nba_id_str] = br_id
        else:
            stats['unmatched'] += 1

    # ============================================================
    # Step 6: Report
    # ============================================================
    print(f"\n  Results:")
    total = sum(stats.values())
    for k in sorted(stats.keys(), key=lambda x: -stats[x]):
        v = stats[k]
        pct = f"({v*100/total:.1f}%)" if total else ""
        print(f"    {k:30s} {v:>6} {pct}")

    matched = sum(v for k, v in stats.items() if k != 'unmatched')
    unmatched = stats.get('unmatched', 0)
    print(f"\n  Matched: {matched} | Unmatched: {unmatched} | Rate: {matched*100/(matched+unmatched):.1f}%")
    print(f"  NBA→BR mappings: {len(nba_to_br)}")

    # ============================================================
    # Step 7: Create bridge table
    # ============================================================
    print("\n" + "=" * 60)
    print("Step 7: Creating player_id_bridge table")
    print("=" * 60)

    cur.execute("DROP TABLE IF EXISTS player_id_bridge CASCADE")
    cur.execute("""
        CREATE TABLE player_id_bridge (
            nba_player_id TEXT,
            player_name VARCHAR NOT NULL,
            br_player_id VARCHAR(32) NOT NULL,
            match_strategy VARCHAR(50),
            UNIQUE (player_name)
        )
    """)

    inserted = 0
    for pname, (br_id, strategy, nba_id_str) in name_to_result.items():
        cur.execute("""
            INSERT INTO player_id_bridge (nba_player_id, player_name, br_player_id, match_strategy)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (player_name) DO NOTHING
        """, (nba_id_str, pname, br_id, strategy))
        inserted += cur.rowcount

    # Also add NBA ID-only mappings (for PBP rows where we have ID but no name match)
    for nba_id_str, br_id in nba_to_br.items():
        cur.execute("""
            INSERT INTO player_id_bridge (nba_player_id, player_name, br_player_id, match_strategy)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (player_name) DO NOTHING
        """, (nba_id_str, f'[nba_id:{nba_id_str}]', br_id, 'nba_id_direct'))
        inserted += cur.rowcount

    conn.commit()
    print(f"  Inserted {inserted} records")

    cur.execute("CREATE INDEX idx_bridge_nba_id ON player_id_bridge(nba_player_id)")
    cur.execute("CREATE INDEX idx_bridge_name ON player_id_bridge(player_name)")
    cur.execute("CREATE INDEX idx_bridge_br_id ON player_id_bridge(br_player_id)")
    conn.commit()

    # ============================================================
    # Step 8: Coverage analysis
    # ============================================================
    print("\n" + "=" * 60)
    print("Step 8: Coverage analysis")
    print("=" * 60)

    # Gamelog
    cur.execute("""
        SELECT COUNT(*) FROM player_gamelog pg
        WHERE pg.player IN (SELECT player_name FROM player_id_bridge)
    """)
    gl_cov = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM player_gamelog WHERE player IS NOT NULL")
    gl_total = cur.fetchone()[0]
    print(f"  player_gamelog: {gl_cov:,}/{gl_total:,} ({gl_cov*100/gl_total:.1f}%)")

    # PBP
    cur.execute("""
        SELECT COUNT(*) FROM play_by_play pbp
        WHERE pbp.playerid IN (SELECT nba_player_id FROM player_id_bridge WHERE nba_player_id IS NOT NULL)
           OR pbp.player IN (SELECT player_name FROM player_id_bridge)
    """)
    pbp_cov = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM play_by_play WHERE playerid IS NOT NULL")
    pbp_total = cur.fetchone()[0]
    print(f"  play_by_play:   {pbp_cov:,}/{pbp_total:,} ({pbp_cov*100/pbp_total:.1f}%)")

    # True orphans (player rows, not team events)
    cur.execute("""
        SELECT COUNT(*) FROM play_by_play 
        WHERE playerid IS NOT NULL 
          AND playerid NOT IN (SELECT nba_player_id FROM player_id_bridge WHERE nba_player_id IS NOT NULL)
          AND (player IS NULL OR player NOT IN (SELECT player_name FROM player_id_bridge))
    """)
    orphan = cur.fetchone()[0]
    print(f"  Still orphan:   {orphan:,} rows")

    # How many are team events (playerid > 6 digits)?
    cur.execute("""
        SELECT COUNT(*) FROM play_by_play 
        WHERE playerid IS NOT NULL 
          AND playerid NOT IN (SELECT nba_player_id FROM player_id_bridge WHERE nba_player_id IS NOT NULL)
          AND (player IS NULL OR player NOT IN (SELECT player_name FROM player_id_bridge))
          AND playerid ~ '^[0-9]+$' AND LENGTH(playerid) > 7
    """)
    team_events = cur.fetchone()[0]
    print(f"    - team events (long ID): {team_events:,}")

    cur.execute("""
        SELECT COUNT(*) FROM play_by_play 
        WHERE playerid IS NOT NULL 
          AND playerid NOT IN (SELECT nba_player_id FROM player_id_bridge WHERE nba_player_id IS NOT NULL)
          AND (player IS NULL OR player NOT IN (SELECT player_name FROM player_id_bridge))
          AND (playerid IS NULL OR playerid = '0' OR playerid = '')
    """)
    null_events = cur.fetchone()[0]
    print(f"    - null/zero events: {null_events:,}")

    true_player_orphans = orphan - team_events - null_events
    print(f"    - true player orphans: {true_player_orphans:,}")

    conn.close()
    print("\n" + "=" * 60)
    print("Done! Bridge table ready.")
    print("=" * 60)


if __name__ == '__main__':
    build_bridge()
