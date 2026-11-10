-- 验证 RS/PO 聚合表是否被季前赛渗进
SET max_parallel_workers_per_gather=0;

-- 1) player_per_game season_type 分布
SELECT 'ppg_season_types' AS t, string_agg(DISTINCT season_type, '|' ORDER BY season_type) FROM player_per_game;

-- 2) player_per_game 常规赛总行数 & 7个季前赛赛季的 RS 行数
SELECT 'ppg_rs_total' AS t, COUNT(*)::text FROM player_per_game WHERE season_type='Regular Season';
SELECT 'ppg_rs_7seasons' AS t, COUNT(*)::text FROM player_per_game WHERE season_type='Regular Season' AND season IN (2004,2005,2006,2008,2009,2019,2020);

-- 3) 泄漏测试: player_per_game 的 RS 行, 在 RS逐场gamelog(非banned且能连dim_games)里找不到同名同队同行→疑似季前赛渗进
SELECT 'ppg_leak_candidates' AS t, COUNT(*)::text FROM player_per_game pp
WHERE pp.season_type='Regular Season' AND pp.season IN (2004,2005,2006,2008,2009,2019,2020)
  AND NOT EXISTS (
    SELECT 1 FROM player_gamelog gl
    JOIN dim_games dg ON dg.game_id = gl.game_id_full
    WHERE dg.season = pp.season AND gl.player_name = pp.player AND gl.team = pp.team
      AND gl.season IS NOT NULL
  );

-- 4) team_stats_per_game playoffs 分布
SELECT 'tstat_playoffs_dist' AS t, string_agg(DISTINCT playoffs::text, '|' ORDER BY playoffs::text) FROM team_stats_per_game;

-- 5) team_stats_per_game RS(playoffs=false) 7赛季行数
SELECT 'tstat_rs_7seasons' AS t, COUNT(*)::text FROM team_stats_per_game WHERE playoffs = false AND season IN (2004,2005,2006,2008,2009,2019,2020);
SELECT 'tstat_rs_total' AS t, COUNT(*)::text FROM team_stats_per_game WHERE playoffs = false;
