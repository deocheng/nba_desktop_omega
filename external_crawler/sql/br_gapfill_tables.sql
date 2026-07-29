-- ============================================================================
-- br_gapfill_tables.sql — BR 球队页数据补全（br_gapfill）新表 DDL + ALTER
-- 目标库: postgres @127.0.0.1:5433 / dbname=nba / user=postgres / public 模式
-- 命名风格对齐现有表: team_shooting / team_lineups / team_on_off / game_referees
--   （snake_case + 实体描述，不加 br_ 前缀；球队列 team_abbr、赛季 season 整数、
--    百分比列 *_percent 对齐 player_shooting；season_type 对齐 player_shooting）
-- 落库次序（优先级 51243）: ⑤ → ① → ② → ④ → ③
-- ============================================================================

-- ============================================================================
-- ⑤ team_shooting（新建，长表：每 team×season×season_type×vs_type×zone 一行）
-- BR 源页: /teams/{ABBR}/{YEAR}/shooting/ （team_shooting=本队, opponent_shooting=对手）
-- 列覆盖 BR 该页标准完整列集；mp 为真实 BR 页「该 zone 总分钟」列，
--   fg2_pct/fg3_pct 为 INFERRED 补全（每 zone 的 2P%/3P%）。
--   原冗余 INFERRED 的 gp 已从 DDL/解析移除（BR 真实页用 g，gp 恒 NULL）。
-- ============================================================================
CREATE TABLE IF NOT EXISTS team_shooting (
    id              bigserial PRIMARY KEY,
    team_abbr       text    NOT NULL,
    season          integer NOT NULL,                       -- 结束年（2026=2025-26）
    season_type     varchar(20) NOT NULL DEFAULT 'Regular', -- 'Regular' | 'Playoffs'
    vs_type         text    NOT NULL,                        -- 'self' 本队出手 | 'opp' 对手出手
    zone            text    NOT NULL,                        -- 区域/距离桶标签（见下受控词表）
    -- —— 以下为 BR team_shooting 标准列（完整集）——
    mp              integer,                                -- BR 真实页 mp（该 zone 总分钟）
    g               integer,                                -- BR G（场次计数）
    fg              integer,
    fga             integer,
    fg_percent      double precision,                        -- 对齐 player_shooting 的 *_percent
    fg2             integer,                                -- 2P 命中
    fga2            integer,                                -- 2P 出手
    fg2_pct         double precision,                       -- INFERRED: BR 2P%（每 zone）
    fg3             integer,                                -- 3P 命中
    fga3            integer,                                -- 3P 出手
    fg3_pct         double precision,                       -- INFERRED: BR 3P%（每 zone）
    pct_of_fga      double precision,                        -- 该 zone 占全队 FGA 比重（PRD fg_freq）
    avg_shot_dist   double precision,                        -- 该 zone 平均出手距离(ft)
    source          text    DEFAULT 'basketball-reference',
    created_at      timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (team_abbr, season, season_type, vs_type, zone)
);

-- ZONE 受控词表（与 player_shooting 距离桶命名呼应）:
--   区域视图(2P): Restricted Area, In The Paint (Non-RA), Mid-Range
--   三分视图(3P): Left Corner 3, Right Corner 3, Above the Break 3
--   距离桶(2P):   0-3 Feet, 3-10 Feet, 10-16 Feet, 16-3P Feet
--   距离桶(3P):   3-Point Range
-- （解析层仅保留上述已知 zone/距离标签行，跳过 BR 的 "Team" 汇总行，避免污染）

CREATE INDEX IF NOT EXISTS idx_team_shooting_team_season
    ON team_shooting (team_abbr, season);
CREATE INDEX IF NOT EXISTS idx_team_shooting_season_type
    ON team_shooting (season, season_type);


-- ============================================================================
-- ① team_lineups（新建，长表：每 team×season×season_type×lineup 一行）
-- BR 源页: /teams/{ABBR}/{YEAR}/lineups/ （#lineups，5 人组合）
-- 球员键三件套对齐 player_gamelog: br_player_id(FK dim_players) + player_id(bigint) + player_name
-- ============================================================================
CREATE TABLE IF NOT EXISTS team_lineups (
    id              bigserial PRIMARY KEY,
    team_abbr       text    NOT NULL,
    season          integer NOT NULL,
    season_type     varchar(20) NOT NULL DEFAULT 'Regular',
    lineup_key      text    NOT NULL,                        -- 5 个 br_player_id 排序后 '|' 连接（无序去重）
    -- 5 个位置占位：BR slug(varchar,FK dim_players) + NBA 数字 id(bigint) + 展示名
    br_player_id1   varchar, br_player_id2 varchar, br_player_id3 varchar,
    br_player_id4   varchar, br_player_id5 varchar,
    player_id1      bigint,  player_id2  bigint,  player_id3  bigint,
    player_id4      bigint,  player_id5  bigint,
    player_name1    text,    player_name2 text,    player_name3 text,
    player_name4    text,    player_name5 text,
    gp              integer,
    minutes         integer,                                -- BR MIN（总分钟，整数）
    won             integer,
    lost            integer,
    pts             integer,                                -- 该阵容得分
    opp_pts         integer,                                -- 该阵容失分
    off_rtg         double precision,
    def_rtg         double precision,
    net_rtg         double precision,
    source          text    DEFAULT 'basketball-reference',
    created_at      timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (team_abbr, season, season_type, lineup_key),
    FOREIGN KEY (br_player_id1) REFERENCES dim_players(player_id),
    FOREIGN KEY (br_player_id2) REFERENCES dim_players(player_id),
    FOREIGN KEY (br_player_id3) REFERENCES dim_players(player_id),
    FOREIGN KEY (br_player_id4) REFERENCES dim_players(player_id),
    FOREIGN KEY (br_player_id5) REFERENCES dim_players(player_id)
);

CREATE INDEX IF NOT EXISTS idx_team_lineups_team_season
    ON team_lineups (team_abbr, season);


-- ============================================================================
-- ② team_on_off（新建，长表：每 team×season×season_type×player 一行，ON/OFF/DIFF 同 row）
-- BR 源页: /teams/{ABBR}/{YEAR}/on-off/ （#on_off）
-- 真实结构 =「On Court / Off Court / Difference」三组，每组 11 列：
--   * On Court 组（无前缀）:    mp, off_rtg, pace, efg_pct, tov_pct, orb_pct,
--                              drb_pct, trb_pct, stl_pct, blk_pct, ast_pct
--   * Off Court 组（opp_ 前缀）: opp_mp, opp_off_rtg, opp_pace, opp_efg_pct,
--                              opp_tov_pct, opp_orb_pct, opp_drb_pct, opp_trb_pct,
--                              opp_stl_pct, opp_blk_pct, opp_ast_pct
--   * Difference 组（diff_ 前缀）: diff_mp, diff_off_rtg, diff_pace, diff_efg_pct,
--                              diff_tov_pct, diff_orb_pct, diff_drb_pct, diff_trb_pct,
--                              diff_stl_pct, diff_blk_pct, diff_ast_pct
-- 无 gp、无独立 def_rtg、无独立 net_rtg（净值由 Diff 组体现）。
-- DDL 列按组前缀落库为 on_*/off_*/diff_*，与真实 data-stat 严格对应（无幻影列）。
-- ============================================================================
CREATE TABLE IF NOT EXISTS team_on_off (
    id              bigserial PRIMARY KEY,
    team_abbr       text    NOT NULL,
    season          integer NOT NULL,
    season_type     varchar(20) NOT NULL DEFAULT 'Regular',
    br_player_id    varchar,                                -- FK dim_players(player_id)，缺则 NULL
    player_id       bigint,                                 -- NBA 数字 id，缺桥 NULL
    player_name     text    NOT NULL,                       -- BR 页展示名（唯一键兜底）
    -- —— On Court 组（BR data-stat 无前缀）——
    on_mp           integer,                                -- ON 总分钟
    on_off_rtg      double precision,                       -- ON 进攻效率
    on_pace         double precision,                       -- ON 节奏
    on_efg_pct      double precision,                       -- ON eFG%
    on_tov_pct      double precision,                       -- ON 失误率
    on_orb_pct      double precision,                       -- ON 进攻篮板率
    on_drb_pct      double precision,                       -- ON 防守篮板率
    on_trb_pct      double precision,                       -- ON 总篮板率
    on_stl_pct      double precision,                       -- ON 抢断率
    on_blk_pct      double precision,                       -- ON 盖帽率
    on_ast_pct      double precision,                       -- ON 助攻率
    -- —— Off Court 组（BR data-stat 带 opp_ 前缀）——
    off_mp          integer,                                -- OFF 总分钟
    off_off_rtg     double precision,                       -- OFF 进攻效率
    off_pace        double precision,                       -- OFF 节奏
    off_efg_pct     double precision,                       -- OFF eFG%
    off_tov_pct     double precision,                       -- OFF 失误率
    off_orb_pct     double precision,                       -- OFF 进攻篮板率
    off_drb_pct     double precision,                       -- OFF 防守篮板率
    off_trb_pct     double precision,                       -- OFF 总篮板率
    off_stl_pct     double precision,                       -- OFF 抢断率
    off_blk_pct     double precision,                       -- OFF 盖帽率
    off_ast_pct     double precision,                       -- OFF 助攻率
    -- —— Difference 组（BR data-stat 带 diff_ 前缀，净值）——
    diff_mp         integer,                                -- ON-OFF 分钟差
    diff_off_rtg    double precision,                       -- ON-OFF 进攻效率差
    diff_pace       double precision,                       -- ON-OFF 节奏差
    diff_efg_pct    double precision,                       -- ON-OFF eFG% 差
    diff_tov_pct    double precision,                       -- ON-OFF 失误率差
    diff_orb_pct    double precision,                       -- ON-OFF 进攻篮板率差
    diff_drb_pct    double precision,                       -- ON-OFF 防守篮板率差
    diff_trb_pct    double precision,                       -- ON-OFF 总篮板率差
    diff_stl_pct    double precision,                       -- ON-OFF 抢断率差
    diff_blk_pct    double precision,                       -- ON-OFF 盖帽率差
    diff_ast_pct    double precision,                       -- ON-OFF 助攻率差
    source          text    DEFAULT 'basketball-reference',
    created_at      timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (team_abbr, season, season_type, player_name),
    FOREIGN KEY (br_player_id) REFERENCES dim_players(player_id)
);

CREATE INDEX IF NOT EXISTS idx_team_on_off_team_season
    ON team_on_off (team_abbr, season);


-- ============================================================================
-- ③ game_referees（新建，长表：每 game×referee 一行）
-- BR 源页: /teams/{ABBR}/{YEAR}/referees/ （#referees，每 game 一行 + 3 名裁判）
-- game_id FK → dim_games.game_id（字母数字全 id）。不建独立 referees 引用表。
-- 同场比赛从主客两队页各抓一次，按 (game_id, referee_name) 去重。
-- ============================================================================
CREATE TABLE IF NOT EXISTS game_referees (
    id              bigserial PRIMARY KEY,
    game_id         text    NOT NULL,                       -- FK dim_games.game_id
    team_abbr       text,                                   -- 抓取来源球队页（冗余，便于核对）
    season          integer,                                -- 冗余，便于分区查询
    referee_name    text    NOT NULL,
    ref_order       smallint,                               -- 1..3（BR 列出顺序）
    source          text    DEFAULT 'basketball-reference',
    created_at      timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (game_id, referee_name),
    FOREIGN KEY (game_id) REFERENCES dim_games(game_id)
);

CREATE INDEX IF NOT EXISTS idx_game_referees_game_id
    ON game_referees (game_id);
CREATE INDEX IF NOT EXISTS idx_game_referees_season
    ON game_referees (season);


-- ============================================================================
-- ④ team_depth_chart（复用现有表，仅增量 upsert 2025-26）—— 需 ALTER
-- 现有 DDL: id, season(int,NN), team_abbr(text,NN), player_name(text,NN),
--           start_count(int), last_start(date), depth_rank(int), created_at
-- 缺 position 与 player_id，按 PRD「不够则 ALTER」补全；并替换唯一键为
--   (season, team_abbr, position, depth_rank)（历史行 position=NULL 自动互异，安全）。
-- ============================================================================
ALTER TABLE team_depth_chart ADD COLUMN IF NOT EXISTS position  text;
ALTER TABLE team_depth_chart ADD COLUMN IF NOT EXISTS player_id bigint;  -- NBA 数字 id，FK 不强制

-- 2025-26 upsert 使用的新唯一键（替换旧 (season, team_abbr, player_name)）。
ALTER TABLE team_depth_chart
    DROP CONSTRAINT IF EXISTS team_depth_chart_season_team_abbr_player_name_key;
ALTER TABLE team_depth_chart
    ADD CONSTRAINT team_depth_chart_season_team_abbr_position_depth_rank_key
    UNIQUE (season, team_abbr, position, depth_rank);
