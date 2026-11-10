-- 用 dim_games 真实数据反推 nba_api_id 的 season 编码规则
SET max_parallel_workers_per_gather=0;

-- 抽样：BR game_id(含日期) / nba_api_id / season
SELECT game_id, nba_api_id::text AS nba_id, season
FROM dim_games
WHERE nba_api_id IS NOT NULL
ORDER BY game_id
LIMIT 12;

-- 全量验证：把 nba_api_id 第2-3位当 YY，season=2000+YY+1(YY<50) / 1900+YY+1(YY>=50)
-- 与 dim_games.season 比对吻合度（这是真实数据上的规则验证）
WITH dec AS (
  SELECT season AS real_season,
         CAST(SUBSTRING(nba_api_id::text FROM 2 FOR 2) AS int) AS yy
  FROM dim_games
  WHERE nba_api_id IS NOT NULL
)
SELECT COUNT(*) FILTER (WHERE real_season = CASE WHEN yy < 50 THEN 2000+yy+1 ELSE 1900+yy+1 END) AS match_rule,
       COUNT(*) AS total
FROM dec;
