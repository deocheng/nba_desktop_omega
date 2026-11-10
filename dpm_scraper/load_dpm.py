#!/usr/bin/env python3
"""
load_dpm.py -- Load DARKO DPM (from darko.app) into the `nba` DB as `player_dpm`.

Source: darko_players.json (extracted from darko.app homepage hydration; 530 players
with nba_id + dpm / o_dpm / d_dpm / box_dpm / on_off_dpm + salary fields).

Alignment: DARKO keys players by NBA numeric id (`nba_id`). The project's canonical
player key is `br_player_id` (Basketball-Reference slug). We resolve br_player_id via
the local `player_id_bridge` (nba_player_id::text = nba_id::text). Unmatched players
fall back to a normalized name match against player_id_bridge.player_name, then
dim_players.player_name/full_name. Players still unresolved keep br_player_id NULL
but retain nba_id so they remain joinable later.

Idempotent upsert keyed on (nba_id, snapshot_date).
"""
import os
import sys
import json
import argparse
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import execute_values
except ImportError:
    sys.stderr.write("psycopg2 not available\n")
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
CREATE TABLE IF NOT EXISTS player_dpm (
    nba_id          BIGINT        NOT NULL,
    br_player_id    TEXT,
    player_name     TEXT,
    team_name       TEXT,
    tm_id           BIGINT,
    position        TEXT,
    season          INTEGER,
    career_game_num INTEGER,
    dpm             NUMERIC(7,3),
    o_dpm           NUMERIC(7,3),
    d_dpm           NUMERIC(7,3),
    box_dpm         NUMERIC(7,3),
    on_off_dpm      NUMERIC(7,3),
    x_minutes       NUMERIC(7,3),
    x_pace          NUMERIC(7,3),
    x_pts_100       NUMERIC(7,3),
    x_ast_100       NUMERIC(7,3),
    x_fg_pct        NUMERIC(7,3),
    x_fg3_pct       NUMERIC(7,3),
    x_ft_pct        NUMERIC(7,3),
    sal_market_fixed NUMERIC(14,2),
    actual_salary   NUMERIC(14,2),
    surplus_value   NUMERIC(14,2),
    dpm_rank        INTEGER,
    snapshot_date   DATE          NOT NULL,
    raw_json        JSONB,
    PRIMARY KEY (nba_id, snapshot_date)
);
"""

COLUMNS = ["nba_id", "br_player_id", "player_name", "team_name", "tm_id", "position",
           "season", "career_game_num", "dpm", "o_dpm", "d_dpm", "box_dpm", "on_off_dpm",
           "x_minutes", "x_pace", "x_pts_100", "x_ast_100", "x_fg_pct", "x_fg3_pct",
           "x_ft_pct", "sal_market_fixed", "actual_salary", "surplus_value", "dpm_rank",
           "snapshot_date", "raw_json"]


def norm(s):
    if not s:
        return ""
    s = str(s).lower().strip()
    for c in "'-.":
        s = s.replace(c, " ")
    return " ".join(s.split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(HERE, "darko_players.json"))
    args = ap.parse_args()

    with open(args.json) as fh:
        data = json.load(fh)
    rows = data if isinstance(data, list) else data.get("players", [])
    print(f"[info] {len(rows)} DPM records to load")

    snap = date.today().isoformat()
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
                # Build nba_id -> br_player_id map from local bridge
                cur.execute(
                    "SELECT nba_player_id, br_player_id, player_name FROM player_id_bridge "
                    "WHERE nba_player_id IS NOT NULL AND br_player_id IS NOT NULL")
                id_to_br = {}
                br_name = {}
                for nid, br, pname in cur.fetchall():
                    try:
                        id_to_br[str(int(nid))] = br
                    except Exception:
                        id_to_br[str(nid)] = br
                    if pname:
                        br_name[norm(pname)] = br
                # dim_players name fallback
                cur.execute(
                    "SELECT player_id, player_name, full_name FROM dim_players "
                    "WHERE player_name IS NOT NULL")
                dim_name = {}
                for pid, pname, fname in cur.fetchall():
                    if pname:
                        dim_name[norm(pname)] = pid
                    if fname:
                        dim_name[norm(fname)] = pid

                matched, unmatched = 0, []
                tuples = []
                for r in rows:
                    nid = r.get("nba_id")
                    br = id_to_br.get(str(nid)) if nid is not None else None
                    if not br:
                        # name fallback
                        nb = br_name.get(norm(r.get("player_name")))
                        if nb:
                            br = nb
                    if br:
                        matched += 1
                    else:
                        unmatched.append(r.get("player_name"))
                    tuples.append((
                        nid, br, r.get("player_name"), r.get("team_name"), r.get("tm_id"),
                        r.get("position"), r.get("season"), r.get("career_game_num"),
                        r.get("dpm"), r.get("o_dpm"), r.get("d_dpm"), r.get("box_dpm"),
                        r.get("on_off_dpm"), r.get("x_minutes"), r.get("x_pace"),
                        r.get("x_pts_100"), r.get("x_ast_100"), r.get("x_fg_pct"),
                        r.get("x_fg3_pct"), r.get("x_ft_pct"), r.get("sal_market_fixed"),
                        r.get("actual_salary"), r.get("surplus_value"), r.get("_rank"),
                        snap, json.dumps(r, ensure_ascii=False),
                    ))
                insert = sql.SQL(
                    "INSERT INTO player_dpm ({cols}) VALUES %s "
                    "ON CONFLICT (nba_id, snapshot_date) DO UPDATE SET "
                    "br_player_id=EXCLUDED.br_player_id, player_name=EXCLUDED.player_name, "
                    "team_name=EXCLUDED.team_name, tm_id=EXCLUDED.tm_id, position=EXCLUDED.position, "
                    "season=EXCLUDED.season, career_game_num=EXCLUDED.career_game_num, "
                    "dpm=EXCLUDED.dpm, o_dpm=EXCLUDED.o_dpm, d_dpm=EXCLUDED.d_dpm, "
                    "box_dpm=EXCLUDED.box_dpm, on_off_dpm=EXCLUDED.on_off_dpm, "
                    "x_minutes=EXCLUDED.x_minutes, x_pace=EXCLUDED.x_pace, "
                    "x_pts_100=EXCLUDED.x_pts_100, x_ast_100=EXCLUDED.x_ast_100, "
                    "x_fg_pct=EXCLUDED.x_fg_pct, x_fg3_pct=EXCLUDED.x_fg3_pct, "
                    "x_ft_pct=EXCLUDED.x_ft_pct, sal_market_fixed=EXCLUDED.sal_market_fixed, "
                    "actual_salary=EXCLUDED.actual_salary, surplus_value=EXCLUDED.surplus_value, "
                    "dpm_rank=EXCLUDED.dpm_rank, raw_json=EXCLUDED.raw_json"
                ).format(cols=sql.SQL(", ").join(map(sql.Identifier, COLUMNS)))
                execute_values(cur, insert, tuples, page_size=200)
                cur.execute("SELECT count(*) FROM player_dpm")
                total = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM player_dpm WHERE br_player_id IS NOT NULL")
                with_br = cur.fetchone()[0]
        print(f"[done] player_dpm rows={total} (with br_player_id={with_br}, "
              f"matched={matched}, unmatched={len(unmatched)})")
        if unmatched:
            print("[unmatched by br_player_id] (kept with nba_id only):")
            print("  " + ", ".join(unmatched))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
