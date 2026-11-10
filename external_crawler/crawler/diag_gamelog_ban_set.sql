-- 诊断：确认"季前赛"待 ban 行集
-- 季前赛 = NBA-API 编码 type-1：game_id_full 为 8 位数字且首位=1，且不在 dim_games（dim_games 不含季前赛）
SET max_parallel_workers_per_gather=0;

-- 1) 当前表是否已存在 banned 列
SELECT 'banned_col_exists' AS chk,
       COUNT(*) AS n
FROM information_schema.columns
WHERE table_schema='public' AND table_name='player_gamelog' AND column_name='banned';

-- 2) 季前赛 ban 行集计数（应=7222）
SELECT 'preseason_ban_set' AS chk, COUNT(*) AS n
FROM player_gamelog
WHERE game_id_full ~ '^1[0-9]{7}$'
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL);

-- 3) 这些行 season 现状（应全非 NULL，上轮已填）
SELECT 'preseason_ban_set_season_null' AS chk, COUNT(*) AS n
FROM player_gamelog
WHERE game_id_full ~ '^1[0-9]{7}$'
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
  AND season IS NULL;

-- 4) 与 dim_games 是否真不重叠（应=0）
SELECT 'preseason_overlap_dim_games' AS chk, COUNT(*) AS n
FROM player_gamelog gl
WHERE game_id_full ~ '^1[0-9]{7}$'
  AND EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = gl.game_id_full);

-- 5) 抽样看一眼
SELECT id, game_id_full, player_name, team, season
FROM player_gamelog
WHERE game_id_full ~ '^1[0-9]{7}$'
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
LIMIT 5;
