-- 查 A 组(伪有效日期)孤儿的真实 game_id_full 格式
SET max_parallel_workers_per_gather=0;

-- A 组定义: 前缀 8 位且月/日均合法(会 PASS 日期正则)
-- 看其完整 game_id_full 样本 + 长度
SELECT game_id_full, length(game_id_full) AS len
FROM player_gamelog_bak_season_orphan_20260817
WHERE game_id_full ~ '^[0-9]{8}'
  AND SUBSTRING(game_id_full FROM 1 FOR 8) ~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
LIMIT 20;

-- 前 4 位(伪年份)分布
SELECT SUBSTRING(game_id_full FROM 1 FOR 4) AS prefix4, COUNT(*) AS n
FROM player_gamelog_bak_season_orphan_20260817
WHERE game_id_full ~ '^[0-9]{8}'
  AND SUBSTRING(game_id_full FROM 1 FOR 8) ~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
GROUP BY prefix4 ORDER BY prefix4;

-- 这些 A 组 ID 是否能在 play_by_play.gameid 或 dim_games.nba_api_id 关联到(权威佐证)?
SELECT 'a_in_pbp' AS chk, COUNT(*) AS n
FROM player_gamelog_bak_season_orphan_20260817 b
WHERE b.game_id_full ~ '^[0-9]{8}'
  AND SUBSTRING(b.game_id_full FROM 1 FOR 8) ~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
  AND EXISTS (SELECT 1 FROM play_by_play pbp WHERE pbp.gameid = b.game_id_full);
