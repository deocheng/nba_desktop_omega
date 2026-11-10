-- 验证 6,393 伪日期孤儿能否经 dim_games.nba_api_id 权威关联
SET max_parallel_workers_per_gather=0;

-- dim_games.nba_api_id 样本长度/格式(nba_api_id 是 bigint, 转 text 看形态)
SELECT 'dg_nba_api_id_samples' AS chk, nba_api_id::text
FROM dim_games WHERE nba_api_id IS NOT NULL LIMIT 5;

-- 6,393 中能经 nba_api_id 关联(dim_games.nba_api_id = '00'||game_id_full 或 = game_id_full) 的数量
SELECT 'orphan_joinable_via_nba_api_id' AS chk,
       COUNT(*) AS joinable
FROM player_gamelog gl
WHERE gl.season IS NULL AND gl.game_id_full ~ '^[0-9]{8}'
  AND SUBSTRING(gl.game_id_full FROM 1 FOR 8) !~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
  AND EXISTS (
    SELECT 1 FROM dim_games dg
    WHERE dg.nba_api_id IS NOT NULL
      AND (dg.nba_api_id::text = '00'||gl.game_id_full OR dg.nba_api_id::text = gl.game_id_full)
  );

-- 抽样: 看关联后的 season 值是否合理
SELECT gl.game_id_full, dg.nba_api_id::text AS dg_nba_api_id, dg.game_id AS dg_game_id, dg.season
FROM player_gamelog gl
JOIN dim_games dg ON (dg.nba_api_id::text = '00'||gl.game_id_full OR dg.nba_api_id::text = gl.game_id_full)
WHERE gl.season IS NULL AND gl.game_id_full ~ '^[0-9]{8}'
  AND SUBSTRING(gl.game_id_full FROM 1 FOR 8) !~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
LIMIT 10;
