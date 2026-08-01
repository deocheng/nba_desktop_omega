-- docs/ddl_player_lineups.sql
-- ============================================================================
-- player_lineups —— 球员级 lineup 表（per player × season × season_type × lineup_size × lineup_key）
-- player_lineups_404 —— 球员 lineup 页 404 隔离表（per (slug, year) 复合 PK）
--
-- 数据源: basketball-reference.com /players/{letter}/{slug}/lineups/{year}
-- 粒度: 每球员 × 每赛季 × 每赛季类型 × 每阵容人数(2~5) × 每阵容组一行
--       lineup_key = 该阵容 N 个 br_player_id 排序后 '|' 连接（N = lineup_size ∈ {2,3,4,5}）
--
-- slug 宇宙源: player_shooting.player_id（text，BR slug，2861 个可靠 slug）
--   ⚠️ 禁用 player_gamelog.br_player_id（corrupt，含 phantom slug）
--
-- 真实页结构（已用 boguemu01/2001 样本核实，2026-07-24 修订）：
--   * 阵容人数表共 4 张：lineups-5-man / -4-man / -3-man / -2-man（Regular）
--     季后赛对应：lineups-5-man-post / -4-man-post / -3-man-post / -2-man-post（若存在；探测+跳过）
--   * 4 张表均被 Chrome 渲染为可解析 DOM（非 HTML 注释），BeautifulSoup 均可 find。
--   * 列 = ranker / lineup / team_id / mp(格式 M:SS) + 22 个 diff_*（每 100 回合净差值，带 +/-）
--   * 阵容组合在 data-stat="lineup" 单元格内，N 个 /players/{l}/{slug}.html 链接（N=阵容人数）
--   * lineup_key 权威值由单元格 csk 属性给出（':' 分隔、已排序）
--
-- 对齐:
--   * lineup_key 对齐 team_lineups.lineup_key（5 slug 排序 '|' 连接）
--   * FK 目标对齐 team_lineups（dim_players.player_id 5×）
--   * 404 隔离表风格对齐 db/player_shooting_404.sql
--     （shooting 是 slug 单列 PK 因一页全赛季；lineup 是 per-year，故用 (slug, year) 复合 PK）
--
-- 连接串: host=127.0.0.1 port=5433 dbname=nba user=postgres
-- 口令: PGPASSWORD 环境变量（禁止硬编码）
-- 幂等: CREATE TABLE IF NOT EXISTS + ALTER TABLE ADD/DROP COLUMN IF NOT EXISTS(迁移旧 schema) + DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT
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
    lineup_size     SMALLINT     NOT NULL DEFAULT 5,    -- 阵容人数：2/3/4/5
    lineup_key      TEXT         NOT NULL,              -- N 个(=lineup_size) br_player_id 排序后 '|' 连接

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

    -- 阵容元数据（真实页字段）
    ranker          INTEGER,                              -- 行序（Rk）
    team_id         TEXT,                                -- 该阵容所属球队（Tm，如 MIL）
    minutes         INTEGER,                              -- 出场时间（秒数；原始 M:SS 已解析为总秒）

    -- 每 100 回合净差值（diff_*，带 +/- 符号；无原始计数统计）
    diff_fg         DOUBLE PRECISION,
    diff_fga        DOUBLE PRECISION,
    diff_fg_pct    DOUBLE PRECISION,
    diff_fg3        DOUBLE PRECISION,
    diff_fg3a       DOUBLE PRECISION,
    diff_fg3_pct   DOUBLE PRECISION,
    diff_efg_pct   DOUBLE PRECISION,
    diff_ft         DOUBLE PRECISION,
    diff_fta        DOUBLE PRECISION,
    diff_ft_pct    DOUBLE PRECISION,
    diff_pts        DOUBLE PRECISION,
    diff_orb        DOUBLE PRECISION,
    diff_orb_pct   DOUBLE PRECISION,
    diff_drb        DOUBLE PRECISION,
    diff_drb_pct   DOUBLE PRECISION,
    diff_trb        DOUBLE PRECISION,
    diff_trb_pct   DOUBLE PRECISION,
    diff_ast        DOUBLE PRECISION,
    diff_stl        DOUBLE PRECISION,
    diff_blk        DOUBLE PRECISION,
    diff_tov        DOUBLE PRECISION,
    diff_pf         DOUBLE PRECISION,

    -- 溯源
    source          TEXT         DEFAULT 'basketball-reference',
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,

    -- 幂等 upsert 键（含 lineup_size：同球员同赛季可能同时有 5/4/3/2-man 阵容）
    CONSTRAINT player_lineups_uq UNIQUE (player_id, season, season_type, lineup_size, lineup_key)
);

-- ============================================================
-- 迁移块（幂等关键）：若 player_lineups 已存在「旧 9 列提案」schema
--   （gp/minutes/won/lost/pts/opp_pts/off_rtg/def_rtg/net_rtg），
--   补齐新列并删除废弃列。对任意状态均安全：
--     * 表不存在      -> CREATE TABLE 已建好，下面 ADD/DROP 全是 no-op
--     * 表是旧 schema  -> CREATE TABLE 跳过，下面 ADD 新列 / DROP 旧列
--     * 表已是新 schema -> 全部 no-op
--   必须放在 CREATE INDEX(team_id) 之前，确保 team_id 已存在。
-- ============================================================
ALTER TABLE player_lineups
    -- 补齐新 schema 列（缺失才新增，已存在则跳过）
    ADD COLUMN IF NOT EXISTS lineup_size SMALLINT NOT NULL DEFAULT 5,
    ADD COLUMN IF NOT EXISTS ranker   INTEGER,
    ADD COLUMN IF NOT EXISTS team_id  TEXT,
    ADD COLUMN IF NOT EXISTS minutes  INTEGER,
    ADD COLUMN IF NOT EXISTS diff_fg         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_fga        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_fg_pct    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_fg3        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_fg3a       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_fg3_pct   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_efg_pct   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_ft         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_fta        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_ft_pct    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_pts        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_orb        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_orb_pct   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_drb        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_drb_pct   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_trb        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_trb_pct   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_ast        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_stl        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_blk        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_tov        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS diff_pf         DOUBLE PRECISION,
    -- 删除废弃的旧提案列（minutes 保留，仍在新 schema 中）
    DROP COLUMN IF EXISTS gp,
    DROP COLUMN IF EXISTS won,
    DROP COLUMN IF EXISTS lost,
    DROP COLUMN IF EXISTS pts,
    DROP COLUMN IF EXISTS opp_pts,
    DROP COLUMN IF EXISTS off_rtg,
    DROP COLUMN IF EXISTS def_rtg,
    DROP COLUMN IF EXISTS net_rtg;

-- 重建唯一约束（含 lineup_size）：先删旧 4 列约束，再建新 5 列约束。
-- 现有行已随 ADD COLUMN 默认 lineup_size=5，5 列约束可满足。
ALTER TABLE player_lineups DROP CONSTRAINT IF EXISTS player_lineups_uq;
ALTER TABLE player_lineups
    ADD CONSTRAINT player_lineups_uq
        UNIQUE (player_id, season, season_type, lineup_size, lineup_key);

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
CREATE INDEX IF NOT EXISTS idx_player_lineups_team_id
    ON player_lineups (team_id);

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
