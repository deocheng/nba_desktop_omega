-- docs/coverage_onoff.sql — 球员级 on-off 覆盖率校验（纯 DB 只读，零 BR 请求）。
--
-- 维度：per (player_id, season) —— on-off 一页覆盖某球员某赛季（Regular+Playoffs 各 3 行）。
-- universe = player_shooting DISTINCT (player_id, season)
--             WHERE season_type='Regular' AND player_id IS NOT NULL AND season>=1997
--             LEFT JOIN player_onoff_404 排除已隔离 (slug, year) 对
-- covered  = player_onoff DISTINCT (player_id, season)
--
-- 结果集首行四列：universe | covered | coverage_pct | gap
-- 供 run_player_onoff_auto.sh 的 verify_coverage() 解析做 DONE 守门。

SELECT
    universe,
    covered,
    CASE WHEN universe > 0
         THEN round(100.0 * covered / universe, 2)
         ELSE 100.0 END AS coverage_pct,
    (universe - covered) AS gap
FROM (
    SELECT
        (SELECT COUNT(*) FROM (
            SELECT DISTINCT ps.player_id, ps.season
            FROM player_shooting ps
            LEFT JOIN player_onoff_404 q
                   ON q.slug = ps.player_id AND q.year = ps.season
            WHERE ps.season_type = 'Regular'
              AND ps.player_id IS NOT NULL
              AND ps.season >= 1997
              AND q.slug IS NULL
        ) u) AS universe,
        (SELECT COUNT(*) FROM (
            SELECT DISTINCT player_id, season
            FROM player_onoff
            WHERE player_id IS NOT NULL
        ) c) AS covered
) t;
