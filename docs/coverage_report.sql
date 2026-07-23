-- ============================================================================
-- coverage_report.sql — player_shooting_backfill 覆盖率校验（T5）
-- 集群 B: 127.0.0.1:5433 / nba / postgres  (口令走 PGPASSWORD)
-- 用途:
--   1) Regular 覆盖率基准(59.8%)与缺口(~9,797)
--   2) Playoffs 覆盖率 (随页顺带; 回填后 po_orphan 应→0)
--   3) Bug2 记录 (player_gamelog 1997-2000 br_player_id NULL, 仅记录不修)
-- 回填/爬虫完成后重跑本文件, 对比前后口径.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1) Regular 覆盖率: 基准 = gamelog 有 BR slug 的 (球员,赛季) 组合
-- ---------------------------------------------------------------------------
WITH universe AS (
    SELECT DISTINCT g.br_player_id AS slug, g.season
    FROM player_gamelog g
    LEFT JOIN player_shooting_404 q ON q.slug = g.br_player_id
    WHERE g.br_player_id IS NOT NULL
      AND g.season >= 1997            -- MIN_SEASON, 对齐爬虫下界
      AND q.slug IS NULL              -- 排除已隔离(404/corrupted) slug，口径诚实
),
covered AS (
    SELECT DISTINCT player_id AS slug, season
    FROM player_shooting
    WHERE season_type = 'Regular'
      AND player_id IS NOT NULL
)
SELECT
    (SELECT COUNT(*) FROM universe)                                 AS universe_combos,
    (SELECT COUNT(*) FROM covered)                                  AS covered_combos,
    ROUND(100.0 * (SELECT COUNT(*) FROM covered)
          / NULLIF((SELECT COUNT(*) FROM universe), 0), 1)          AS regular_coverage_pct,
    (SELECT COUNT(*) FROM universe)
        - (SELECT COUNT(*) FROM covered)                            AS regular_gap;

-- 缺口按年代分布 (定位 2001-2026 的 58%-87% 段)
WITH universe AS (
    SELECT DISTINCT g.br_player_id AS slug, g.season
    FROM player_gamelog g
    LEFT JOIN player_shooting_404 q ON q.slug = g.br_player_id
    WHERE g.br_player_id IS NOT NULL AND g.season >= 1997
      AND q.slug IS NULL              -- 排除已隔离(404/corrupted) slug
),
covered AS (
    SELECT DISTINCT player_id AS slug, season
    FROM player_shooting
    WHERE season_type = 'Regular' AND player_id IS NOT NULL
)
SELECT u.season,
       COUNT(*)                                           AS universe,
       COUNT(*) FILTER (WHERE c.slug IS NOT NULL)         AS covered,
       COUNT(*) FILTER (WHERE c.slug IS NULL)            AS gap
FROM universe u
LEFT JOIN covered c USING (slug, season)
GROUP BY u.season
ORDER BY u.season;

-- ---------------------------------------------------------------------------
-- 2) Playoffs 覆盖率 (随页顺带; 回填后 po_orphan 应→0)
-- ---------------------------------------------------------------------------
SELECT
    COUNT(*) FILTER (WHERE season_type='Playoffs' AND player_id IS NOT NULL) AS po_with_id,
    COUNT(*) FILTER (WHERE season_type='Playoffs' AND player_id IS NULL)     AS po_orphan,
    COUNT(*) FILTER (WHERE season_type='Regular' AND player_id IS NOT NULL)  AS rs_with_id,
    COUNT(*)                                                        AS total_rows
FROM player_shooting;

-- ---------------------------------------------------------------------------
-- 3) Bug2 记录 (仅记录, 不修): player_gamelog 1997-2000 br_player_id NULL
-- ---------------------------------------------------------------------------
SELECT season, COUNT(*) AS null_slug_rows
FROM player_gamelog
WHERE season BETWEEN 1997 AND 2000
  AND br_player_id IS NULL
GROUP BY season
ORDER BY season;

-- ---------------------------------------------------------------------------
-- 4) T5 DDL: 补唯一约束（T0 实测确认 player_shooting 原本 0 索引 / 0 唯一约束）
--    ON CONFLICT(player_id, season, season_type, team) 的前置条件。
--    幂等：CREATE UNIQUE INDEX IF NOT EXISTS（T0 已确认无重复 4 列组合）。
--    注意：本 DDL 必须在爬虫 A 的 upsert 之前执行（runner 已内置此步）。
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uq_player_shooting_key
  ON player_shooting (player_id, season, season_type, team);

-- 回查表（B 回填歧义/缺失行登记，T1 创建；此处再次确保存在）
CREATE TABLE IF NOT EXISTS backfill_review (
    id          SERIAL PRIMARY KEY,
    season      BIGINT,
    player      TEXT,
    season_type VARCHAR,
    reason      TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);
