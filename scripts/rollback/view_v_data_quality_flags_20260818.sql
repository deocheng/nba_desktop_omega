CREATE OR REPLACE VIEW analytics.v_data_quality_flags AS 
 SELECT 'player_gamelog'::text AS table_name,
    'player_id'::text AS column_name,
    'null_key'::text AS issue_type,
        CASE
            WHEN (1.0 * count(*) FILTER (WHERE player_gamelog.player_id IS NULL)::numeric / count(*)::numeric) > 0.6 THEN 'CRITICAL'::text
            WHEN (1.0 * count(*) FILTER (WHERE player_gamelog.player_id IS NULL)::numeric / count(*)::numeric) > 0.3 THEN 'WARN'::text
            ELSE 'INFO'::text
        END AS severity,
    round(1.0 * count(*) FILTER (WHERE player_gamelog.player_id IS NULL)::numeric / count(*)::numeric, 3) AS metric_value,
    now() AS detected_at
   FROM player_gamelog
UNION ALL
 SELECT 'weight'::text AS table_name,
    'weight'::text AS column_name,
    'unit_mismatch'::text AS issue_type,
    'CRITICAL'::text AS severity,
    round((( SELECT avg(fact_player_season_stats.weight) AS avg
           FROM fact_player_season_stats)) / (( SELECT avg(dim_players.weight_kg) AS avg
           FROM dim_players)), 2) AS metric_value,
    now() AS detected_at
UNION ALL
 SELECT 'player_id_bridge'::text AS table_name,
    'nba_player_id'::text AS column_name,
    'identity_1_to_n'::text AS issue_type,
        CASE
            WHEN count(*) FILTER (WHERE player_id_bridge.nba_player_id IS NULL) > 0 THEN 'CRITICAL'::text
            ELSE 'WARN'::text
        END AS severity,
    count(*) FILTER (WHERE player_id_bridge.nba_player_id IS NULL) AS metric_value,
    now() AS detected_at
   FROM player_id_bridge
UNION ALL
 SELECT 'play_by_play'::text AS table_name,
    'x'::text AS column_name,
    'coord_coverage'::text AS issue_type,
        CASE
            WHEN (1.0 * count(*) FILTER (WHERE play_by_play_bak_20260730.x IS NOT NULL)::numeric / count(*)::numeric) < 0.5 THEN 'WARN'::text
            ELSE 'INFO'::text
        END AS severity,
    round(1.0 * count(*) FILTER (WHERE play_by_play_bak_20260730.x IS NOT NULL)::numeric / count(*)::numeric, 3) AS metric_value,
    now() AS detected_at
   FROM play_by_play_bak_20260730
  GROUP BY play_by_play_bak_20260730.source
UNION ALL
 SELECT 'injuries'::text AS table_name,
    'report_date'::text AS column_name,
    'future_date'::text AS issue_type,
        CASE
            WHEN count(*) FILTER (WHERE injuries.report_date > CURRENT_DATE) > 0 THEN 'CRITICAL'::text
            ELSE 'INFO'::text
        END AS severity,
    count(*) FILTER (WHERE injuries.report_date > CURRENT_DATE) AS metric_value,
    now() AS detected_at
   FROM injuries
UNION ALL
 SELECT 'fact_player_season_stats'::text AS table_name,
    'vorp'::text AS column_name,
    'null_rate'::text AS issue_type,
        CASE
            WHEN (1.0 * count(*) FILTER (WHERE fact_player_season_stats.vorp IS NULL)::numeric / count(*)::numeric) > 0.3 THEN 'WARN'::text
            ELSE 'INFO'::text
        END AS severity,
    round(1.0 * count(*) FILTER (WHERE fact_player_season_stats.vorp IS NULL)::numeric / count(*)::numeric, 3) AS metric_value,
    now() AS detected_at
   FROM fact_player_season_stats
  WHERE fact_player_season_stats.season >= 2016
UNION ALL
 SELECT 'play_by_play'::text AS table_name,
    'dist'::text AS column_name,
    'physically_impossible'::text AS issue_type,
        CASE
            WHEN count(*) FILTER (WHERE play_by_play_bak_20260730.dist > 94) > 0 THEN 'WARN'::text
            ELSE 'INFO'::text
        END AS severity,
    count(*) FILTER (WHERE play_by_play_bak_20260730.dist > 94) AS metric_value,
    now() AS detected_at
   FROM play_by_play_bak_20260730;;
