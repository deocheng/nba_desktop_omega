-- migrate_team_referees.sql — 2026-07-28
-- 真相（SAS/2026 实抓）：BR 裁判页真实 URL = /teams/{ABBR}/{YEAR}_referees.html，
-- 表 id = refs-summary，粒度 = team×season×referee 的**赛季汇总**（非逐场）。
-- 列 data-stat: rank/referee/g/wins/losses/win_pct/pace/
--   team_pts/team_fta/team_pf/team_sfoul/team_ofoul/
--   opp_pts/opp_fta/opp_pf/opp_sfoul/opp_ofoul/
--   diff_pts/diff_fta/diff_pf/diff_sfoul/diff_ofoul
-- 处置：新建 team_referees 承接该页；game_referees（逐场）保留空表，
-- 其数据源在 box score 主页，另行决策。

CREATE TABLE IF NOT EXISTS team_referees (
    id            BIGSERIAL PRIMARY KEY,
    team_abbr     TEXT NOT NULL,
    season        INTEGER NOT NULL,
    referee_slug  TEXT NOT NULL,          -- /referees/{slug}.html
    referee_name  TEXT NOT NULL,
    rank          SMALLINT,
    g             SMALLINT,
    wins          SMALLINT,
    losses        SMALLINT,
    win_pct       DOUBLE PRECISION,
    pace          DOUBLE PRECISION,
    team_pts      DOUBLE PRECISION,
    team_fta      DOUBLE PRECISION,
    team_pf       DOUBLE PRECISION,
    team_sfoul    DOUBLE PRECISION,       -- shooting fouls drawn (per game avg)
    team_ofoul    DOUBLE PRECISION,       -- offensive fouls
    opp_pts       DOUBLE PRECISION,
    opp_fta       DOUBLE PRECISION,
    opp_pf        DOUBLE PRECISION,
    opp_sfoul     DOUBLE PRECISION,
    opp_ofoul     DOUBLE PRECISION,
    diff_pts      DOUBLE PRECISION,
    diff_fta      DOUBLE PRECISION,
    diff_pf       DOUBLE PRECISION,
    diff_sfoul    DOUBLE PRECISION,
    diff_ofoul    DOUBLE PRECISION,
    source        TEXT DEFAULT 'basketball-reference',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (team_abbr, season, referee_slug)
);
CREATE INDEX IF NOT EXISTS idx_team_referees_season ON team_referees (season);
CREATE INDEX IF NOT EXISTS idx_team_referees_ref ON team_referees (referee_slug);
