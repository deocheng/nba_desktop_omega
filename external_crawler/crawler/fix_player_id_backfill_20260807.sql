-- ============================================================
-- 回填 player_gamelog.player_id / nba_player_id（NBA 数字球员 id）
-- 根因：BR 爬虫 build_insert 从不写这两列（只写 br_player_id + gameid），
--       导致 2024/2026 等纯 BR 爬取季的 NBA 数字球员 id 全 NULL，
--       2023/2025 的 BR-only 部分行也缺失。
-- 修复：从 player_id_bridge(br_player_id -> nba_player_id) 桥接回填。
-- 幂等：只动 player_id IS NULL 的行；可重复运行。
-- 仅在需要回滚时保留备份表 player_gamelog_bak_pid_20260807。
-- ============================================================

-- 0) 备份（受影响行的 id / player_id / nba_player_id / br_player_id / season）
DROP TABLE IF EXISTS player_gamelog_bak_pid_20260807;
CREATE TABLE player_gamelog_bak_pid_20260807 AS
SELECT id, player_id, nba_player_id, br_player_id, season
FROM player_gamelog
WHERE player_id IS NULL OR nba_player_id IS NULL;

-- 1) 回填（两列都设成 bridge 的 nba_player_id）
UPDATE player_gamelog p
SET player_id     = b.nba_player_id::bigint,
    nba_player_id = b.nba_player_id::bigint
FROM (
    SELECT DISTINCT ON (br_player_id) br_player_id, nba_player_id
    FROM player_id_bridge
    WHERE nba_player_id IS NOT NULL
    ORDER BY br_player_id, nba_player_id
) b
WHERE (p.player_id IS NULL OR p.nba_player_id IS NULL)
  AND p.br_player_id = b.br_player_id
  AND p.br_player_id IS NOT NULL AND p.br_player_id <> '';

-- 2) 自校验：各季 player_id / nba_player_id 仍 NULL 的行数
SELECT season,
       count(*)                                  AS rows,
       count(*) FILTER (WHERE player_id IS NULL)     AS pid_null,
       count(*) FILTER (WHERE nba_player_id IS NULL) AS nba_pid_null,
       count(DISTINCT br_player_id) FILTER (WHERE player_id IS NULL) AS br_null_distinct
FROM player_gamelog
GROUP BY season
ORDER BY season;
