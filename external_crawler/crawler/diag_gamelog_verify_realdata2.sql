-- 修正：用 gameid(8位) 直连 dim_games.nba_api_id(8位) 查真实 season
SET max_parallel_workers_per_gather=0;

-- 1) 孤儿行中，gameid 能连上 dim_games.nba_api_id 并拿到 season 的行数
SELECT 'orphan_gameid_matches_dg_nbaid' AS k, COUNT(*) FROM player_gamelog gl
WHERE gl.season IS NOT NULL
  AND gl.game_id_full IS NOT NULL
  AND gl.gameid IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = gl.game_id_full AND dg.season IS NOT NULL)
  AND EXISTS (SELECT 1 FROM dim_games dg WHERE dg.nba_api_id::text = gl.gameid AND dg.season IS NOT NULL);

-- 2) 其中：我解码的 season 与 dim_games 真实 season 完全一致的有多少（验证解码正确性）
SELECT 'decode_matches_real' AS k, COUNT(*) FROM player_gamelog gl
WHERE gl.season IS NOT NULL
  AND gl.gameid IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = gl.game_id_full AND dg.season IS NOT NULL)
  AND EXISTS (SELECT 1 FROM dim_games dg WHERE dg.nba_api_id::text = gl.gameid AND dg.season = gl.season);

-- 3) 不一致的有多少（若有，列出样本）
SELECT 'decode_mismatch' AS k, COUNT(*) FROM player_gamelog gl
WHERE gl.season IS NOT NULL
  AND gl.gameid IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = gl.game_id_full AND dg.season IS NOT NULL)
  AND EXISTS (SELECT 1 FROM dim_games dg WHERE dg.nba_api_id::text = gl.gameid AND dg.season IS NOT NULL)
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.nba_api_id::text = gl.gameid AND dg.season = gl.season);

-- 4) 不一致样本
SELECT gl.gameid, gl.season AS decoded, dg.season AS real_season
FROM player_gamelog gl JOIN dim_games dg ON dg.nba_api_id::text = gl.gameid
WHERE gl.season IS NOT NULL
  AND gl.gameid IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dim_games d2 WHERE d2.game_id = gl.game_id_full AND d2.season IS NOT NULL)
  AND dg.season <> gl.season
LIMIT 15;
