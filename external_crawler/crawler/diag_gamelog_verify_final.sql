-- 最终验证：用 dim_games 验证过的规则重算孤儿 season，与当前落库值比对
SET max_parallel_workers_per_gather=0;

WITH orph AS (
  SELECT id, game_id_full, season AS cur,
         CAST(SUBSTRING(game_id_full FROM 2 FOR 2) AS int) AS yy
  FROM player_gamelog
  WHERE season IS NOT NULL AND game_id_full IS NOT NULL AND game_id_full ~ '^[0-9]{8}$'
    AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
),
recomputed AS (
  SELECT id, cur,
         CASE WHEN yy < 50 THEN 2000+yy+1 ELSE 1900+yy+1 END AS verified_season
  FROM orph
)
SELECT 'orphan_total' AS k, COUNT(*) FROM recomputed
UNION ALL
SELECT 'matches_verified_rule', COUNT(*) FILTER (WHERE cur = verified_season) FROM recomputed
UNION ALL
SELECT 'differs_from_verified', COUNT(*) FILTER (WHERE cur <> verified_season) FROM recomputed;

-- 当前孤儿 season 分布（最终态）
SELECT cur AS season, COUNT(*) FROM (
  SELECT season AS cur FROM player_gamelog
  WHERE season IS NOT NULL AND game_id_full IS NOT NULL AND game_id_full ~ '^[0-9]{8}$'
    AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
) t GROUP BY cur ORDER BY cur;
