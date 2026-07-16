-- ============================================================================
-- 头像覆盖度统计报告（HS-12）：按状态拆分，监控缺口收敛
-- 执行：psql "postgresql://postgres:$DB_PASSWORD@localhost:5433/nba" -f docs/headshots_coverage.sql
-- ============================================================================

-- 总体分布
SELECT
    COUNT(*)                                               AS total_players,
    COUNT(*) FILTER (WHERE headshot_status = 'ok')          AS ok,
    COUNT(*) FILTER (WHERE headshot_status = 'missing')     AS missing,
    COUNT(*) FILTER (WHERE headshot_status = 'failed')      AS failed,
    COUNT(*) FILTER (WHERE headshot_status IS NULL)         AS not_attempted,
    ROUND(100.0 * COUNT(*) FILTER (WHERE headshot_status = 'ok') / NULLIF(COUNT(*),0), 2)
                                                         AS ok_pct
FROM dim_players;

-- 失败行明细（供 --resume 重试排查）
SELECT player_id, player_name, headshot_url
FROM dim_players
WHERE headshot_status = 'failed'
ORDER BY player_id
LIMIT 200;

-- 文件实际存在性交叉校验（DB 标 ok 但文件缺失 → 需重抓）
SELECT dp.player_id
FROM dim_players dp
WHERE dp.headshot_status = 'ok'
  AND dp.headshot_path IS NOT NULL
  AND NOT pg_stat_file(dp.headshot_path, true) IS NOT NULL;
