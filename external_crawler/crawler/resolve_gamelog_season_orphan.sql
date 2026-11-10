-- ============================================================
-- player_gamelog.season 孤儿回填(第二批): 8,071 行
--   来源: 季前赛(7,722) + Play-In(349) 等, 不在 dim_games
--   方法:
--     A 组 (1,678): game_id_full 前缀为合法 YYYYMMDD -> end-year 口径(month>=10 -> year+1)
--                   [已对 dim_games 1,492,211 行验证 100% 吻合]
--     B 组 (6,393): 前缀为 8 位 NBA-API 季前赛 ID (首位=1, 2-3位=赛季年)
--                   解码 end-year 标签 = 2000 + YY + 1 (YY<50)
--                   [结构确定, 解码后全在 1997-2026, 与 end-year 口径一致]
--   回滚: player_gamelog_bak_season_orphan_20260817
-- ============================================================
SET max_parallel_workers_per_gather=0;

-- 1) 回滚快照(仅受影响的孤儿 NULL 行)
DROP TABLE IF EXISTS player_gamelog_bak_season_orphan_20260817;
CREATE TABLE player_gamelog_bak_season_orphan_20260817 AS
SELECT id, game_id_full, season AS old_season
FROM player_gamelog
WHERE season IS NULL AND game_id_full IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL);

-- 2) 事务内回填
BEGIN;

-- A 组: 合法日期孤儿 -> end-year
UPDATE player_gamelog gl
SET season = CASE
               WHEN EXTRACT(MONTH FROM CAST(SUBSTRING(gl.game_id_full FROM 1 FOR 8) AS date)) >= 10
               THEN EXTRACT(YEAR FROM CAST(SUBSTRING(gl.game_id_full FROM 1 FOR 8) AS date))::int + 1
               ELSE EXTRACT(YEAR FROM CAST(SUBSTRING(gl.game_id_full FROM 1 FOR 8) AS date))::int
             END
WHERE gl.season IS NULL
  AND gl.game_id_full ~ '^[0-9]{8}'
  AND SUBSTRING(gl.game_id_full FROM 1 FOR 8) ~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = gl.game_id_full AND dg.season IS NOT NULL);

-- B 组: NBA-API 季前赛 ID 孤儿 -> 解码 end-year
UPDATE player_gamelog gl
SET season = CASE
               WHEN CAST(SUBSTRING(gl.game_id_full FROM 2 FOR 2) AS int) < 50
               THEN 2000 + CAST(SUBSTRING(gl.game_id_full FROM 2 FOR 2) AS int) + 1
               ELSE 1900 + CAST(SUBSTRING(gl.game_id_full FROM 2 FOR 2) AS int) + 1
             END
WHERE gl.season IS NULL
  AND gl.game_id_full ~ '^[0-9]{8}'
  AND SUBSTRING(gl.game_id_full FROM 1 FOR 8) !~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = gl.game_id_full AND dg.season IS NOT NULL);

COMMIT;

-- 3) 复核
SELECT 'remaining_null_total' AS chk, COUNT(*) AS n
FROM player_gamelog WHERE season IS NULL;

SELECT 'filled_from_snapshot' AS chk, COUNT(*) AS n
FROM player_gamelog_bak_season_orphan_20260817 b
JOIN player_gamelog gl ON gl.id = b.id
WHERE gl.season IS NOT NULL AND b.old_season IS NULL;

-- 回填后 season 分布(孤儿段)
SELECT gl.season, COUNT(*) AS n
FROM player_gamelog gl
JOIN player_gamelog_bak_season_orphan_20260817 b ON b.id = gl.id
GROUP BY gl.season ORDER BY gl.season;
