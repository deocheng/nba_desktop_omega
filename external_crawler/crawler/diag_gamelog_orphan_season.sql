-- 诊断: 验证 end-year 口径 + 孤儿日期前缀合法性
SET max_parallel_workers_per_gather=0;

-- ① 用已匹配行(经 dim_games 权威 season)验证 end-year 口径(month>=10 -> year+1) 吻合度
WITH m AS (
  SELECT gl.game_id_full, dg.season AS dg_season,
         CAST(SUBSTRING(gl.game_id_full FROM 1 FOR 8) AS date) AS d
  FROM player_gamelog gl
  JOIN dim_games dg ON dg.game_id = gl.game_id_full
  WHERE gl.season IS NULL AND gl.game_id_full IS NOT NULL AND dg.season IS NOT NULL
)
SELECT 'conv_match_ge10' AS chk,
       COUNT(*) FILTER (WHERE dg_season = CASE WHEN EXTRACT(MONTH FROM d)>=10 THEN EXTRACT(YEAR FROM d)::int+1 ELSE EXTRACT(YEAR FROM d)::int END) AS matched,
       COUNT(*) AS total
FROM m;

-- ② 孤儿(8,071)日期前缀合法性
SELECT 'orphan_prefix' AS chk,
       COUNT(*) FILTER (WHERE game_id_full ~ '^[0-9]{8}') AS valid_prefix,
       COUNT(*) FILTER (WHERE game_id_full !~ '^[0-9]{8}') AS bad_prefix,
       COUNT(*) AS total
FROM player_gamelog
WHERE season IS NULL AND game_id_full IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL);

-- ②b 孤儿派生 season 分布预览(校验合理性, 不应出现离谱年份)
SELECT CASE WHEN EXTRACT(MONTH FROM CAST(SUBSTRING(game_id_full FROM 1 FOR 8) AS date))>=10
            THEN EXTRACT(YEAR FROM CAST(SUBSTRING(game_id_full FROM 1 FOR 8) AS date))::int+1
            ELSE EXTRACT(YEAR FROM CAST(SUBSTRING(game_id_full FROM 1 FOR 8) AS date))::int END AS derived_season,
       COUNT(*) AS n
FROM player_gamelog
WHERE season IS NULL AND game_id_full IS NOT NULL AND game_id_full ~ '^[0-9]{8}'
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
GROUP BY derived_season ORDER BY derived_season;
