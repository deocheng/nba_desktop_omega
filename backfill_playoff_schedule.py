#!/usr/bin/env python3
"""
Backfill NBA playoff schedule rows into `dim_games` for seasons whose
postseason schedule was missing, using the BR schedule cache JSONs.

Source : /Users/deocheng/WorkBuddy/NBA_BR_爬虫/audit_output/season_<Y>.json
         each record with "issues" containing "MISSING" is a game absent from dim_games.
Target : dim_games  (game_id=YYYYMMDD0HOME, 12-char; home_team_id = NBA numeric id string)

Key correctness notes (learned from prior broken script):
  * br_matchup = "AWAY@HOME"  -> game_id uses HOME abbr
  * detail      = "BR {away_pts}-{home_pts}"  (visitor=away, home=home) -> DO NOT swap
  * team abbr must use modern codes: CHH->CHO, SEA->OKC, NJN->BRK, PHX->PHO
  * inserts only Playoffs (none of the 294 fall on Play-In dates)

Usage:
  python3 backfill_playoff_schedule.py --dry-run
  python3 backfill_playoff_schedule.py --execute
  python3 backfill_playoff_schedule.py --fix-ghosts --execute   # also delete 2024 phantom rows
"""
import json, os, re, sys, argparse
from collections import Counter
from dotenv import load_dotenv
import psycopg2

PROJECT_ROOT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
CACHE_ROOT = "/Users/deocheng/WorkBuddy/NBA_BR_爬虫/audit_output"

# playoff window lower bound per target season (first possible playoff date)
PO_START = {
    2000: "2000-04-22",
    2006: "2006-04-22",
    2024: "2024-04-16",
    2025: "2025-04-15",
}
DEFAULT_TARGETS = [2000, 2006, 2024, 2025]

HIST_TO_CUR = {
    "CHH": "CHO", "SEA": "OKC", "NJN": "BRK", "PHX": "PHO",
}
def norm(abbr):
    return HIST_TO_CUR.get(abbr, abbr)


def build_rows(cur, targets):
    # abbr -> (numeric team_id str, team_name) from existing dim_games
    cur.execute("""SELECT DISTINCT home_team_abbr, home_team_id, home_team_name
                   FROM dim_games WHERE home_team_id IS NOT NULL""")
    team_map = {}
    for abbr, tid, tname in cur.fetchall():
        if abbr and tid:
            team_map[abbr] = (str(tid), tname)

    rows = []
    for season in targets:
        path = os.path.join(CACHE_ROOT, f"season_{season}.json")
        if not os.path.exists(path):
            print(f"SKIP {season}: {path} not found", file=sys.stderr)
            continue
        with open(path) as fh:
            data = json.load(fh)
        # cache JSON top-level is a dict: {"year":..., "count":..., "records":[...]}
        records = data["records"] if isinstance(data, dict) else data
        start = PO_START.get(season, f"{season}-04-15")
        end = f"{season}-06-30"
        n_season = 0
        for rec in records:
            if "MISSING" not in (rec.get("issues") or []):
                continue
            gd = rec.get("game_date")
            if not gd or gd < start or gd > end:
                continue
            m = re.match(r"([A-Z]{3})@([A-Z]{3})", rec.get("br_matchup", ""))
            if not m:
                continue
            away_raw, home_raw = m.group(1), m.group(2)
            away, home = norm(away_raw), norm(home_raw)
            dm = re.search(r"BR\s+(\d+)-(\d+)", rec.get("detail", ""))
            away_pts = home_pts = None
            if dm:
                away_pts, home_pts = int(dm.group(1)), int(dm.group(2))
            gid = gd.replace("-", "") + "0" + home
            hid, hname = team_map.get(home, (None, None))
            aid, aname = team_map.get(away, (None, None))
            if not hid or not aid:
                print(f"WARN no team_id for {home}/{away} (game {gid})", file=sys.stderr)
            rows.append({
                "game_id": gid, "game_date": gd, "season": season,
                "season_type": "Playoffs",
                "home_abbr": home, "home_team_id": hid, "home_team_name": hname,
                "away_abbr": away, "away_team_id": aid, "away_team_name": aname,
                "home_pts": home_pts, "away_pts": away_pts,
                "game_status": "Final", "source": "BR_schedule",
            })
            n_season += 1
        print(f"  season {season}: {n_season} candidate rows from cache", file=sys.stderr)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="+", type=int, default=DEFAULT_TARGETS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--fix-ghosts", action="store_true",
                    help="also DELETE 2024 phantom Playoffs rows (source IS NULL)")
    args = ap.parse_args()
    if not args.execute and not args.dry_run:
        args.dry_run = True

    load_dotenv(ENV_PATH)
    cfg = dict(host=os.getenv("DB_HOST"), port=int(os.getenv("DB_PORT", 5433)),
               dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
               password=os.getenv("DB_PASSWORD"))
    conn = psycopg2.connect(**cfg)
    conn.autocommit = False
    cur = conn.cursor()

    rows = build_rows(cur, args.targets)
    cnt = Counter(r["season"] for r in rows)
    print(f"Prepared {len(rows)} rows to insert:")
    for s in sorted(cnt):
        print(f"  season {s}: {cnt[s]} games")

    if args.fix_ghosts:
        cur.execute("""SELECT COUNT(*) FROM dim_games
                       WHERE season=2024 AND season_type='Playoffs' AND source IS NULL""")
        g = cur.fetchone()[0]
        print(f"Ghost 2024 phantom Playoffs rows (source IS NULL): {g}")

    if args.dry_run:
        print("DRY-RUN: no changes. Sample (first 10):")
        for r in rows[:10]:
            print("  ", r["game_id"], r["game_date"],
                  f"{r['away_abbr']}@{r['home_abbr']}",
                  f"{r['away_pts']}-{r['home_pts']}",
                  "hid=", r["home_team_id"], "aid=", r["away_team_id"])
        conn.rollback()
        return

    if not args.execute:
        conn.rollback()
        return

    # ghost cleanup first (so re-tag JOIN won't hit phantoms)
    if args.fix_ghosts:
        cur.execute("""DELETE FROM dim_games
                       WHERE season=2024 AND season_type='Playoffs' AND source IS NULL""")
        print(f"Deleted {cur.rowcount} ghost 2024 rows")

    sql = """INSERT INTO dim_games
             (game_id, game_date, season, season_type,
              home_team_abbr, home_team_id, home_team_name,
              away_team_abbr, away_team_id, away_team_name,
              home_pts, away_pts, game_status, source)
             VALUES
             (%(game_id)s,%(game_date)s,%(season)s,%(season_type)s,
              %(home_abbr)s,%(home_team_id)s,%(home_team_name)s,
              %(away_abbr)s,%(away_team_id)s,%(away_team_name)s,
              %(home_pts)s,%(away_pts)s,%(game_status)s,%(source)s)
             ON CONFLICT (game_id) DO NOTHING"""
    cur.executemany(sql, rows)
    print(f"INSERTED {cur.rowcount} rows into dim_games")
    conn.commit()
    print("COMMITTED")


if __name__ == "__main__":
    main()
