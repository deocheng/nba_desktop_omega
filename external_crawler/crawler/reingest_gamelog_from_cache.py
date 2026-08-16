#!/usr/bin/env python3
"""Re-ingest player_gamelog rows for 1980-2013 (cached seasons) that were
PREVIOUSLY DROPPED at write time due to the team-abbreviation mismatch bug.

ROOT CAUSE (verified 2026-08-12):
  crawl_br_gamelog.get_game_id_map() keyed (game_date, team) against
  dim_games using a LITERAL abbreviation match. But dim_games stores BOTH
  historical and modern abbreviations (e.g. UTA vs UTH, SAS vs SAN, GSW vs
  GOS, PHI vs PHL, plus CHA/NOK/VAN/WSB which appear only in the cache side).
  When the cache used one form and dim_games used the other, the lookup failed
  -> game_id=None -> the row was skipped at write. This is NOT a source/BR-500
  issue; the data was correctly scraped into gamelog_cache/.

FIX:
  - Preload dim_games rows per season and match each cache game by
    (date, team, opp) using SYMMETRIC GROUP-CANONICALIZATION of abbreviations
    (a franchise's alternate spellings collapse to one token on both sides),
    so either abbreviation form matches. The matched dim row supplies the
    authoritative nba_api_id (-> gameid) and BR game_id (-> game_id_full).
  - Surgically insert only (gameid, br_player_id) pairs MISSING from
    player_gamelog. Existing correct rows are left untouched (idempotent).
  - 385 games whose dim row has nba_api_id NULL cannot be written
    (player_gamelog.gameid is NOT NULL) -> they remain as residual gaps.

Standalone (stdlib + psycopg2 only) to avoid importing the crawler's heavy
`common` chain (which OOMs the sandbox PG).

Usage:
  python reingest_gamelog_from_cache.py [--dry-run] [--seasons 1980 1981 ...]
"""
import json
import os
import sys
import argparse
import psycopg2

ROOT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
CACHE = os.path.join(ROOT, "external_crawler/crawler/gamelog_cache")
DB = dict(host="127.0.0.1", port=5433, user="postgres",
          password="R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1", dbname="nba")

# Symmetric franchise abbreviation groups. Either form canonicalizes to the
# same token, so matching is order- and form-independent. No two DIFFERENT
# franchises share a group, so no false matches.
ABBR_GROUPS = [
    {'SAS', 'SAN'},
    {'GSW', 'GOS'},
    {'PHI', 'PHL'},
    {'UTA', 'UTH'},
    {'CHA', 'CHO', 'CHH'},
    {'NOK', 'NOP', 'NOH'},  # New Orleans: Hornets(NOH/NOK) -> Pelicans(NOP)
    {'VAN', 'MEM'},
    {'WSB', 'WAS'},
    {'NJN', 'BRK'},
    {'SEA', 'OKC'},
    {'SDC', 'LAC'},
    {'KCK', 'SAC'},
]
CANON = {}
for _grp in ABBR_GROUPS:
    _tok = frozenset(_grp)
    for _a in _grp:
        CANON[_a] = _tok

def canon(a):
    return CANON.get(a, a)

# 29-column INSERT order — mirrors crawl_br_gamelog.build_insert exactly.
COLUMNS = (
    'gameid', 'player', 'team', 'season',
    'br_player_id', 'player_name', 'game_id_full',
    'player_id', 'nba_player_id',
    'fg', 'fga', 'fg_pct', 'fg3', 'fga3', 'fg3_pct',
    'ft', 'fta', 'ft_pct', 'orb', 'drb', 'trb', 'ast', 'stl', 'blk',
    'tov', 'pf', 'pts', 'plus_minus', 'minutes',
)

# Columns that come straight from the cache game dict.
STAT_KEYS = ['fg', 'fga', 'fg_pct', 'fg3', 'fga3', 'fg3_pct',
             'ft', 'fta', 'ft_pct', 'orb', 'drb', 'trb', 'ast', 'stl',
             'blk', 'tov', 'pf', 'pts', 'plus_minus', 'minutes']


def build_values(player_name, slug, g, gameid, game_id_full, nba_player_id):
    """Return the 29-value tuple in COLUMNS order (mirrors build_insert)."""
    vals = [None] * 29
    vals[0] = gameid                 # gameid
    vals[1] = player_name            # player
    vals[2] = g.get('team')          # team
    vals[3] = g.get('season')        # season
    vals[4] = slug                   # br_player_id
    vals[5] = player_name            # player_name
    vals[6] = game_id_full           # game_id_full
    vals[7] = slug                   # player_id
    vals[8] = nba_player_id          # nba_player_id
    for i, k in enumerate(STAT_KEYS):
        vals[9 + i] = g.get(k)
    return tuple(vals)


def delete_existing(cur, gameid, slug, player_name):
    """Idempotent delete (mirrors crawl_br_gamelog.delete_existing)."""
    cur.execute(
        "DELETE FROM player_gamelog "
        "WHERE gameid = %s "
        "  AND (br_player_id = %s OR (br_player_id IS NULL AND player = %s))",
        (gameid, slug, player_name),
    )


def load_bridge(conn):
    cur = conn.cursor()
    cur.execute("SELECT br_player_id, nba_player_id FROM player_id_bridge")
    return {r[0]: r[1] for r in cur.fetchall()}


def load_dim_season(conn, season):
    """date_str -> list of (home, away, nba_api_id, nba_api_id_is_null, game_id_BR)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT game_date::text, home_team_abbr, away_team_abbr, nba_api_id, game_id
        FROM dim_games
        WHERE season = %s AND season_type = 'Regular Season'
    """, (season,))
    d = {}
    for date_str, home, away, nid, gid in cur.fetchall():
        d.setdefault(date_str, []).append((home, away, nid, gid))
    return d


def load_existing_keys(conn, season):
    """Set of (gameid_str, br_player_id) already present for the season."""
    cur = conn.cursor()
    cur.execute(
        "SELECT gameid, br_player_id FROM player_gamelog "
        "WHERE season = %s AND br_player_id IS NOT NULL",
        (season,))
    return {(str(r[0]), r[1]) for r in cur.fetchall()}


def resolve(dim_rows, date, team, opp):
    """Return (nba_api_id, game_id_BR) for a cache game, or None."""
    if not dim_rows:
        return None
    ct, co = canon(team), canon(opp)
    target = {ct, co}
    for (home, away, nid, gid) in dim_rows:
        if {canon(home), canon(away)} == target:
            return (nid, gid)
    return None


def process_season(conn, season, bridge, dry_run):
    fp = os.path.join(CACHE, f"gamelog_{season}.json")
    if not os.path.exists(fp):
        print(f"  [skip] no cache for {season}")
        return dict(inserted=0, skipped_present=0, unresolved=0, nid_null=0)

    dim = load_dim_season(conn, season)
    existing = load_existing_keys(conn, season)
    with open(fp) as f:
        data = json.load(f)

    stats = dict(inserted=0, skipped_present=0, unresolved=0, nid_null=0)
    cur = conn.cursor()
    col_sql = ", ".join(COLUMNS)
    ph = ", ".join(["%s"] * len(COLUMNS))

    for p in data.get("players", []):
        name = p.get("player")
        slug = p.get("player_id")
        if not slug:
            continue
        nba_pid = bridge.get(slug)
        for g in p.get("games", []):
            D = g.get("date"); T = g.get("team"); O = g.get("opp")
            if not D or not T:
                continue
            res = resolve(dim.get(D), D, T, O)
            if res is None:
                stats["unresolved"] += 1
                continue
            nid, gid = res
            if nid is None:
                # dim row exists but has no numeric id -> cannot write (NOT NULL)
                stats["nid_null"] += 1
                continue
            gameid = str(nid)
            game_id_full = str(gid) if gid else None
            key = (gameid, slug)
            if key in existing:
                stats["skipped_present"] += 1
                continue
            if dry_run:
                stats["inserted"] += 1
                continue
            delete_existing(cur, gameid, slug, name)
            vals = build_values(name, slug, g, gameid, game_id_full, nba_pid)
            cur.execute(
                f"INSERT INTO player_gamelog ({col_sql}, created_at) "
                f"VALUES ({ph}, NOW())", vals)
            existing.add(key)
            stats["inserted"] += 1

    if not dry_run:
        conn.commit()
    cur.close()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Count what would be inserted; write nothing.")
    ap.add_argument("--seasons", nargs="*", type=int,
                    default=[s for s in range(1980, 2014) if s not in (1990, 1996)])
    args = ap.parse_args()

    conn = psycopg2.connect(**DB)
    try:
        bridge = load_bridge(conn)
        print(f"bridge map size: {len(bridge)}")
        tot = dict(inserted=0, skipped_present=0, unresolved=0, nid_null=0)
        for s in args.seasons:
            st = process_season(conn, s, bridge, args.dry_run)
            for k in tot:
                tot[k] += st[k]
            print(f"  season {s}: +{st['inserted']} inserted, "
                  f"{st['skipped_present']} already-present, "
                  f"{st['unresolved']} unresolved, {st['nid_null']} nid_null"
                  f"{' [DRY-RUN]' if args.dry_run else ''}")
        print("\nTOTAL:", tot, "[DRY-RUN]" if args.dry_run else "")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
