-- 查清现代 dim_games 中规则不匹配的行：按 type 首位分类，确认是否影响孤儿家族(type 1/5)
SET max_parallel_workers_per_gather=0;

-- 现代不匹配行的 type 首位分布
WITH dec AS (
  SELECT season AS real_season, LEFT(nba_api_id::text,1) AS typ, CAST(SUBSTRING(nba_api_id::text FROM 2 FOR 2) AS int) AS yy
  FROM dim_games WHERE nba_api_id IS NOT NULL AND season >= 2000
)
SELECT typ, COUNT(*) FILTER (WHERE real_season = 2000+yy+1) AS match_n, COUNT(*) FILTER (WHERE real_season <> 2000+yy+1) AS mismatch_n
FROM dec GROUP BY typ ORDER BY typ;

-- 不匹配样本（看真实原因）
WITH dec AS (
  SELECT game_id, nba_api_id::text AS nba_id, season AS real_season, CAST(SUBSTRING(nba_api_id::text FROM 2 FOR 2) AS int) AS yy
  FROM dim_games WHERE nba_api_id IS NOT NULL AND season >= 2000
)
SELECT game_id, nba_id, real_season, 2000+yy+1 AS decoded FROM dec
WHERE real_season <> 2000+yy+1 LIMIT 12;

-- 孤儿解码值复核：是否全部落在 dim_games 真实存在的赛季集合内
SELECT 'orphan_seasons_all_valid' AS k,
       COUNT(*) FILTER (WHERE gl.season IN (SELECT DISTINCT season FROM dim_games)) AS valid_n,
       COUNT(*) AS total_n
FROM player_gamelog gl
WHERE gl.season IS NOT NULL
  AND gl.game_id_full IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = gl.game_id_full AND dg.season IS NOT NULL);
