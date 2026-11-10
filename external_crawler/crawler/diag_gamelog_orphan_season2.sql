-- 诊断 v2
SET max_parallel_workers_per_gather=0;

-- ① 用已填行(season NOT NULL, 来自 dim_games 权威)复核 end-year 口径(month>=10 -> year+1) 对 dim_games.season 的吻合度
WITH m AS (
  SELECT dg.season AS dg_season,
         CAST(SUBSTRING(gl.game_id_full FROM 1 FOR 8) AS date) AS d
  FROM player_gamelog gl
  JOIN dim_games dg ON dg.game_id = gl.game_id_full
  WHERE gl.season IS NOT NULL AND gl.game_id_full ~ '^[0-9]{8}'
)
SELECT 'conv_match_ge10_vs_dim_games' AS chk,
       COUNT(*) FILTER (WHERE dg_season = CASE WHEN EXTRACT(MONTH FROM d)>=10 THEN EXTRACT(YEAR FROM d)::int+1 ELSE EXTRACT(YEAR FROM d)::int END) AS matched,
       COUNT(*) AS total
FROM m;

-- ② 孤儿中 前缀为合法日期 YYYYMMDD vs 伪日期(数字但越界) 的分布
WITH orph AS (
  SELECT game_id_full,
         SUBSTRING(game_id_full FROM 1 FOR 8) AS p8
  FROM player_gamelog
  WHERE season IS NULL AND game_id_full IS NOT NULL AND game_id_full ~ '^[0-9]{8}'
    AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
)
SELECT 'orphan_date_split' AS chk,
       COUNT(*) FILTER (WHERE p8 ~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$') AS valid_date,
       COUNT(*) FILTER (WHERE p8 !~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$') AS fake_date,
       COUNT(*) AS total
FROM orph;

-- ②b 伪日期孤儿样本(看其真实格式)
SELECT game_id_full
FROM player_gamelog
WHERE season IS NULL AND game_id_full IS NOT NULL AND game_id_full ~ '^[0-9]{8}'
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
  AND SUBSTRING(game_id_full FROM 1 FOR 8) !~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
LIMIT 15;
