-- 验证 8,071 孤儿解码 season 是否真实：找库内权威来源交叉核对
SET max_parallel_workers_per_gather=0;

-- A) player_gamelog 是否含 nba_api_id 形态列（如 gameid）
SELECT 'pg_columns' AS k, column_name||' '||data_type
FROM information_schema.columns
WHERE table_schema='public' AND table_name='player_gamelog'
  AND column_name ILIKE '%game%'
ORDER BY ordinal_position;

-- B) dim_games.nba_api_id 真实格式（位数/前缀）
SELECT 'dg_nba_api_id_sample' AS k, nba_api_id::text
FROM dim_games WHERE nba_api_id IS NOT NULL LIMIT 5;

-- C) 孤儿行的 gameid 列是否存原生 nba_api_id（可连 dim_games.nba_api_id）
SELECT 'orphan_gameid_sample' AS k, game_id_full||' | '||COALESCE(gameid::text,'<null>')
FROM player_gamelog
WHERE season IS NOT NULL
  AND game_id_full IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
LIMIT 8;

-- D) 孤儿 gameid(若存在) 直连 dim_games.nba_api_id 能拿到真实 season 的行数
SELECT 'orphan_gameid_matches_dim_games' AS k, COUNT(*)
FROM player_gamelog gl
WHERE gl.season IS NOT NULL
  AND gl.game_id_full IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = gl.game_id_full AND dg.season IS NOT NULL)
  AND gl.gameid IS NOT NULL
  AND EXISTS (SELECT 1 FROM dim_games dg WHERE dg.nba_api_id = gl.gameid AND dg.season IS NOT NULL);

-- E) 孤儿 game_id_full 加 '00' 前缀后能否连 dim_games.nba_api_id
SELECT 'orphan_prefix00_matches' AS k, COUNT(*)
FROM player_gamelog gl
WHERE gl.season IS NOT NULL
  AND gl.game_id_full IS NOT NULL
  AND gl.game_id_full ~ '^[0-9]{8}$'
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = gl.game_id_full AND dg.season IS NOT NULL)
  AND EXISTS (SELECT 1 FROM dim_games dg WHERE dg.nba_api_id = ('00'||gl.game_id_full)::bigint AND dg.season IS NOT NULL);
