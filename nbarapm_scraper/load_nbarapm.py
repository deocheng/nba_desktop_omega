#!/usr/bin/env python3
"""
load_nbarapm.py  --  Load nbarapm_rapm.jsonl into the `nba` DB as `player_rapm`.

Idempotent upsert keyed on (nba_id, snapshot_date). Br_player_id is resolved
from player_id_bridge (nba_player_id::text = nba_id::text) so the metrics join
to the project's canonical BR slug key where possible.

Usage:
  python load_nbarapm.py [--jsonl nbarapm_rapm.jsonl]
"""
import os
import sys
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    sys.stderr.write("psycopg2 not available in this interpreter\n")
    sys.exit(2)


def read_dotenv(path):
    cfg = {}
    if not os.path.exists(path):
        return cfg
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip()
    return cfg


def get_conn():
    root = os.path.dirname(HERE)
    cfg = read_dotenv(os.path.join(root, ".env"))
    return psycopg2.connect(
        host=cfg.get("DB_HOST", "localhost"),
        port=int(cfg.get("DB_PORT", 5433)),
        dbname=cfg.get("DB_NAME", "nba"),
        user=cfg.get("DB_USER", "postgres"),
        password=cfg.get("DB_PASSWORD", ""),
    )


DDL = """
CREATE TABLE IF NOT EXISTS player_rapm (
    nba_id        BIGINT        NOT NULL,
    player_name   TEXT,
    team_abbr     TEXT,
    position      TEXT,
    snapshot_date DATE          NOT NULL,
    rapm_total    NUMERIC(7,3),
    rapm_rank     INTEGER,
    rapm_pop      INTEGER,
    ots           NUMERIC(7,3),
    otov          NUMERIC(7,3),
    osc           NUMERIC(7,3),
    dts           NUMERIC(7,3),
    dtov          NUMERIC(7,3),
    dsc           NUMERIC(7,3),
    rapm_sum      NUMERIC(7,3),
    on_off_net    NUMERIC(7,3),
    on_court_net  NUMERIC(7,3),
    off_rtg       NUMERIC(7,3),
    def_rtg       NUMERIC(7,3),
    br_player_id  TEXT,
    has_bundle    BOOLEAN,
    PRIMARY KEY (nba_id, snapshot_date)
);
"""

COLUMNS = ["nba_id", "player_name", "team_abbr", "position", "snapshot_date",
           "rapm_total", "rapm_rank", "rapm_pop", "ots", "otov", "osc", "dts",
           "dtov", "dsc", "rapm_sum", "on_off_net", "on_court_net", "off_rtg",
           "def_rtg", "br_player_id", "has_bundle"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default=os.path.join(HERE, "nbarapm_rapm.jsonl"))
    ap.add_argument("--resolve-br", action="store_true",
                    help="resolve br_player_id via player_id_bridge (slower)")
    args = ap.parse_args()

    if not os.path.exists(args.jsonl):
        sys.stderr.write(f"[fatal] jsonl not found: {args.jsonl}\n")
        sys.exit(2)

    rows = [json.loads(l) for l in open(args.jsonl) if l.strip()]
    print(f"[info] loaded {len(rows)} records from {args.jsonl}")

    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
                # optional BR slug resolution
                bridge = {}
                if args.resolve_br:
                    cur.execute(
                        "SELECT nba_player_id, br_player_id FROM player_id_bridge "
                        "WHERE nba_player_id IS NOT NULL AND br_player_id IS NOT NULL")
                    for nba_id, br in cur.fetchall():
                        try:
                            bridge[str(int(nba_id))] = br
                        except Exception:
                            bridge[str(nba_id)] = br
                # upsert
                insert = sql.SQL(
                    "INSERT INTO player_rapm ({cols}) VALUES %s "
                    "ON CONFLICT (nba_id, snapshot_date) DO UPDATE SET "
                    "player_name=EXCLUDED.player_name, team_abbr=EXCLUDED.team_abbr, "
                    "position=EXCLUDED.position, rapm_total=EXCLUDED.rapm_total, "
                    "rapm_rank=EXCLUDED.rapm_rank, rapm_pop=EXCLUDED.rapm_pop, "
                    "ots=EXCLUDED.ots, otov=EXCLUDED.otov, osc=EXCLUDED.osc, "
                    "dts=EXCLUDED.dts, dtov=EXCLUDED.dtov, dsc=EXCLUDED.dsc, "
                    "rapm_sum=EXCLUDED.rapm_sum, on_off_net=EXCLUDED.on_off_net, "
                    "on_court_net=EXCLUDED.on_court_net, off_rtg=EXCLUDED.off_rtg, "
                    "def_rtg=EXCLUDED.def_rtg, br_player_id=EXCLUDED.br_player_id, "
                    "has_bundle=EXCLUDED.has_bundle"
                ).format(cols=sql.SQL(", ").join(map(sql.Identifier, COLUMNS)))
                tuples = []
                for r in rows:
                    br = bridge.get(str(r["nba_id"])) if args.resolve_br else None
                    tuples.append((
                        r.get("nba_id"), r.get("player_name"), r.get("team_abbr"),
                        r.get("position"), r.get("snapshot_date"),
                        r.get("rapm_total"), r.get("rapm_rank"), r.get("rapm_pop"),
                        r.get("ots"), r.get("otov"), r.get("osc"), r.get("dts"),
                        r.get("dtov"), r.get("dsc"), r.get("rapm_sum"),
                        r.get("on_off_net"), r.get("on_court_net"),
                        r.get("off_rtg"), r.get("def_rtg"), br, r.get("has_bundle"),
                    ))
                from psycopg2.extras import execute_values
                execute_values(cur, insert, tuples, page_size=200)
                cur.execute("SELECT count(*) FROM player_rapm")
                total = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM player_rapm WHERE has_bundle")
                with_bundle = cur.fetchone()[0]
        print(f"[done] player_rapm rows={total} (with_bundle={with_bundle})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
