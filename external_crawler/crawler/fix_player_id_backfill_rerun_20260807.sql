-- 重跑 player_id / nba_player_id 回填（crawler 已停，结果将永久生效）
-- 备份表 player_gamelog_bak_pid_20260807 已在首次回填时建立，可作回滚点，此处不重建。
-- 本 UPDATE 幂等：只动 player_id/nba_player_id 为 NULL 的行，不覆盖 NBA-API 源已有值。
-- 连接键 = br_player_id；bridge 用 DISTINCT ON(br_player_id) 取稳定 nba_player_id（歧义极小）。

UPDATE player_gamelog p
SET player_id     = b.nba_player_id::bigint,
    nba_player_id = b.nba_player_id::bigint
FROM (
    SELECT DISTINCT ON (br_player_id) br_player_id, nba_player_id
    FROM player_id_bridge
    WHERE nba_player_id IS NOT NULL
    ORDER BY br_player_id, nba_player_id
) b
WHERE p.br_player_id = b.br_player_id
  AND (p.player_id IS NULL OR p.nba_player_id IS NULL)
  AND p.season BETWEEN 2023 AND 2026;

-- 回填后核对（应只剩 player_id_bridge 本身缺 NBA id 的球员为 NULL）
SELECT season,
       count(*)                                                        AS rows,
       count(player_id)     FILTER (WHERE player_id IS NOT NULL)      AS pid_ok,
       count(player_id)     FILTER (WHERE player_id IS NULL)          AS pid_null,
       count(nba_player_id) FILTER (WHERE nba_player_id IS NOT NULL)  AS nba_ok,
       count(nba_player_id) FILTER (WHERE nba_player_id IS NULL)      AS nba_null
FROM player_gamelog
WHERE season BETWEEN 2023 AND 2026
GROUP BY season ORDER BY season;
