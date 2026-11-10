-- 给 player_gamelog 的季前赛(type-1 孤儿)行打 banned 标记，分析时 WHERE NOT banned 即可跳过。
-- 非物理删除，完全可回滚：
--   解 ban： UPDATE player_gamelog SET banned=FALSE WHERE banned;
--   撤列：   ALTER TABLE player_gamelog DROP COLUMN banned;
--   恢复集： player_gamelog_banned_ids_20260817 (id 备份)
SET max_parallel_workers_per_gather=0;

BEGIN;

-- 1) 留存待 ban 行的 id 备份（便于回滚/审计）
DROP TABLE IF EXISTS player_gamelog_banned_ids_20260817;
CREATE TABLE player_gamelog_banned_ids_20260817 AS
SELECT id, game_id_full, player_name, team, season
FROM player_gamelog
WHERE game_id_full ~ '^1[0-9]{7}$'
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL);

-- 2) 加标记列（PostgreSQL 11+ 加带默认值的列是即时元数据操作，不重写表）
ALTER TABLE player_gamelog ADD COLUMN IF NOT EXISTS banned BOOLEAN NOT NULL DEFAULT FALSE;

-- 3) 打标记
UPDATE player_gamelog
SET banned = TRUE
WHERE game_id_full ~ '^1[0-9]{7}$'
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL);

COMMIT;

-- 复核
SELECT 'banned_true' AS chk, COUNT(*) AS n FROM player_gamelog WHERE banned;
SELECT 'banned_false' AS chk, COUNT(*) AS n FROM player_gamelog WHERE NOT banned;
SELECT 'backup_ids'  AS chk, COUNT(*) AS n FROM player_gamelog_banned_ids_20260817;
SELECT 'banned_set_season_null' AS chk, COUNT(*) AS n FROM player_gamelog WHERE banned AND season IS NULL;
