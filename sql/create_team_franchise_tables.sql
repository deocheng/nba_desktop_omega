-- =====================================================================
-- 球队 franchise 级页面表（与用户 17 个 BR 球队页一一对应）
-- 来源：https://www.basketball-reference.com/teams/{slug}/{page}.html
--       （无赛季维度，整队历史累计页）
-- 设计原则：
--   ① 12 个「统计表页」→ 1 张长表 team_franchise_stats
--      （table_id 标识来源页；table_seq 标识同页多表；row_label+data_stat
--       为 (行表头, 列表头) 键，val 为单元格值 —— 与 team_page_raw 同形态，
--       仅去掉 season/season_type）
--   ② 5 个「列表页」(players/numbers/head2head/hof/all_star)
--      → 各一张通用网格捕获表（table_seq,row_idx,col_idx,col_header,val），
--        零结构假设、最大化抽取（铁律③），每个单元格都可离线回放。
--   ③ 所有表注入 franchise_id（落实「数据四性·统一连贯」：NJN/BRK 等
--      历史缩写归属同一 franchise）。
--   ④ 回滚：DROP TABLE ... CASCADE（见同目录 rollback 脚本）。
-- =====================================================================

-- ── 1) 12 个统计表页 → 长表 ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS team_franchise_stats (
    team_abbr    text        NOT NULL,
    franchise_id integer,
    table_id     text        NOT NULL,  -- 来源页名：stats_basic_totals / stats_per_game_totals /
                                       -- opp_stats_basic_totals / opp_stats_per_game_totals /
                                       -- stats_basic_ranks / stats_per_game_ranks /
                                       -- opp_stats_basic_ranks / opp_stats_per_game_ranks /
                                       -- stats_basic_yr_yr / stats_per_game_yr_yr /
                                       -- opp_stats_basic_yr_yr / opp_stats_per_game_yr_yr
    table_seq    smallint    NOT NULL DEFAULT 0,
    row_label    text        NOT NULL DEFAULT '',  -- 行表头（如球员名 / 赛季 / 队名）
    data_stat    text        NOT NULL,             -- 列表头（BR data-stat 属性）
    val          text,
    source       text        DEFAULT 'br_crawler',
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (team_abbr, table_id, table_seq, row_label, data_stat)
);
CREATE INDEX IF NOT EXISTS idx_tfs_table_id ON team_franchise_stats(table_id);
CREATE INDEX IF NOT EXISTS idx_tfs_team     ON team_franchise_stats(team_abbr);
CREATE INDEX IF NOT EXISTS idx_tfs_franchise ON team_franchise_stats(franchise_id);

-- ── 2) 5 个列表页 → 各一张通用网格捕获表 ─────────────────────────────
-- 通用结构：team_abbr / franchise_id / table_seq(同页多表) /
--          row_idx / col_idx / col_header(该列表头文本) / val(单元格文本)
CREATE TABLE IF NOT EXISTS team_franchise_players (
    team_abbr    text        NOT NULL,
    franchise_id integer,
    table_seq    smallint    NOT NULL DEFAULT 0,
    row_idx      integer     NOT NULL,
    col_idx      integer     NOT NULL,
    col_header   text,
    val          text,
    source       text        DEFAULT 'br_crawler',
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (team_abbr, table_seq, row_idx, col_idx)
);
CREATE INDEX IF NOT EXISTS idx_tfp_team ON team_franchise_players(team_abbr);

CREATE TABLE IF NOT EXISTS team_franchise_numbers (
    team_abbr    text        NOT NULL,
    franchise_id integer,
    table_seq    smallint    NOT NULL DEFAULT 0,
    row_idx      integer     NOT NULL,
    col_idx      integer     NOT NULL,
    col_header   text,
    val          text,
    source       text        DEFAULT 'br_crawler',
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (team_abbr, table_seq, row_idx, col_idx)
);
CREATE INDEX IF NOT EXISTS idx_tfn_team ON team_franchise_numbers(team_abbr);

CREATE TABLE IF NOT EXISTS team_franchise_head2head (
    team_abbr    text        NOT NULL,
    franchise_id integer,
    table_seq    smallint    NOT NULL DEFAULT 0,
    row_idx      integer     NOT NULL,
    col_idx      integer     NOT NULL,
    col_header   text,
    val          text,
    source       text        DEFAULT 'br_crawler',
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (team_abbr, table_seq, row_idx, col_idx)
);
CREATE INDEX IF NOT EXISTS idx_tfh_team ON team_franchise_head2head(team_abbr);

CREATE TABLE IF NOT EXISTS team_franchise_hof (
    team_abbr    text        NOT NULL,
    franchise_id integer,
    table_seq    smallint    NOT NULL DEFAULT 0,
    row_idx      integer     NOT NULL,
    col_idx      integer     NOT NULL,
    col_header   text,
    val          text,
    source       text        DEFAULT 'br_crawler',
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (team_abbr, table_seq, row_idx, col_idx)
);
CREATE INDEX IF NOT EXISTS idx_tfhof_team ON team_franchise_hof(team_abbr);

CREATE TABLE IF NOT EXISTS team_franchise_all_star (
    team_abbr    text        NOT NULL,
    franchise_id integer,
    table_seq    smallint    NOT NULL DEFAULT 0,
    row_idx      integer     NOT NULL,
    col_idx      integer     NOT NULL,
    col_header   text,
    val          text,
    source       text        DEFAULT 'br_crawler',
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (team_abbr, table_seq, row_idx, col_idx)
);
CREATE INDEX IF NOT EXISTS idx_tfas_team ON team_franchise_all_star(team_abbr);

-- ── 落盘原始 HTML 的归档目录（铁律①：先存原始页，再离线解析）──────────
-- raw_archive/br_teams_franchise/{slug}/{page}.html
-- （由爬虫用 tempfile + os.replace 原子写，仅建目录占位说明，无需 DB 对象）
