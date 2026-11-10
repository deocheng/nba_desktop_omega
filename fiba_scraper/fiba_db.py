"""FIBA PostgreSQL layer — schema + idempotent upserts.

Connects to the existing local PG cluster (port 5433) into a dedicated `fiba`
database (created separately). DB credentials are read from the NBA project's
.env (same cluster) — set FIBA_ENV to override the path.

All writes are parameterized (psycopg2 %s) and idempotent (ON CONFLICT / DELETE+INSERT).
No dynamic SQL, no eval — table/column names are static literals from this module.
"""
from __future__ import annotations

import os
import re

import psycopg2
import psycopg2.extras as extras

# Default path to the .env that holds DB_* for the local PG cluster.
ENV_PATH = os.environ.get(
    "FIBA_ENV",
    "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env",
)


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


def get_conn(dbname: str = "fiba") -> psycopg2.extensions.connection:
    cfg = _load_cfg()
    return psycopg2.connect(
        host=cfg.get("DB_HOST", "localhost"),
        port=int(cfg.get("DB_PORT", 5433)),
        user=cfg.get("DB_USER", "postgres"),
        password=cfg.get("DB_PASSWORD", ""),
        dbname=dbname,
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS competitions (
    competition_id   INT PRIMARY KEY,
    competition_code TEXT,
    season           INT,
    official_name    TEXT,
    start_date       TIMESTAMPTZ,
    end_date         TIMESTAMPTZ,
    gender           TEXT,
    zone             TEXT
);

CREATE TABLE IF NOT EXISTS rounds (
    round_id        INT PRIMARY KEY,
    competition_id  INT REFERENCES competitions(competition_id),
    name            TEXT,
    type            TEXT
);

CREATE TABLE IF NOT EXISTS teams (
    org_id        INT PRIMARY KEY,
    code          TEXT,
    official_name TEXT,
    short_name    TEXT,
    country       TEXT,
    country_code  TEXT,
    logo_url      TEXT
);

CREATE TABLE IF NOT EXISTS players (
    player_id     BIGINT PRIMARY KEY,
    first_name    TEXT,
    last_name     TEXT,
    full_name     TEXT,
    nationality   TEXT,
    position_code TEXT,
    date_of_birth TIMESTAMPTZ,
    uniform_number INT,
    headshot_url TEXT
);

CREATE TABLE IF NOT EXISTS games (
    game_id              BIGINT PRIMARY KEY,
    competition_id      INT REFERENCES competitions(competition_id),
    round_id            INT REFERENCES rounds(round_id),
    technical_name      TEXT,
    team_a_org          INT REFERENCES teams(org_id),
    team_b_org          INT REFERENCES teams(org_id),
    team_a_score        INT,
    team_b_score        INT,
    status              TEXT,
    game_datetime_utc   TIMESTAMPTZ,
    venue_name          TEXT,
    host_city           TEXT,
    host_country        TEXT,
    spectators          INT,
    raw                 JSONB,
    pbp_loaded          BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS game_team_stats (
    game_id   BIGINT REFERENCES games(game_id),
    org_id    INT REFERENCES teams(org_id),
    is_winner BOOLEAN,
    score     INT,
    pts INT, fg_made INT, fg_att INT, fg3_made INT, fg3_att INT,
    ft_made INT, ft_att INT,
    oreb INT, dreb INT, reb INT, ast INT, stl INT, blk INT, tov INT, pf INT,
    raw_stats JSONB,
    PRIMARY KEY (game_id, org_id)
);

CREATE TABLE IF NOT EXISTS game_player_stats (
    game_id     BIGINT REFERENCES games(game_id),
    player_id   BIGINT REFERENCES players(player_id),
    org_id      INT REFERENCES teams(org_id),
    jersey      INT,
    is_starter  BOOLEAN,
    pts INT, fg_made INT, fg_att INT, fg3_made INT, fg3_att INT,
    ft_made INT, ft_att INT,
    oreb INT, dreb INT, reb INT, ast INT, stl INT, blk INT, tov INT, pf INT,
    plus_minus INT, eff INT,
    raw_stats JSONB,
    PRIMARY KEY (game_id, player_id)
);

CREATE TABLE IF NOT EXISTS play_by_play (
    event_id      BIGSERIAL PRIMARY KEY,
    game_id       BIGINT REFERENCES games(game_id),
    quarter       TEXT,
    seq_order     INT,
    event_time    TEXT,
    gt_epoch      BIGINT,
    score_a       INT,
    score_b       INT,
    act           TEXT,
    action_code   TEXT,
    description   TEXT,
    made          BOOLEAN,
    pts           INT,
    x             INT,
    y             INT,
    org_id        INT,
    player_id     BIGINT,
    raw           JSONB
);
CREATE INDEX IF NOT EXISTS ix_pbp_game ON play_by_play(game_id);

CREATE TABLE IF NOT EXISTS competition_player_game_highs (
    competition_id   INT,
    statistic_code   TEXT,
    rank             INT,
    person_id        BIGINT,
    first_name       TEXT,
    last_name        TEXT,
    nationality      TEXT,
    game_id          BIGINT,
    game_date        TIMESTAMPTZ,
    team_name        TEXT,
    team_score       INT,
    vs_team_name     TEXT,
    vs_team_score    INT,
    value            NUMERIC,
    raw_value        TEXT,
    pts INT, eff INT,
    fg2_made INT, fg2_att INT, fg3_made INT, fg3_att INT,
    ft_made INT, ft_att INT, ft_pct NUMERIC,
    raw              JSONB,
    PRIMARY KEY (competition_id, statistic_code, person_id, game_id)
);

CREATE TABLE IF NOT EXISTS competition_team_game_highs (
    competition_id     INT,
    statistic_code     TEXT,
    rank               INT,
    competition_team_id BIGINT,
    game_id            BIGINT,
    game_date          TIMESTAMPTZ,
    team_name          TEXT,
    team_score         INT,
    vs_team_name       TEXT,
    vs_team_score      INT,
    value              NUMERIC,
    raw_value          TEXT,
    raw                JSONB,
    PRIMARY KEY (competition_id, statistic_code, competition_team_id, game_id)
);

CREATE OR REPLACE VIEW v_game_shots AS
    SELECT * FROM play_by_play WHERE act = 'shot';
"""


def init_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
        # Loaded-marker for idempotent/resumable batch scraping.
        cur.execute(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS "
            "boxscore_loaded BOOLEAN NOT NULL DEFAULT FALSE"
        )
        # PBP capture-marker: once a game's live-feed PBP is captured we flag it
        # so daily re-runs never delete it after FIBA's retention window closes.
        cur.execute(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS "
            "pbp_loaded BOOLEAN NOT NULL DEFAULT FALSE"
        )
        # Migrate leaderboard PKs: game-high leaderboards have rank TIES, so the
        # natural key is the entity id, not (competition_id, statistic_code, rank).
        cur.execute(
            "ALTER TABLE competition_player_game_highs "
            "DROP CONSTRAINT IF EXISTS competition_player_game_highs_pkey")
        cur.execute(
            "ALTER TABLE competition_player_game_highs "
            "ADD PRIMARY KEY (competition_id, statistic_code, person_id, game_id)")
        cur.execute(
            "ALTER TABLE competition_team_game_highs "
            "DROP CONSTRAINT IF EXISTS competition_team_game_highs_pkey")
        cur.execute(
            "ALTER TABLE competition_team_game_highs "
            "ADD PRIMARY KEY (competition_id, statistic_code, competition_team_id, game_id)")
        # GAP-3 bio backfill: extend the players dimension with position /
        # birthdate / jersey (recoverable from boxscore player objects already
        # stored in game_player_stats.raw_stats). Idempotent.
        for col, typ in (
            ("position_code", "TEXT"),
            ("date_of_birth", "TIMESTAMPTZ"),
            ("uniform_number", "INT"),
        ):
            cur.execute(
                f"ALTER TABLE players ADD COLUMN IF NOT EXISTS {col} {typ}")
        # GAP-3 headshot: FIBA serves per-player headshots from a public
        # Cloudinary CDN keyed by player_id (no APIM key required). The canonical
        # URL is deterministic, so we store it on the players dimension. Idempotent.
        cur.execute(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS headshot_url TEXT")
    conn.commit()


def upsert_many(conn, table: str, cols: list, pk_cols: list, rows: list,
                page_size: int = 200) -> None:
    """Idempotent bulk insert. Table/column names are static literals (safe)."""
    if not rows:
        return
    col_sql = ", ".join(cols)
    set_sql = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in pk_cols)
    # execute_values expands the single %s into the (...),(...) value groups.
    sql = (f"INSERT INTO {table} ({col_sql}) VALUES %s "
           f"ON CONFLICT ({', '.join(pk_cols)}) DO UPDATE SET {set_sql}")
    with conn.cursor() as cur:
        extras.execute_values(cur, sql, rows, page_size=page_size)
    conn.commit()


def delete_game_events(conn, game_id: int) -> None:
    """Remove existing PBP rows for a game before re-insert (idempotent reload)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM play_by_play WHERE game_id=%s", (game_id,))
    conn.commit()
