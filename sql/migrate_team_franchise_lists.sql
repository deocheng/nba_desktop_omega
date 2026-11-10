-- 迁移：把 numbers/hof/all_star 三张「通用网格」表改为有意义的列结构
-- （这三页是 BR leaderboard_grid div 布局，非 <table>，需专用列而非 row_idx/col_idx）。
-- 玩家/对阵两页（players/head2head）是真 <table>，维持通用网格不变。
DROP TABLE IF EXISTS team_franchise_hof      CASCADE;
DROP TABLE IF EXISTS team_franchise_all_star CASCADE;
DROP TABLE IF EXISTS team_franchise_numbers  CASCADE;

-- 名人堂：赛季（如 '2018-19'）→ 入选球员
CREATE TABLE IF NOT EXISTS team_franchise_hof (
    team_abbr    text        NOT NULL,
    franchise_id integer,
    season       text        NOT NULL,
    player_name  text        NOT NULL,
    br_slug      text,
    source       text        DEFAULT 'br_crawler',
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (team_abbr, season, player_name)
);
CREATE INDEX IF NOT EXISTS idx_tfhof_team ON team_franchise_hof(team_abbr);

-- 全明星：赛季（如 '2025-26'）→ 入选球员
CREATE TABLE IF NOT EXISTS team_franchise_all_star (
    team_abbr    text        NOT NULL,
    franchise_id integer,
    season       text        NOT NULL,
    player_name  text        NOT NULL,
    br_slug      text,
    source       text        DEFAULT 'br_crawler',
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (team_abbr, season, player_name)
);
CREATE INDEX IF NOT EXISTS idx_tfas_team ON team_franchise_all_star(team_abbr);

-- 球衣号码：section ∈ {'retired'=退役/荣誉号码, 'combinations'=历史穿用组合}
--  number=号码(如 '00','6','UNK')；years=年段(仅 combinations)；br_slug 仅 combinations。
CREATE TABLE IF NOT EXISTS team_franchise_numbers (
    team_abbr    text        NOT NULL,
    franchise_id integer,
    section      text        NOT NULL,
    number       text        NOT NULL,
    player_name  text        NOT NULL,
    br_slug      text,
    years        text,
    source       text        DEFAULT 'br_crawler',
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (team_abbr, section, number, player_name)
);
CREATE INDEX IF NOT EXISTS idx_tfn_team ON team_franchise_numbers(team_abbr);
