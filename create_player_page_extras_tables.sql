-- 球员主页面 "More" 菜单 5 类缺失数据表（均位于 /players/{slug}.html 同一 HTML）
-- 2026-07-29 核实：Game Highs / Playoffs Series / Similarity Scores / All-Star Games / Adjusted Shooting

-- 1) Game Highs（单场各项最大值，按赛季）
CREATE TABLE IF NOT EXISTS player_game_highs (
  player_id      text    NOT NULL,
  season_type    text    NOT NULL,
  season_end     int     NOT NULL,
  season_text    varchar(9),
  age            int,
  team           varchar(4),
  league         varchar(4),
  time_on_court  varchar(12),
  fg int, fga int, fg3 int, fg3a int, fg2 int, fg2a int,
  ft int, fta int, orb int, drb int, trb int, ast int, stl int, blk int, tov int, pf int, pts int,
  game_score     numeric(5,1),
  PRIMARY KEY (player_id, season_type, season_end)
);

-- 2) Playoffs Series（每轮季后赛系列赛）
CREATE TABLE IF NOT EXISTS player_playoffs_series (
  player_id      text    NOT NULL,
  season_end     int     NOT NULL,
  season_text    varchar(9),
  age            int,
  team_abbr      varchar(4),
  lg             varchar(4),
  ps_round       varchar(8),
  opp_abbr       varchar(4),
  series_result  varchar(16),
  games          int,
  mp_per_g       numeric(5,1),
  pts_per_g      numeric(5,1), trb_per_g numeric(5,1), ast_per_g numeric(5,1),
  stl_per_g      numeric(5,1), blk_per_g numeric(5,1),
  fg int, fga int, fg_pct numeric(5,3),
  fg3 int, fg3a int, fg3_pct numeric(5,3),
  fg2 int, fg2a int, fg2_pct numeric(5,3), efg_pct numeric(5,3),
  ft int, fta int, ft_pct numeric(5,3),
  orb int, drb int, trb int, ast int, stl int, blk int, tov int, pf int, pts int,
  awards         text,
  PRIMARY KEY (player_id, season_text, ps_round, opp_abbr)
);

-- 3) Similarity Scores（相似球员，thru=截至本季 / career=生涯）
CREATE TABLE IF NOT EXISTS player_similarity_scores (
  player_id       text    NOT NULL,
  scope           text    NOT NULL,
  comparable_name text    NOT NULL,
  sim_score       numeric(6,2),
  year_scores     jsonb,
  PRIMARY KEY (player_id, scope, comparable_name)
);

-- 4) All-Star Games（全明星正赛逐场 box score）
CREATE TABLE IF NOT EXISTS player_all_star_games (
  player_id    text    NOT NULL,
  season_end   int     NOT NULL,
  season_text  varchar(9),
  age          int,
  team_id      varchar(4),
  lg_id        varchar(4),
  pos          varchar(8),
  g int, gs int,
  mp           varchar(12),
  fg int, fga int, fg_pct numeric(5,3),
  fg3 int, fg3a int, fg3_pct numeric(5,3),
  ft int, fta int, ft_pct numeric(5,3),
  orb int, drb int, trb int, ast int, stl int, blk int, tov int, pf int, pts int,
  PRIMARY KEY (player_id, season_text)
);

-- 5) Adjusted Shooting（按年代调整的命中率，+ 列为相对联盟均值）
CREATE TABLE IF NOT EXISTS player_adjusted_shooting (
  player_id      text    NOT NULL,
  season_type    text    NOT NULL,
  season_end     int     NOT NULL,
  season_text    varchar(9),
  age            int,
  team_abbr      varchar(64),
  lg             varchar(4),
  pos            varchar(8),
  games          int, games_started int, mp int,
  fg_pct numeric(5,3), fg2_pct numeric(5,3), fg3_pct numeric(5,3),
  efg_pct numeric(5,3), ft_pct numeric(5,3), ts_pct numeric(5,3),
  fta_per_fga_pct numeric(5,3), fg3a_per_fga_pct numeric(5,3),
  adj_fg_pct numeric(6,2), adj_fg2_pct numeric(6,2), adj_fg3_pct numeric(6,2),
  adj_efg_pct numeric(6,2), adj_ft_pct numeric(6,2), adj_ts_pct numeric(6,2),
  adj_fta_per_fga_pct numeric(6,2), adj_fg3a_per_fga_pct numeric(6,2),
  fg_pts_added numeric(7,2), ts_pts_added numeric(7,2),
  awards         text,
  PRIMARY KEY (player_id, season_type, season_end)
);

-- 404 隔离表（与主爬虫同构，避免死 slug 重复撞墙）
CREATE TABLE IF NOT EXISTS player_page_extras_404 (
  slug       text PRIMARY KEY,
  note       text,
  first_seen timestamptz DEFAULT now()
);

-- 7) Player Page Overview（主页面顶部 #info 文本块，每球员一行）
-- 与上面 6 张表同源同页（/players/{slug}.html），在一次抓取内顺便解析。
-- 文本为主：含 full_name / instagram / 绰号展示串(nickname_display) / 各项 meta 标签 / 整段原始文本。
-- 注：position/shoots/height/weight/born/high_school/draft/experience 等维度 player_bio 已有结构化列，
--     此处额外保留 BR #info 原样文本（overview_raw）与 player_bio 缺失的 instagram / nickname_display。
CREATE TABLE IF NOT EXISTS player_page_overview (
  player_id        varchar(16) PRIMARY KEY,
  full_name        text,
  instagram        text,
  nickname_display text,
  position_text    text,
  shoots           text,
  height_display   text,
  weight_display   text,
  team_text        text,
  born_text        text,
  relatives_text   text,
  high_school      text,
  recruiting_rank  text,
  draft_text       text,
  nba_debut        text,
  experience_text  text,
  overview_raw     text,
  source_url       text,
  scraped_at       timestamptz DEFAULT now()
);
