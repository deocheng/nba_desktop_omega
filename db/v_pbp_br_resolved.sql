-- db/v_pbp_br_resolved.sql
-- ============================================================================
-- v_pbp_br_resolved —— 只读视图（下游零侵入关键）
-- 用 pbp.gameid = m.nba_api_id 左连 game_id_map，使「PBP 挂在 nba_api_id 下、
-- 但下游按 BR gid 查不到」的约 4655 场自动以 gameid_resolved = br_gid 暴露，
-- 无需复制任何行、不污染 play_by_play 热表。
-- 下游战术引擎只需把 `FROM play_by_play WHERE gameid = :gid`
-- 改为 `FROM v_pbp_br_resolved WHERE gameid_resolved = :gid`。
-- ============================================================================
CREATE OR REPLACE VIEW v_pbp_br_resolved AS
SELECT
    pbp.*,
    COALESCE(m.br_gid, pbp.gameid)        AS gameid_resolved,  -- 下游统一按此列查 BR gid
    m.nba_api_id                          AS gameid_api,
    m.espn_event                          AS espn_event
FROM play_by_play pbp
LEFT JOIN game_id_map m
       ON pbp.gameid = m.nba_api_id;
