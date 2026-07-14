-- db/espn_boxscore.sql
-- ============================================================================
-- espn_boxscore —— ESPN 宽数据集最小可用集（依 OQ-c）
-- 归档来自 ESPN Site API v2 summary 的球队盒式 + 球员盒式 + 投篮坐标。
-- raw_json_path 指回 raw_archive/espn/{date}/{event}.json 原始响应，可离线重解析。
-- ============================================================================
CREATE TABLE IF NOT EXISTS espn_boxscore (
    id              BIGSERIAL PRIMARY KEY,
    espn_event      VARCHAR(20)  NOT NULL,
    br_gid          VARCHAR(20),
    nba_api_id      VARCHAR(20),
    game_date       DATE,
    season          SMALLINT,
    season_type     VARCHAR(24),
    home_abbr       VARCHAR(3),
    away_abbr       VARCHAR(3),
    home_pts        SMALLINT,
    away_pts        SMALLINT,
    home_team_box   JSONB,        -- ESPN teams[] 中主队盒式
    away_team_box   JSONB,        -- ESPN teams[] 中客队盒式
    player_boxes    JSONB,        -- players[] 全量球员盒式数组
    shot_coords     JSONB,        -- [{player_id, player_name, team, period, clock, x, y, made}]
    raw_json_path   TEXT,         -- raw_archive/espn/{date}/{event}.json 指针
    archived_at     TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (espn_event)
);

CREATE INDEX IF NOT EXISTS idx_eb_brgid ON espn_boxscore (br_gid);
CREATE INDEX IF NOT EXISTS idx_eb_date  ON espn_boxscore (game_date);
