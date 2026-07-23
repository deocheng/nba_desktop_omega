-- ============================================================================
-- coverage_lineup.sql — player_lineups 覆盖率/gap 校验
-- 集群 B: 127.0.0.1:5433 / nba / postgres  (口令走 PGPASSWORD)
--
-- 用途:
--   1) Regular 覆盖率基准与缺口（auto runner 的 verify_coverage 守门解析首个结果集）
--   2) 缺口按赛季分布（诊断定位）
--
-- 宇宙源: player_shooting DISTINCT (player_id, season) WHERE Regular AND >=1997
--   ⚠️ 禁用 player_gamelog.br_player_id（corrupt，含 phantom slug）
-- 扣除: player_lineups_404 已隔离的 (slug, year) 对
-- 已覆盖: player_lineups DISTINCT (player_id, season)
-- gap = universe - covered
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1) 汇总: universe | covered | coverage_pct | gap
--    （auto runner 的 verify_coverage 解析本行，4 列 pipe-separated）
-- ---------------------------------------------------------------------------
WITH universe AS (
    SELECT DISTINCT ps.player_id AS slug, ps.season AS year
    FROM player_shooting ps
    LEFT JOIN player_lineups_404 q
           ON q.slug = ps.player_id AND q.year = ps.season
    WHERE ps.season_type = 'Regular'
      AND ps.player_id IS NOT NULL
      AND ps.season >= 1997            -- MIN_SEASON, 对齐爬虫下界
      AND q.slug IS NULL               -- 排除已隔离(404) (slug, year) 对，口径诚实
),
covered AS (
    SELECT DISTINCT player_id AS slug, season AS year
    FROM player_lineups
    WHERE player_id IS NOT NULL
)
SELECT
    (SELECT COUNT(*) FROM universe)                                 AS universe,
    (SELECT COUNT(*) FROM covered)                                  AS covered,
    ROUND(100.0 * (SELECT COUNT(*) FROM covered)
          / NULLIF((SELECT COUNT(*) FROM universe), 0), 1)          AS coverage_pct,
    (SELECT COUNT(*) FROM universe)
        - (SELECT COUNT(*) FROM covered)                            AS gap;

-- ---------------------------------------------------------------------------
-- 2) 缺口按赛季分布（诊断定位，不参与 verify_coverage 守门）
-- ---------------------------------------------------------------------------
WITH universe AS (
    SELECT DISTINCT ps.player_id AS slug, ps.season AS year
    FROM player_shooting ps
    LEFT JOIN player_lineups_404 q
           ON q.slug = ps.player_id AND q.year = ps.season
    WHERE ps.season_type = 'Regular'
      AND ps.player_id IS NOT NULL
      AND ps.season >= 1997
      AND q.slug IS NULL
),
covered AS (
    SELECT DISTINCT player_id AS slug, season AS year
    FROM player_lineups
    WHERE player_id IS NOT NULL
)
SELECT u.year AS season,
       COUNT(*)                                           AS universe,
       COUNT(*) FILTER (WHERE c.slug IS NOT NULL)         AS covered,
       COUNT(*) FILTER (WHERE c.slug IS NULL)            AS gap
FROM universe u
LEFT JOIN covered c USING (slug, year)
GROUP BY u.year
ORDER BY u.year;
