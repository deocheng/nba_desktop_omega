-- 查清现代(2018+) dim_games 的 nba_api_id 真实编码
SET max_parallel_workers_per_gather=0;

-- 抽样：现代赛季的 game_id(含日期) / nba_api_id / season
SELECT game_id, nba_api_id::text AS nba_id, season
FROM dim_games
WHERE season >= 2019
ORDER BY game_id
LIMIT 12;

-- 现代赛季 nba_api_id 前3位分布（看 type+YY 形态）
SELECT LEFT(nba_api_id::text, 3) AS prefix3, COUNT(*) FROM dim_games
WHERE season >= 2019 AND nba_api_id IS NOT NULL
GROUP BY prefix3 ORDER BY prefix3 LIMIT 15;

-- 用规则 2000+yy+1(yy<50) 验证现代赛季吻合度（只看 season>=2000）
WITH dec AS (
  SELECT season AS real_season, CAST(SUBSTRING(nba_api_id::text FROM 2 FOR 2) AS int) AS yy
  FROM dim_games WHERE nba_api_id IS NOT NULL AND season >= 2000
)
SELECT COUNT(*) FILTER (WHERE real_season = 2000+yy+1) AS match_modern, COUNT(*) AS total
FROM dec;
