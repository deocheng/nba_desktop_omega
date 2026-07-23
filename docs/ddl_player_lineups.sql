-- docs/ddl_player_lineups.sql
-- ============================================================================
-- player_lineups —— 球员级 lineup 表（per player × season × season_type × lineup_key）
-- player_lineups_404 —— 球员 lineup 页 404 隔离表（per (slug, year) 复合 PK）
--
-- 数据源: basketball-reference.com /players/{letter}/{slug}/lineups/{year}
-- 粒度: 每球员 × 每赛季 × 每 5 人阵容组一行（lineup_key = 5 br_player_id 排序 '|' 连接）
--
-- slug 宇宙源: player_shooting.player_id（text，BR slug，2861 个可靠 slug）
--   ⚠️ 禁用 player_gamelog.br_player_id（corrupt，含 phantom slug）
--
-- 对齐:
--   * 字段集对齐 team_lineups（gp/minutes/won/lost/pts/opp_pts/off_rtg/def_rtg/net_rtg）
--   * lineup_key 对齐 team_lineups.lineup_key（5 slug 排序 '|' 连接）
--   * FK 目标对齐 team_lineups（dim_players.player_id 5×）
--   * 404 隔离表风格对齐 db/player_shooting_404.sql
--     （shooting 是 slug 单列 PK 因一页全赛季；lineup 是 per-year，故用 (slug, year) 复合 PK）
--
-- 连接串: host=127.0.0.1 port=5433 dbname=nba user=postgres
-- 口令: PGPASSWORD 环境变量（禁止硬编码）
-- 幂等: CREATE TABLE IF NOT EXISTS + ALTER TABLE DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT
-- ============================================================================

-- ============================================================
-- 1. player_lineups 主表
-- ============================================================
CREATE TABLE IF NOT EXISTS player_lineups (
    id              BIGSERIAL    PRIMARY KEY,
    -- 维度键
    player_id       TEXT         NOT NULL,              -- BR slug（主球员，即 lineup 页所属球员）
    season          INTEGER      NOT NULL,              -- 赛季结束年（2014 = 2013-14 赛季）
    season_type     VARCHAR(20)  NOT NULL DEFAULT 'Regular',
    lineup_key      TEXT         NOT NULL,              -- 5 个 br_player_id 排序后 '|' 连接

    -- 5 人组合（与 team_lineups 结构对齐）
    br_player_id1   VARCHAR,                            -- FK -> dim_players.player_id
    br_player_id2   VARCHAR,
    br_player_id3   VARCHAR,
    br_player_id4   VARCHAR,
    br_player_id5   VARCHAR,
    player_name1    TEXT,
    player_name2    TEXT,
    player_name3    TEXT,
    player_name4    TEXT,
    player_name5    TEXT,

    -- 出场 / 效率（字段集待样例 HTML 最终确认）
    gp              INTEGER,
    minutes         INTEGER,
    won             INTEGER,
    lost            INTEGER,
    pts             INTEGER,
    opp_pts         INTEGER,
    off_rtg         DOUBLE PRECISION,
    def_rtg         DOUBLE PRECISION,
    net_rtg         DOUBLE PRECISION,

    -- 溯源
    source          TEXT         DEFAULT 'basketball-reference',
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,

    -- 幂等 upsert 键
    CONSTRAINT player_lineups_uq UNIQUE (player_id, season, season_type, lineup_key)
);

-- FK 约束（5x br_player_id -> dim_players.player_id），幂等 DROP + ADD
ALTER TABLE player_lineups
    DROP CONSTRAINT IF EXISTS player_lineups_br_pid1_fkey;
ALTER TABLE player_lineups
    ADD  CONSTRAINT player_lineups_br_pid1_fkey
        FOREIGN KEY (br_player_id1) REFERENCES dim_players(player_id);

ALTER TABLE player_lineups
    DROP CONSTRAINT IF EXISTS player_lineups_br_pid2_fkey;
ALTER TABLE player_lineups
    ADD  CONSTRAINT player_lineups_br_pid2_fkey
        FOREIGN KEY (br_player_id2) REFERENCES dim_players(player_id);

ALTER TABLE player_lineups
    DROP CONSTRAINT IF EXISTS player_lineups_br_pid3_fkey;
ALTER TABLE player_lineups
    ADD  CONSTRAINT player_lineups_br_pid3_fkey
        FOREIGN KEY (br_player_id3) REFERENCES dim_players(player_id);

ALTER TABLE player_lineups
    DROP CONSTRAINT IF EXISTS player_lineups_br_pid4_fkey;
ALTER TABLE player_lineups
    ADD  CONSTRAINT player_lineups_br_pid4_fkey
        FOREIGN KEY (br_player_id4) REFERENCES dim_players(player_id);

ALTER TABLE player_lineups
    DROP CONSTRAINT IF EXISTS player_lineups_br_pid5_fkey;
ALTER TABLE player_lineups
    ADD  CONSTRAINT player_lineups_br_pid5_fkey
        FOREIGN KEY (br_player_id5) REFERENCES dim_players(player_id);

-- 索引
CREATE INDEX IF NOT EXISTS idx_player_lineups_pid_season
    ON player_lineups (player_id, season);
CREATE INDEX IF NOT EXISTS idx_player_lineups_season
    ON player_lineups (season);
CREATE INDEX IF NOT EXISTS idx_player_lineups_lineup_key
    ON player_lineups (lineup_key);

-- ============================================================
-- 2. player_lineups_404 隔离表：per (slug, year) 复合主键
--
-- shooting 的 player_shooting_404 是 slug 单列 PK（一页全赛季）；
-- lineup 是 per-year，404 可能只影响某年，故用复合 PK (slug, year)。
-- ============================================================
CREATE TABLE IF NOT EXISTS player_lineups_404 (
    slug        TEXT        NOT NULL,
    year        INTEGER     NOT NULL,
    first_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
    note        TEXT,
    PRIMARY KEY (slug, year)
);
CREATE INDEX IF NOT EXISTS idx_pl404_first_seen
    ON player_lineups_404 (first_seen);
