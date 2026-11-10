-- 回填 player_gamelog.season 的 NULL（经 dim_games 权威反推，纯 DB 操作，不碰爬虫）
-- 连接键: player_gamelog.game_id_full (BR) <-> dim_games.game_id (BR, 主键, 已索引)
-- 口径: 直接抄 dim_games.season（权威），不自行推断日期，避免错值。
-- 范围: 仅回填能匹配 dim_games 的行(预期 42669)；孤儿(季前赛/Play-In, 不在 dim_games)保留 NULL。

-- 0) 回滚快照: 仅受影响(NULL-season)行的 (id, 旧 season)
DROP TABLE IF EXISTS player_gamelog_bak_season_20260817;
CREATE TABLE player_gamelog_bak_season_20260817 AS
SELECT id, season AS old_season FROM player_gamelog WHERE season IS NULL;

-- 1) 回填: 经 dim_games.game_id 反推 season
UPDATE player_gamelog gl
SET season = dg.season
FROM dim_games dg
WHERE gl.season IS NULL
  AND gl.game_id_full IS NOT NULL
  AND dg.game_id = gl.game_id_full
  AND dg.season IS NOT NULL;

-- 2) 复核(应只剩孤儿 8071 行 NULL)
-- SELECT COUNT(*) AS null_remaining FROM player_gamelog WHERE season IS NULL;
-- SELECT COUNT(*) AS filled FROM player_gamelog_bak_season_20260817 b
--   JOIN player_gamelog gl ON gl.id=b.id WHERE gl.season IS NOT NULL AND b.old_season IS NULL;
