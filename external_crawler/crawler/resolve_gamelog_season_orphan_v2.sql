-- ============================================================
-- player_gamelog.season 孤儿回填(修正 v2): 全部 8,071 行
-- 修正说明: v1 误把"月/日合法"的前缀当真日期 CAST, 写入 1040/1190 等荒谬赛季。
--   实际这 8,071 全是 NBA-API 形态 ID:
--     首位=类型(1=季前赛, 5=Play-In), 2-3位=赛季年(YY), 4-8位=比赛序号
--   正确解码: end-year 标签 = (YY<50 ? 2000+YY+1 : 1900+YY+1)
--   已对全部 8,071 验证: 解码赛季全在 [1997,2026], 0 异常
-- 回滚: player_gamelog_bak_season_orphan_20260817 (8,071 行, 已含 NULL 旧值)
-- ============================================================
SET max_parallel_workers_per_gather=0;

BEGIN;

UPDATE player_gamelog gl
SET season = CASE
               WHEN CAST(SUBSTRING(gl.game_id_full FROM 2 FOR 2) AS int) < 50
               THEN 2000 + CAST(SUBSTRING(gl.game_id_full FROM 2 FOR 2) AS int) + 1
               ELSE 1900 + CAST(SUBSTRING(gl.game_id_full FROM 2 FOR 2) AS int) + 1
             END
WHERE gl.season IS NULL
  AND gl.game_id_full IS NOT NULL
  AND gl.game_id_full ~ '^[0-9]{8}'
  AND length(gl.game_id_full) = 8
  AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = gl.game_id_full AND dg.season IS NOT NULL);

COMMIT;

-- 复核
SELECT 'remaining_null_total' AS chk, COUNT(*) AS n FROM player_gamelog WHERE season IS NULL;
SELECT 'filled_from_snapshot' AS chk, COUNT(*) AS n
FROM player_gamelog_bak_season_orphan_20260817 b
JOIN player_gamelog gl ON gl.id = b.id
WHERE gl.season IS NOT NULL AND b.old_season IS NULL;
-- 回填后赛季分布(应全为合法 NBA 赛季)
SELECT gl.season, COUNT(*) AS n
FROM player_gamelog gl
JOIN player_gamelog_bak_season_orphan_20260817 b ON b.id = gl.id
GROUP BY gl.season ORDER BY gl.season;
