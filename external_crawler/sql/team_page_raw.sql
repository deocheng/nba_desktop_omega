-- ============================================================================
-- team_page_raw：BR 球队主页面「队级」统计表原始捕获层（长表，逐格 data-stat）
-- 设计：随 team_pbp 爬虫「访问一次主页面」时，顺带把同页上的**队级**统计表
--       （totals_stats / per_game_stats / per_poss / advanced / adj_shooting /
--        team_misc / team_and_opponent，及其 Playoffs 的 _post 变体）长表捕获，
--        实现「一次页面访问获得多项数据」；零额外网络请求。
--   注意：主页面 shooting 表是**球员级**（Rk/name_display/age/pos/games），
--        并非 team_shooting 的出手分布；后者在 /teams/{ABBR}/{YEAR}/shooting/
--        子页，需单独节流请求，不在此处处理。
-- 命名/样式对齐 team_pbp_raw（集群 B 5433 / nba，public 模式）。
-- ============================================================================

CREATE TABLE IF NOT EXISTS team_page_raw (
    team_abbr    text        NOT NULL,
    season       integer     NOT NULL,
    season_type  text        NOT NULL,   -- 'Regular' / 'Playoffs'
    table_id     text        NOT NULL,   -- 真实 id：'totals_stats' / 'totals_stats_post' ...
    row_label    text        NOT NULL DEFAULT '',  -- 行语义（'Team','Opponent','Shot Clock < 10'）
    data_stat    text        NOT NULL,   -- BR 原始 data-stat 名
    val          text,                     -- 原始文本（长表存 raw）
    source       text        DEFAULT 'br_crawler',
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (team_abbr, season, season_type, table_id, row_label, data_stat)
);

COMMENT ON TABLE team_page_raw IS
    'BR 球队主页队级统计表原始捕获层（长表）。由 team_pbp 爬虫同页顺带抽取（零额外请求），覆盖 totals_stats/per_game_stats/per_poss/advanced/adj_shooting/team_misc/team_and_opponent 及其 _post 季后赛变体。';

CREATE INDEX IF NOT EXISTS idx_team_page_raw_team_season
    ON team_page_raw (team_abbr, season, season_type);
CREATE INDEX IF NOT EXISTS idx_team_page_raw_table_id
    ON team_page_raw (table_id);
