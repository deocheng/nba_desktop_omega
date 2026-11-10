#!/usr/bin/env python3
"""
extract_rapm_history.py — materialize per-season RAPM history from the cached
nbarapm bundles (raw_archive/<nba_id>.json) into a new `player_rapm_history`
table in the `nba` DB.

Context
-------
`scrape_nbarapm.py` already harvested every player's 1.5MB analytics bundle and
cached it to raw_archive/. The bundle's `dashboard` block only exposes the
CURRENT (time-decay) 6-factor RAPM — that already lives in `player_rapm`.
But `scposs.rs` / `scposs.ps` carry the full **per-season** RAPM as 9 time-decay
windows (Year_Interval 1Y..8Y, plus TD) x N seasons. The single-season estimate
(Year_Interval == "1Y") is the genuine season-by-season RAPM — and it was NEVER
loaded into any table. This script closes that gap by extracting the "1Y" rows.

Zero network. Pure local read of the cache. Idempotent (ON CONFLICT upsert).

DB writes follow the standing §6 rules: psycopg2.sql.Identifier for every
table/column name, %s for all values, no dynamic SQL / eval, independent
connection, pre-check + post-check row counts.

Usage:
    .venv/bin/python extract_rapm_history.py [--cache-dir raw_archive]
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras as extras
from psycopg2 import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.nba_paths import ENV_FILE

ENV_PATH = os.environ.get(
    "FIBA_ENV",
    str(ENV_FILE),
)
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "raw_archive")

# Static column list (table + column names are literals from this module only).
COLUMNS = [
    "nba_id", "season", "is_playoff", "player_name", "team_abbr", "position",
    "ovr_rapm", "orapm", "drapm", "ovr_rapm_rank", "rapm_rank", "def_rapm_rank",
    "off_poss", "def_poss", "possessions",
    "orapm_decomp_tov", "orapm_decomp_sc", "orapm_decomp_shot",
    "orapm_decomp_ft", "orapm_decomp_scoring",
    "drapm_decomp_tov", "drapm_decomp_sc", "drapm_decomp_shot",
    "drapm_decomp_ft", "drapm_decomp_scoring",
    "nrapm_decomp_tov", "nrapm_decomp_sc", "nrapm_decomp_shot",
    "nrapm_decomp_ft", "nrapm_decomp_scoring",
    "as_of_date", "raw",
]
PK = ["nba_id", "season", "is_playoff"]

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS player_rapm_history (
    nba_id        BIGINT NOT NULL,
    season        INTEGER NOT NULL,
    is_playoff    BOOLEAN NOT NULL DEFAULT FALSE,
    player_name   TEXT,
    team_abbr     TEXT,
    position      TEXT,
    ovr_rapm      NUMERIC,
    orapm         NUMERIC,
    drapm         NUMERIC,
    ovr_rapm_rank INTEGER,
    rapm_rank     INTEGER,
    def_rapm_rank INTEGER,
    off_poss      NUMERIC,
    def_poss      NUMERIC,
    possessions   NUMERIC,
    orapm_decomp_tov     NUMERIC,
    orapm_decomp_sc      NUMERIC,
    orapm_decomp_shot    NUMERIC,
    orapm_decomp_ft      NUMERIC,
    orapm_decomp_scoring NUMERIC,
    drapm_decomp_tov     NUMERIC,
    drapm_decomp_sc      NUMERIC,
    drapm_decomp_shot    NUMERIC,
    drapm_decomp_ft      NUMERIC,
    drapm_decomp_scoring NUMERIC,
    nrapm_decomp_tov     NUMERIC,
    nrapm_decomp_sc      NUMERIC,
    nrapm_decomp_shot    NUMERIC,
    nrapm_decomp_ft      NUMERIC,
    nrapm_decomp_scoring NUMERIC,
    as_of_date    TEXT,
    raw           JSONB,
    PRIMARY KEY (nba_id, season, is_playoff)
)
"""


def _load_cfg() -> dict:
    cfg = {}
    try:
        for line in open(ENV_PATH, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Z0-9_]+)\s*=\s*(.*)$", line)
            if m:
                cfg[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return cfg


def connect():
    cfg = _load_cfg()
    return psycopg2.connect(
        host=cfg.get("DB_HOST", "localhost"),
        port=int(cfg.get("DB_PORT", 5433)),
        user=cfg.get("DB_USER", "postgres"),
        password=cfg.get("DB_PASSWORD", ""),
        dbname=cfg.get("DB_NAME", "nba"),
    )


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def extract_rows(bundle: dict) -> list:
    """Pull the single-season (Year_Interval=='1Y') RAPM rows from a bundle."""
    out = []
    sc = (bundle or {}).get("scposs") or {}
    for section, is_playoff in (("rs", False), ("ps", True)):
        for r in (sc.get(section) or []):
            if r.get("Year_Interval") != "1Y":
                continue
            season = _int(r.get("Latest_Year"))
            if season is None:
                continue
            nid = _int(r.get("nba_id")) or _int(r.get("nba_id_str"))
            if nid is None:
                continue
            out.append((
                nid, season, is_playoff,
                r.get("player_name"), r.get("team_abbreviation") or r.get("team_abbr"),
                r.get("Position") or r.get("position") or r.get("Pos2"),
                _num(r.get("OVR_RAPM")), _num(r.get("Off_RAPM")), _num(r.get("Def_RAPM")),
                _int(r.get("OVR_RAPM_rank")), _int(r.get("Off_RAPM_rank")),
                _int(r.get("Def_RAPM_rank")),
                _num(r.get("Off_Poss")), _num(r.get("Def_Poss")),
                _num(r.get("possessions")),
                _num(r.get("oRAPM_DECOMP_TOV")), _num(r.get("oRAPM_DECOMP_SC")),
                _num(r.get("oRAPM_DECOMP_SHOT")), _num(r.get("oRAPM_DECOMP_FT")),
                _num(r.get("oRAPM_DECOMP_SCORING")),
                _num(r.get("dRAPM_DECOMP_TOV")), _num(r.get("dRAPM_DECOMP_SC")),
                _num(r.get("dRAPM_DECOMP_SHOT")), _num(r.get("dRAPM_DECOMP_FT")),
                _num(r.get("dRAPM_DECOMP_SCORING")),
                _num(r.get("nRAPM_DECOMP_TOV")), _num(r.get("nRAPM_DECOMP_SC")),
                _num(r.get("nRAPM_DECOMP_SHOT")), _num(r.get("nRAPM_DECOMP_FT")),
                _num(r.get("nRAPM_DECOMP_SCORING")),
                str(r.get("as_of_date")) if r.get("as_of_date") else None,
                json.dumps(r, ensure_ascii=False),
            ))
    return out


def main() -> None:
    cache_dir = sys.argv[1] if len(sys.argv) > 1 else CACHE_DIR
    files = sorted(glob.glob(os.path.join(cache_dir, "*.json")))
    print(f"[info] {len(files)} cached bundles in {cache_dir}")

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_SQL)
            cur.execute("SELECT COUNT(*) FROM player_rapm_history")
            pre = cur.fetchone()[0]
        conn.commit()
        print(f"[pre-check] player_rapm_history rows before = {pre}")

        col_ids = [sql.Identifier(c) for c in COLUMNS]
        pk_ids = [sql.Identifier(c) for c in PK]
        set_clause = ", ".join(
            f"{sql.Identifier(c).as_string(conn)}=EXCLUDED.{sql.Identifier(c).as_string(conn)}"
            for c in COLUMNS if c not in PK
        )
        insert_sql = sql.SQL(
            "INSERT INTO {tbl} ({cols}) VALUES %s ON CONFLICT ({pk}) DO UPDATE SET {set}"
        ).format(
            tbl=sql.Identifier("player_rapm_history"),
            cols=sql.SQL(", ").join(col_ids),
            pk=sql.SQL(", ").join(pk_ids),
            set=sql.SQL(set_clause),
        )

        total = 0
        players = 0
        for fp in files:
            try:
                bundle = json.load(open(fp, encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                print(f"  [skip] {fp}: {e}")
                continue
            rows = extract_rows(bundle)
            if not rows:
                continue
            with conn.cursor() as cur:
                extras.execute_values(cur, insert_sql, rows, page_size=200)
            conn.commit()
            total += len(rows)
            players += 1

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM player_rapm_history")
            post = cur.fetchone()[0]
            cur.execute(
                "SELECT nba_id, season, ovr_rapm, orapm, drapm, ovr_rapm_rank "
                "FROM player_rapm_history WHERE nba_id=1628983 ORDER BY season")
            sample = cur.fetchall()
        print(f"[post-check] player_rapm_history rows after = {post} "
              f"(+{post - pre}); bundles processed = {players}; rows extracted = {total}")
        print("  SGA(1628983) season history sample:")
        for row in sample:
            print("   ", row)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
