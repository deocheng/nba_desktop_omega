-- 看清 6,393 伪日期孤儿的 game_id_full 真实格式
SET max_parallel_workers_per_gather=0;

-- 伪日期孤儿完整 game_id_full 样本
SELECT game_id_full
FROM player_gamelog
WHERE season IS NULL AND game_id_full IS NOT NULL AND game_id_full ~ '^[0-9]{8}'
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
  AND SUBSTRING(game_id_full FROM 1 FOR 8) !~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
LIMIT 25;

-- 伪日期孤儿 game_id_full 长度分布(看是否带日期尾段)
SELECT length(game_id_full) AS len, COUNT(*) AS n
FROM player_gamelog
WHERE season IS NULL AND game_id_full IS NOT NULL AND game_id_full ~ '^[0-9]{8}'
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
  AND SUBSTRING(game_id_full FROM 1 FOR 8) !~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
GROUP BY len ORDER BY len;

-- 伪日期孤儿 player_name 采样(确认是真实球员行, 非垃圾)
SELECT player_name, team, COUNT(*) AS n
FROM player_gamelog
WHERE season IS NULL AND game_id_full IS NOT NULL AND game_id_full ~ '^[0-9]{8}'
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
  AND SUBSTRING(game_id_full FROM 1 FOR 8) !~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
GROUP BY player_name, team ORDER BY n DESC LIMIT 15;
