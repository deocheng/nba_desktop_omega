-- 核查：回滚前状态确认
SET max_parallel_workers_per_gather=0;

-- 1) 当前全表 season 非空 / NULL 计数
SELECT 'current_total'            AS k, COUNT(*)               FROM player_gamelog
UNION ALL
SELECT 'current_season_nonnull', COUNT(*) FROM player_gamelog WHERE season IS NOT NULL
UNION ALL
SELECT 'current_season_null',    COUNT(*) FROM player_gamelog WHERE season IS NULL;

-- 2) 回滚快照内容（old_season 应为 NULL，因快照在解码 UPDATE 前抓取）
SELECT 'snap_rows'            AS k, COUNT(*)                              FROM player_gamelog_bak_season_orphan_20260817
UNION ALL
SELECT 'snap_old_null',       COUNT(*) FILTER (WHERE old_season IS NULL) FROM player_gamelog_bak_season_orphan_20260817
UNION ALL
SELECT 'snap_old_nonnull',    COUNT(*) FILTER (WHERE old_season IS NOT NULL) FROM player_gamelog_bak_season_orphan_20260817;

-- 3) 当前孤儿集（game_id_full 不在 dim_games 的 8,071 行，现被解码成非空）——回滚目标
SELECT 'orphan_decoded_now' AS k, COUNT(*) FROM player_gamelog gl
WHERE gl.game_id_full IS NOT NULL
  AND gl.season IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = gl.game_id_full AND dg.season IS NOT NULL);
