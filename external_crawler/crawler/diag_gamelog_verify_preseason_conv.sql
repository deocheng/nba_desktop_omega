-- 提取 dim_games 中 type 1(季前赛)/type 5(Play-In) 的真实 YY->season 映射
SET max_parallel_workers_per_gather=0;

-- type 1 各 YY 对应的 dim_games.season（真实约定）
SELECT CAST(SUBSTRING(nba_api_id::text FROM 2 FOR 2) AS int) AS yy,
       MIN(season) AS min_s, MAX(season) AS max_s, COUNT(*) AS n
FROM dim_games
WHERE nba_api_id IS NOT NULL AND LEFT(nba_api_id::text,1)='1'
GROUP BY yy ORDER BY yy;

-- type 5 各 YY 对应的 dim_games.season
SELECT CAST(SUBSTRING(nba_api_id::text FROM 2 FOR 2) AS int) AS yy,
       MIN(season) AS min_s, MAX(season) AS max_s, COUNT(*) AS n
FROM dim_games
WHERE nba_api_id IS NOT NULL AND LEFT(nba_api_id::text,1)='5'
GROUP BY yy ORDER BY yy;

-- 校验：type 1 是否严格 = 2000+yy (起始年)，type 5 是否严格 = 2000+yy+1 (结束年)
WITH t1 AS (
  SELECT CAST(SUBSTRING(nba_api_id::text FROM 2 FOR 2) AS int) AS yy, season
  FROM dim_games WHERE nba_api_id IS NOT NULL AND LEFT(nba_api_id::text,1)='1'
), t5 AS (
  SELECT CAST(SUBSTRING(nba_api_id::text FROM 2 FOR 2) AS int) AS yy, season
  FROM dim_games WHERE nba_api_id IS NOT NULL AND LEFT(nba_api_id::text,1)='5'
)
SELECT 't1_startyear_match' AS k, COUNT(*) FILTER (WHERE season = 2000+yy) AS m, COUNT(*) AS tot FROM t1
UNION ALL
SELECT 't5_endyear_match', COUNT(*) FILTER (WHERE season = 2000+yy+1), COUNT(*) FROM t5;
