-- db/player_onoff.sql — BR 球员级 on-off 数据表（player_onoff）+ 404 隔离表。
--
-- 数据源：https://www.basketball-reference.com/players/{letter}/{slug}/on-off/{year}
--   * 常规赛表 <table id="on-off">，季后赛表 <table id="on-off-post">
--   * 每表恰好 3 行，由 data-stat="split_id" 区分：On Court / Off Court / On-Off
--     （BR 原文 "On − Off" 用 U+2212 减号，入库规范化为 ASCII "On-Off"）
--   * 30 列 = split_id, team_id, mp + Team 组 9 + Opponent 组 9(opp_*) + Difference 组 9(diff_*)
--   * mp 异构：On/Off 行=分钟数(numeric)；On-Off 行=在场时间占比 "65%" → 存 min_pct=65.0
--
-- 宽表模型：每行 = 一个 split。唯一键 (player_id, season, season_type, split)。
-- 注意：这是【球员级】on-off，与废弃的【球队级】team_on_off 完全不同，勿混用。

CREATE TABLE IF NOT EXISTS player_onoff (
    player_id     text    NOT NULL,   -- BR slug（如 antetgi01）
    season        integer NOT NULL,   -- 赛季结束年（2024 = 2023-24）
    season_type   text    NOT NULL,   -- 'Regular' / 'Playoffs'
    split         text    NOT NULL,   -- 'On Court' / 'Off Court' / 'On-Off'
    team_id       text,               -- 球队缩写（如 MIL）

    mp            numeric,            -- 分钟数（仅 On Court / Off Court 行）
    min_pct       numeric,            -- 在场时间占比 %（仅 On-Off 行，如 65.0）

    -- Team 组（球员所在队在该 split 下的表现）
    efg_pct       numeric,
    orb_pct       numeric,
    drb_pct       numeric,
    trb_pct       numeric,
    ast_pct       numeric,
    stl_pct       numeric,
    blk_pct       numeric,
    tov_pct       numeric,
    off_rtg       numeric,

    -- Opponent 组（对手在该 split 下的表现）
    opp_efg_pct   numeric,
    opp_orb_pct   numeric,
    opp_drb_pct   numeric,
    opp_trb_pct   numeric,
    opp_ast_pct   numeric,
    opp_stl_pct   numeric,
    opp_blk_pct   numeric,
    opp_tov_pct   numeric,
    opp_off_rtg   numeric,

    -- Difference 组（Team − Opponent 净差）
    diff_efg_pct  numeric,
    diff_orb_pct  numeric,
    diff_drb_pct  numeric,
    diff_trb_pct  numeric,
    diff_ast_pct  numeric,
    diff_stl_pct  numeric,
    diff_blk_pct  numeric,
    diff_tov_pct  numeric,
    diff_off_rtg  numeric,

    created_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT uq_player_onoff UNIQUE (player_id, season, season_type, split)
);

CREATE INDEX IF NOT EXISTS idx_player_onoff_player  ON player_onoff (player_id);
CREATE INDEX IF NOT EXISTS idx_player_onoff_season  ON player_onoff (season);

-- 404 隔离表：per (slug, year) 复合 PK（某年页面不存在时只隔离该年，不整 slug 隔离）
CREATE TABLE IF NOT EXISTS player_onoff_404 (
    slug        text        NOT NULL,
    year        integer     NOT NULL,
    note        text,
    first_seen  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (slug, year)
);
