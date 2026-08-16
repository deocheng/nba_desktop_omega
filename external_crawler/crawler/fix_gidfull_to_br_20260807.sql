-- =====================================================================
-- fix_gidfull_to_br_20260807.sql
-- 目的: 把 player_gamelog.game_id_full 全面规整成 BR game_id 格式,
--       以 BR game_id 对齐 dim_games.game_id, 使其成为唯一的连接/回填键。
--       nba_api_id(数字)从此仅作附属属性, 不再作连接键。
--
-- 规整路径(因 dim_games.nba_api_id 已有唯一约束, 保证 1:1 无歧义):
--   player_gamelog.gameid(=nba_api_id 数字)  ->  dim_games.nba_api_id
--       ->  dim_games.game_id(BR, 如 202512090TOR)  ->  写回 game_id_full
--
-- 处理对象: game_id_full 为 NULL 或纯数字(零填充10位/8位无前导零)的行。
--           已是 BR 式(^[0-9]{9}[A-Z]{3}$)的行不动。
--
-- 已知残留(本轮不改, 报告给用户):
--   约 8071 行季前赛(1 前缀)+Play-In(5 前缀), 其 nba_api_id 在 dim_games
--   无对应, 且 gamelog 无比赛日期列, 无法自力构造 BR game_id -> 保持原值。
--
-- 安全措施: 备份表 + 按 season 分批(防 OOM) + 自校验 + 干跑/落盘开关。
-- 用法: 干跑  psql ... -v real=false -f 本文件
--       落盘  psql ... -v real=true  -f 本文件
-- =====================================================================
\set ON_ERROR_STOP on
\timing on

BEGIN;

-- ---------- 1. 备份受影响行(仅关键列, id 主键足以回滚 game_id_full) ----------
DROP TABLE IF EXISTS player_gamelog_gidfull_bak_20260807;
CREATE TABLE player_gamelog_gidfull_bak_20260807 AS
SELECT id, gameid, game_id_full AS old_gid_full, season
FROM player_gamelog
WHERE game_id_full IS NULL OR game_id_full ~ '^[0-9]+$';

\echo '--- 备份行数(应 = 611329) ---'
SELECT count(*) AS backup_rows FROM player_gamelog_gidfull_bak_20260807;

-- ---------- 2. 按 season 分批 UPDATE(防 OOM) ----------
DO $$
DECLARE s smallint; n bigint; tot bigint := 0;
BEGIN
  FOR s IN SELECT DISTINCT season FROM player_gamelog WHERE season IS NOT NULL ORDER BY 1 LOOP
    UPDATE player_gamelog p
       SET game_id_full = d.game_id
      FROM dim_games d
     WHERE p.season = s
       AND p.gameid ~ '^[0-9]+$'
       AND (p.game_id_full IS NULL OR p.game_id_full ~ '^[0-9]+$')
       AND d.nba_api_id = p.gameid::bigint;
    GET DIAGNOSTICS n = ROW_COUNT; tot := tot + n;
    IF n > 0 THEN RAISE NOTICE 'season % : % rows', s, n; END IF;
  END LOOP;

  -- season IS NULL 批
  UPDATE player_gamelog p
     SET game_id_full = d.game_id
    FROM dim_games d
   WHERE p.season IS NULL
     AND p.gameid ~ '^[0-9]+$'
     AND (p.game_id_full IS NULL OR p.game_id_full ~ '^[0-9]+$')
     AND d.nba_api_id = p.gameid::bigint;
  GET DIAGNOSTICS n = ROW_COUNT; tot := tot + n;
  IF n > 0 THEN RAISE NOTICE 'season NULL : % rows', n; END IF;

  RAISE NOTICE '=== TOTAL updated: % rows (期望 603258) ===', tot;
END $$;

-- ---------- 3. 自校验 ----------
\echo '--- 自校验: 备份/改后BR式/残留非BR ---'
SELECT
  (SELECT count(*) FROM player_gamelog_gidfull_bak_20260807)                                   AS backup_rows,
  (SELECT count(*) FROM player_gamelog WHERE game_id_full ~ '^[0-9]{9}[A-Z]{3}$')              AS br_after,
  (SELECT count(*) FROM player_gamelog WHERE game_id_full IS NULL OR game_id_full ~ '^[0-9]+$') AS remain_nonbr;

\echo '--- 残留(孤儿)按 gameid 前3位分布(应全为 1xx 季前赛 / 5xx Play-In) ---'
SELECT left(gameid,3) AS pfx, count(*) AS n
FROM player_gamelog
WHERE (game_id_full IS NULL OR game_id_full ~ '^[0-9]+$') AND gameid ~ '^[0-9]+$'
GROUP BY 1 ORDER BY 2 DESC LIMIT 12;

\echo '--- 对齐校验(2024-2026): 改后 BR 式行 game_id_full 是否 == dim_games.game_id ---'
SELECT count(*) AS checked,
       count(*) FILTER (WHERE p.game_id_full = d.game_id) AS aligned,
       count(*) FILTER (WHERE p.game_id_full <> d.game_id) AS misaligned
FROM player_gamelog p
JOIN dim_games d ON d.nba_api_id = p.gameid::bigint
WHERE p.season IN (2024,2025,2026)
  AND p.gameid ~ '^[0-9]+$'
  AND p.game_id_full ~ '^[0-9]{9}[A-Z]{3}$';

-- ---------- 4. 干跑/落盘开关 ----------
\if :real
  COMMIT;
  \echo '################ COMMITTED ################'
\else
  ROLLBACK;
  \echo '################ ROLLED BACK (dry-run) ################'
\endif
