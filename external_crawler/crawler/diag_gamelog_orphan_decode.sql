-- 解码 6,393 伪日期孤儿的 NBA-API ID -> 赛季年, 核查合理性
SET max_parallel_workers_per_gather=0;

-- 首位(类型)分布 + 解码赛季分布
WITH orph AS (
  SELECT game_id_full,
         SUBSTRING(game_id_full FROM 1 FOR 1) AS d1,
         CAST(SUBSTRING(game_id_full FROM 2 FOR 2) AS int) AS yy
  FROM player_gamelog
  WHERE season IS NULL AND game_id_full IS NOT NULL AND game_id_full ~ '^[0-9]{8}'
    AND SUBSTRING(game_id_full FROM 1 FOR 8) !~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
    AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
),
dec AS (
  SELECT game_id_full, d1,
         CASE WHEN yy < 50 THEN 2000 + yy + 1 ELSE 1900 + yy + 1 END AS decoded_season
  FROM orph
)
SELECT 'first_digit_dist' AS chk, d1 AS val, COUNT(*) AS n
FROM orph GROUP BY d1 ORDER BY d1;

-- 解码赛季分布 + 异常计数
WITH orph AS (
  SELECT game_id_full, CAST(SUBSTRING(game_id_full FROM 2 FOR 2) AS int) AS yy
  FROM player_gamelog
  WHERE season IS NULL AND game_id_full IS NOT NULL AND game_id_full ~ '^[0-9]{8}'
    AND SUBSTRING(game_id_full FROM 1 FOR 8) !~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
    AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
),
dec AS (
  SELECT CASE WHEN yy < 50 THEN 2000 + yy + 1 ELSE 1900 + yy + 1 END AS decoded_season
  FROM orph
)
SELECT decoded_season, COUNT(*) AS n
FROM dec GROUP BY decoded_season ORDER BY decoded_season;

-- 异常值(超出 [1997,2026]) 计数
WITH orph AS (
  SELECT CAST(SUBSTRING(game_id_full FROM 2 FOR 2) AS int) AS yy
  FROM player_gamelog
  WHERE season IS NULL AND game_id_full IS NOT NULL AND game_id_full ~ '^[0-9]{8}'
    AND SUBSTRING(game_id_full FROM 1 FOR 8) !~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
    AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
)
SELECT 'out_of_range' AS chk,
       COUNT(*) FILTER (WHERE (CASE WHEN yy<50 THEN 2000+yy+1 ELSE 1900+yy+1 END) NOT BETWEEN 1997 AND 2026) AS bad,
       COUNT(*) AS total
FROM orph;
