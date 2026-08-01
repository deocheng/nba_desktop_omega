-- create_team_page_extras_tables.sql
-- 球队主页面 Group A 缺失板块（Roster / Per 36 / Coaches / Leaderboards）对应表。
-- 这些板块都在 /teams/{ABBR}/{YEAR}.html 同一份 HTML 内，由
-- crawl_br_team_page_extras.py 一次抓取解析落库（类比球员页 crawl_br_player_page_extras.py）。
-- 已存在的 team_stats_per_game / team_totals / team_stats_per_100_poss /
-- team_summaries / fact_team_season_stats / team_page_raw 不重建、不冲突。

-- ── 1) team_roster：花名册（每球员一行）──────────────────────────────
CREATE TABLE IF NOT EXISTS team_roster (
    team_abbr      TEXT    NOT NULL,
    season         INTEGER NOT NULL,          -- 赛季结束年
    player_slug    TEXT    NOT NULL,          -- BR slug（来自 /players/ 链接）
    player_name    TEXT,
    jersey         TEXT,                      -- 球衣号（No.）
    pos            TEXT,                      -- 位置（可能组合如 PG-SF，留 VARCHAR(8) 余量）
    height         TEXT,                      -- 如 "6-6"
    weight         TEXT,                      -- 如 "215lb" 或纯数字
    birth_date     TEXT,
    experience     TEXT,                      -- "Rookie" 或 "10"
    college        TEXT,
    source         TEXT    DEFAULT 'br_crawler',
    created_at     TIMESTAMP DEFAULT now(),
    PRIMARY KEY (team_abbr, season, player_slug)
);

-- ── 2) team_per_36：球队 Per 36 Minutes 汇总（Team/Opponent 行）──────
-- 列集与 team_totals 同源（BR 队级统计口径一致），仅数值为每 36 分钟。
CREATE TABLE IF NOT EXISTS team_per_36 (
    team_abbr      TEXT    NOT NULL,
    season         INTEGER NOT NULL,
    season_type    TEXT    NOT NULL DEFAULT 'Regular',
    team_type      TEXT    NOT NULL DEFAULT 'Team',  -- 'Team' / 'Opponent'
    g              INTEGER,
    mp             INTEGER,
    fg             INTEGER, fga INTEGER, fg_percent DOUBLE PRECISION,
    x3p            INTEGER, x3pa INTEGER, x3p_percent DOUBLE PRECISION,
    x2p            INTEGER, x2pa INTEGER, x2p_percent DOUBLE PRECISION,
    ft             INTEGER, fta INTEGER, ft_percent DOUBLE PRECISION,
    orb            INTEGER, drb INTEGER, trb INTEGER,
    ast            INTEGER, stl INTEGER, blk INTEGER, tov INTEGER, pf INTEGER, pts INTEGER,
    opp_fg         INTEGER, opp_fga INTEGER, opp_fg_percent DOUBLE PRECISION,
    opp_x3p        INTEGER, opp_x3pa INTEGER, opp_x3p_percent DOUBLE PRECISION,
    opp_x2p        INTEGER, opp_x2pa INTEGER, opp_x2p_percent DOUBLE PRECISION,
    opp_ft         INTEGER, opp_fta INTEGER, opp_ft_percent DOUBLE PRECISION,
    opp_orb        INTEGER, opp_drb INTEGER, opp_trb INTEGER,
    opp_ast        INTEGER, opp_stl INTEGER, opp_blk INTEGER, opp_tov INTEGER,
    opp_pf         INTEGER, opp_pts INTEGER,
    source         TEXT    DEFAULT 'br_crawler',
    created_at     TIMESTAMP DEFAULT now(),
    PRIMARY KEY (team_abbr, season, season_type, team_type)
);

-- ── 3) team_coaches：球队季教练组（Head/Assistant）──────────────────
CREATE TABLE IF NOT EXISTS team_coaches (
    team_abbr      TEXT    NOT NULL,
    season         INTEGER NOT NULL,
    coach_name     TEXT    NOT NULL,
    role           TEXT,                      -- 'Head Coach' / 'Assistant Coach' 等
    coach_slug     TEXT,                      -- 来自 /coaches/ 链接（若有）
    source         TEXT    DEFAULT 'br_crawler',
    created_at     TIMESTAMP DEFAULT now(),
    PRIMARY KEY (team_abbr, season, coach_name, role)
);

-- ── 4) team_leaderboards：球队登上联盟 Leaderboards 的球员 ────────────
CREATE TABLE IF NOT EXISTS team_leaderboards (
    team_abbr      TEXT    NOT NULL,
    season         INTEGER NOT NULL,
    player_slug    TEXT,
    player_name    TEXT,
    leaderboard    TEXT    NOT NULL,          -- 类别，如 'PTS' / 'TRB'
    rank           INTEGER,
    value          TEXT,
    source         TEXT    DEFAULT 'br_crawler',
    created_at     TIMESTAMP DEFAULT now(),
    PRIMARY KEY (team_abbr, season, player_slug, leaderboard)
);

-- 索引（按队季反查）
CREATE INDEX IF NOT EXISTS idx_team_roster_team_season
    ON team_roster (team_abbr, season);
CREATE INDEX IF NOT EXISTS idx_team_per_36_team_season
    ON team_per_36 (team_abbr, season);
CREATE INDEX IF NOT EXISTS idx_team_coaches_team_season
    ON team_coaches (team_abbr, season);
CREATE INDEX IF NOT EXISTS idx_team_leaderboards_team_season
    ON team_leaderboards (team_abbr, season);
