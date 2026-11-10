-- 轻量泄漏测试: 先物化 7 个赛季的 RS 逐场(球员,队,季)集合, 再反连 player_per_game
SET max_parallel_workers_per_gather=0;

DROP TABLE IF EXISTS rs_gl_7;
CREATE TEMP TABLE rs_gl_7 AS
SELECT DISTINCT gl.player_name, gl.team, dg.season::int AS season
FROM player_gamelog gl
JOIN dim_games dg ON dg.game_id = gl.game_id_full
WHERE dg.season IN (2004,2005,2006,2008,2009,2019,2020)
  AND gl.season IS NOT NULL;

CREATE INDEX ix_rs_gl_7 ON rs_gl_7 (season, team, player_name);

-- player_per_game 的 RS 行在 RS逐场里找不到同名同队同行 → 疑似季前赛渗进(或名字归一化差异)
SELECT 'ppg_leak_candidates' AS t, COUNT(*)::text AS n FROM player_per_game pp
WHERE pp.season_type='Regular Season' AND pp.season IN (2004,2005,2006,2008,2009,2019,2020)
  AND NOT EXISTS (
    SELECT 1 FROM rs_gl_7 r
    WHERE r.season = pp.season AND r.team = pp.team AND r.player_name = pp.player
  );

-- 对照: 这 7 赛季 player_per_game RS 总行数(比对泄漏占比)
SELECT 'ppg_rs_7seasons' AS t, COUNT(*)::text AS n FROM player_per_game
WHERE season_type='Regular Season' AND season IN (2004,2005,2006,2008,2009,2019,2020);

-- team_stats_per_game 同理(用 playoffs=false), 但 team 维度无法用 gamelog 反验, 仅报结构
SELECT 'tstat_rs_7seasons' AS t, COUNT(*)::text AS n FROM team_stats_per_game
WHERE playoffs = false AND season IN (2004,2005,2006,2008,2009,2019,2020);
