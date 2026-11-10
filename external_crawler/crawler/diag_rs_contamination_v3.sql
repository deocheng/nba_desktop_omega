-- 轻量泄漏测试 v3: 不连 dim_games, 用 banned 标志界定 RS 逐场
SET max_parallel_workers_per_gather=0;
SET work_mem='64MB';

DROP TABLE IF EXISTS rs_gl_7;
CREATE TEMP TABLE rs_gl_7 AS
SELECT DISTINCT player_name, team, season::int AS season
FROM player_gamelog
WHERE season IN (2004,2005,2006,2008,2009,2019,2020)
  AND NOT banned AND season IS NOT NULL;

CREATE INDEX ix_rs_gl_7 ON rs_gl_7 (season, team, player_name);

-- player_per_game RS 行在 RS逐场里找不到同名同队同行 → 疑似季前赛渗进(或名字归一化差异)
SELECT 'ppg_leak_candidates' AS t, COUNT(*)::text AS n FROM player_per_game pp
WHERE pp.season_type='Regular Season' AND pp.season IN (2004,2005,2006,2008,2009,2019,2020)
  AND NOT EXISTS (
    SELECT 1 FROM rs_gl_7 r
    WHERE r.season = pp.season AND r.team = pp.team AND r.player_name = pp.player
  );

SELECT 'ppg_rs_7seasons' AS t, COUNT(*)::text AS n FROM player_per_game
WHERE season_type='Regular Season' AND season IN (2004,2005,2006,2008,2009,2019,2020);
