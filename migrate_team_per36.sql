-- migrate_team_per36.sql
-- BR 球队页 #per_minute_stats 实为「逐球员」Per-36 表（非 Team/Opponent 汇总），
-- 原 team_per_36 设计的 team_type 行与真实数据不符 → 重建为逐球员表。
-- team_leaderboards 去掉无用的 value 列（以 rank 为准）。
-- 注意：仅重建这两张空表，team_roster / team_coaches（已有数据）不动。

DROP TABLE IF EXISTS team_per_36;
CREATE TABLE IF NOT EXISTS team_per_36 (
    team_abbr      TEXT    NOT NULL,
    season         INTEGER NOT NULL,
    season_type    TEXT    NOT NULL DEFAULT 'Regular',
    player_slug    TEXT    NOT NULL,
    player_name    TEXT,
    pos            TEXT,
    g              INTEGER,
    gs             INTEGER,
    mp             INTEGER,
    fg             DOUBLE PRECISION, fga DOUBLE PRECISION, fg_pct DOUBLE PRECISION,
    x3p            DOUBLE PRECISION, x3pa DOUBLE PRECISION, x3p_pct DOUBLE PRECISION,
    x2p            DOUBLE PRECISION, x2pa DOUBLE PRECISION, x2p_pct DOUBLE PRECISION,
    efg_pct        DOUBLE PRECISION,
    ft             DOUBLE PRECISION, fta DOUBLE PRECISION, ft_pct DOUBLE PRECISION,
    orb            DOUBLE PRECISION, drb DOUBLE PRECISION, trb DOUBLE PRECISION,
    ast            DOUBLE PRECISION, stl DOUBLE PRECISION, blk DOUBLE PRECISION,
    tov            DOUBLE PRECISION, pf DOUBLE PRECISION, pts DOUBLE PRECISION,
    awards         TEXT,
    source         TEXT    DEFAULT 'br_crawler',
    created_at     TIMESTAMP DEFAULT now(),
    PRIMARY KEY (team_abbr, season, season_type, player_slug)
);

DROP TABLE IF EXISTS team_leaderboards;
CREATE TABLE IF NOT EXISTS team_leaderboards (
    team_abbr      TEXT    NOT NULL,
    season         INTEGER NOT NULL,
    player_slug    TEXT,
    player_name    TEXT,
    leaderboard    TEXT    NOT NULL,
    rank           INTEGER,
    source         TEXT    DEFAULT 'br_crawler',
    created_at     TIMESTAMP DEFAULT now(),
    PRIMARY KEY (team_abbr, season, player_slug, leaderboard)
);

CREATE INDEX IF NOT EXISTS idx_team_per_36_team_season
    ON team_per_36 (team_abbr, season);
CREATE INDEX IF NOT EXISTS idx_team_leaderboards_team_season
    ON team_leaderboards (team_abbr, season);
