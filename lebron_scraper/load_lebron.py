#!/usr/bin/env python3
"""
load_lebron.py  --  Load lebron.jsonl into the `player_lebron` table.

Aligns each row's nba_id to br_player_id via player_id_bridge
(nba_player_id::text = str(nba_id)). Rows whose nba_id has no bridge match
are kept with br_player_id = NULL (nba_id is the stable key).

Idempotent: INSERT ... ON CONFLICT (nba_id, season) DO UPDATE.
"""
import os
import sys
import json
import argparse
import psycopg2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp",
                    default=os.path.join(os.path.dirname(__file__),
                                         "lebron.jsonl"))
    ap.add_argument("--resolve-br", action="store_true", default=True,
                    help="resolve br_player_id from player_id_bridge "
                         "(default: on)")
    args = ap.parse_args()

    # DB connection from .env (resolve absolute so it works from any cwd)
    env = {}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for l in open(os.path.join(root, ".env")):
        if l.startswith("DB_"):
            k, v = l.strip().split("=", 1)
            env[k] = v
    dsn = (f"host={env['DB_HOST']} port={env['DB_PORT']} "
           f"dbname={env['DB_NAME']} user={env['DB_USER']} "
           f"password={env['DB_PASSWORD']}")

    c = psycopg2.connect(dsn)
    cur = c.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_lebron (
            nba_id            text    NOT NULL,
            player_name       text,
            season            integer NOT NULL,
            through_date      date,
            lebron            numeric,
            olebron           numeric,
            dlebron           numeric,
            boxlebron         numeric,
            lebron_war        numeric,
            total_luck        numeric,
            mins              numeric,
            off_poss          numeric,
            def_poss          numeric,
            cum_off_poss      numeric,
            cum_def_poss      numeric,
            off_points_added  numeric,
            def_points_saved  numeric,
            br_player_id      varchar,
            snapshot_date     date,
            PRIMARY KEY (nba_id, season)
        )
    """)

    bridge = {}
    if args.resolve_br:
        cur.execute("""SELECT nba_player_id, br_player_id FROM player_id_bridge
                       WHERE nba_player_id IS NOT NULL AND nba_player_id <> ''""")
        for nid, bid in cur.fetchall():
            try:
                bridge[str(int(float(nid)))] = bid
            except (TypeError, ValueError):
                bridge[str(nid)] = bid
    print(f"[info] bridge size: {len(bridge)}")

    cols = ["nba_id", "player_name", "season", "through_date", "lebron",
            "olebron", "dlebron", "boxlebron", "lebron_war", "total_luck",
            "mins", "off_poss", "def_poss", "cum_off_poss", "cum_def_poss",
            "off_points_added", "def_points_saved", "br_player_id",
            "snapshot_date"]
    colsql = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    upd = ", ".join(f"{col}=EXCLUDED.{col}" for col in
                    ["player_name", "through_date", "lebron", "olebron",
                     "dlebron", "boxlebron", "lebron_war", "total_luck",
                     "mins", "off_poss", "def_poss", "cum_off_poss",
                     "cum_def_poss", "off_points_added", "def_points_saved",
                     "br_player_id", "snapshot_date"])

    n = 0
    matched = 0
    with open(args.inp) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            nid = str(r["nba_id"])
            bid = bridge.get(nid)
            if bid:
                matched += 1
            vals = [r.get("nba_id"), r.get("player_name"),
                    (2000 + int(str(r.get("season")).split("-")[-1]))
                    if r.get("season") else None,
                    r.get("through_date"), r.get("lebron"), r.get("olebron"),
                    r.get("dlebron"), r.get("boxlebron"), r.get("lebron_war"),
                    r.get("total_luck"), r.get("mins"), r.get("off_poss"),
                    r.get("def_poss"), r.get("cum_off_poss"),
                    r.get("cum_def_poss"), r.get("off_points_added"),
                    r.get("def_points_saved"), bid, r.get("snapshot_date")]
            cur.execute(
                f"INSERT INTO player_lebron ({colsql}) VALUES ({placeholders}) "
                f"ON CONFLICT (nba_id, season) DO UPDATE SET {upd}", vals)
            n += 1
    c.commit()
    print(f"[done] rows={n} br_matched={matched} br_unmatched={n-matched}")
    cur.execute("SELECT count(*) FROM player_lebron")
    print("[verify] player_lebron total:", cur.fetchone()[0])
    c.close()


if __name__ == "__main__":
    main()
