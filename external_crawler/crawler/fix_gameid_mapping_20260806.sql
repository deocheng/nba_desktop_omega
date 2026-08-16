-- =============================================================
-- 修复 dim_games.nba_api_id 缺口 + player_gamelog.gameid 错挂
-- 生成日期: 2026-08-06
-- 用法:
--   干跑: psql ... -v mode=dry  -f fix_gameid_mapping_20260806.sql
--   落盘: psql ... -v mode=real -f fix_gameid_mapping_20260806.sql
-- 依据:
--   1) dim_games.game_id (BR 主键) 从未被污染 -> 唯一可信锚点
--   2) player_gamelog.game_id_full 存 BR 主键 -> 可反查正确 nba_api_id
--   3) play_by_play(season=2026) 的数字 gameid 提供独立比分+球队证据
-- =============================================================
\set ON_ERROR_STOP on
BEGIN;

-- ---------- 0. 备份 ----------
DROP TABLE IF EXISTS dim_games_bak_20260806b;
CREATE TABLE dim_games_bak_20260806b AS
  SELECT game_id, season, season_type, nba_api_id FROM dim_games WHERE season BETWEEN 2024 AND 2026;

DROP TABLE IF EXISTS player_gamelog_bak_20260806b;
CREATE TABLE player_gamelog_bak_20260806b AS
  SELECT * FROM player_gamelog
  WHERE gameid LIKE '223%' OR gameid LIKE '224%' OR gameid LIKE '225%';

-- ---------- 1. dim_games: 补齐 2026 常规赛 27 场缺失 nba_api_id ----------
-- 27 条中 26 条经 play_by_play「最终比分 + 参赛双方」双重确认；
-- 1 条 (202512150LAC -> 22501226) 由 27 空闲 id : 27 缺口场次的 1:1 排他法确定(该 id 无 pbp)。
CREATE TEMP TABLE fix26(game_id text PRIMARY KEY, new_id bigint, evidence text);
INSERT INTO fix26 VALUES
 ('202512090TOR',22501202,'pbp score+team'),('202512100LAL',22501204,'pbp score+team'),
 ('202512110HOU',22501205,'pbp score+team'),('202512110MIL',22501206,'pbp score+team'),
 ('202512110SAC',22501208,'pbp score+team'),('202512120CHO',22501209,'pbp score+team'),
 ('202512120DAL',22501214,'pbp score+current_team'),('202512120MEM',22501213,'pbp score+team'),
 ('202512120PHI',22501211,'pbp score+team'),('202512120WAS',22501212,'pbp score+team'),
 ('202512130OKC',22501230,'pbp score+team'),('202512130ORL',22501229,'pbp score+team'),
 ('202512140CLE',22501218,'pbp score+team'),('202512140PHO',22501228,'pbp score+current_team'),
 ('202512140POR',22501221,'pbp score+team'),('202512150BOS',22501222,'pbp score+team'),
 ('202512150LAC',22501226,'1:1 elimination (no pbp)'),('202512150UTA',22501224,'pbp score+team'),
 ('202512180OKC',22500369,'pbp score+team'),('202512180SAS',22500370,'pbp score+team'),
 ('202601250MIN',22500644,'pbp score+team'),('202601290CHI',22500529,'pbp score+team'),
 ('202601310MIA',22500692,'pbp score+team'),('202603120MEM',22501111,'pbp score+team'),
 ('202603180MEM',22500651,'pbp score+team'),('202603310MIL',22500652,'pbp score+team'),
 ('202604010MEM',22501003,'pbp score+team');

-- 安全闸: 目标 id 必须当前无人占用
DO $$
DECLARE c int;
BEGIN
  SELECT count(*) INTO c FROM fix26 f
   WHERE EXISTS (SELECT 1 FROM dim_games d WHERE d.nba_api_id=f.new_id);
  IF c>0 THEN RAISE EXCEPTION '目标 nba_api_id 已被占用, 共 % 条', c; END IF;
END $$;

UPDATE dim_games d SET nba_api_id=f.new_id FROM fix26 f WHERE d.game_id=f.game_id;

-- ---------- 2. dim_games: 202604150PHI 误标常规赛, 实为 Play-In ----------
-- 证据: 2026 常规赛 4-12 结束; play_by_play 存在 gameid=52500101 (ORL/PHI, 109-97) 与本场完全一致;
--       同期 202604140CHA / 202604140PHX / 202604150LAC 均已正确标为 Play-In。
--       改后 2026 常规赛正好 1230 场。
UPDATE dim_games SET season_type='Play-In', nba_api_id=52500101 WHERE game_id='202604150PHI';

-- ---------- 3. player_gamelog: 用 game_id_full 反查正确 gameid ----------
CREATE TEMP TABLE remap AS
SELECT pg.id AS row_id, pg.gameid AS old_id, d.nba_api_id::text AS good_id,
       pg.br_player_id, d.season, pg.game_id_full
FROM player_gamelog pg
JOIN dim_games d ON d.game_id = pg.game_id_full
WHERE d.season BETWEEN 2024 AND 2026
  AND d.nba_api_id IS NOT NULL
  AND pg.br_player_id IS NOT NULL
  AND pg.gameid IS DISTINCT FROM d.nba_api_id::text;

-- 3a. 拦路行 = 已占住目标键、且自身不在搬迁集合内的行
--     实测仅 2025 的 202503170LAL 一场共 21 行, 来源为 NBA-API 抓取(game_id_full='0022400537',
--     minutes 为截断整数); 待搬入的 BR 行 minutes 为完整 M:SS。删旧留新以与全季其余 1220 场保持一致。
CREATE TEMP TABLE blockers AS
SELECT o.id AS row_id
FROM remap r
JOIN player_gamelog o ON o.gameid=r.good_id AND o.br_player_id=r.br_player_id
WHERE NOT EXISTS (SELECT 1 FROM remap r2 WHERE r2.row_id=o.id);

DROP TABLE IF EXISTS player_gamelog_quarantine_20260806;
CREATE TABLE player_gamelog_quarantine_20260806 AS
SELECT * FROM player_gamelog WHERE id IN (SELECT row_id FROM blockers);

DELETE FROM player_gamelog WHERE id IN (SELECT row_id FROM blockers);

-- 3b. 两阶段搬迁(避开唯一索引 ux_player_gamelog_game_player 的瞬时冲突)
UPDATE player_gamelog pg SET gameid = 'T'||r.good_id
  FROM remap r WHERE pg.id=r.row_id;
UPDATE player_gamelog pg SET gameid = r.good_id
  FROM remap r WHERE pg.id=r.row_id;

-- ---------- 4. 校验 ----------
\echo '=== [校验] 2026 常规赛场次与缺口 ==='
SELECT season_type, count(*) AS games, count(nba_api_id) AS with_id
FROM dim_games WHERE season=2026 GROUP BY 1 ORDER BY 1;

\echo '=== [校验] 残留错挂(应为 0) ==='
SELECT d.season, count(*) AS still_wrong
FROM player_gamelog pg JOIN dim_games d ON d.game_id=pg.game_id_full
WHERE d.season BETWEEN 2024 AND 2026 AND d.nba_api_id IS NOT NULL
  AND pg.gameid IS DISTINCT FROM d.nba_api_id::text
GROUP BY 1 ORDER BY 1;

\echo '=== [校验] 临时键残留(应为 0) ==='
SELECT count(*) AS temp_key_left FROM player_gamelog WHERE gameid LIKE 'T%';

\echo '=== [校验] 唯一键重复(应为 0) ==='
SELECT count(*) AS dup_pairs FROM (
  SELECT gameid, br_player_id FROM player_gamelog
  WHERE (gameid LIKE '223%' OR gameid LIKE '224%' OR gameid LIKE '225%') AND br_player_id IS NOT NULL
  GROUP BY 1,2 HAVING count(*)>1) x;

\echo '=== [校验] 2026 常规赛 gamelog 覆盖的比赛数 ==='
SELECT count(DISTINCT pg.gameid) AS games_with_log
FROM player_gamelog pg
WHERE EXISTS (SELECT 1 FROM dim_games d
              WHERE d.season=2026 AND d.season_type='Regular Season' AND d.nba_api_id::text=pg.gameid);

\echo '=== [校验] 变更量 ==='
SELECT 'dim_games_updated' AS item, 28 AS n
UNION ALL SELECT 'gamelog_remapped', (SELECT count(*) FROM remap)
UNION ALL SELECT 'gamelog_deleted(quarantined)', (SELECT count(*) FROM blockers);

-- ---------- 5. 提交 / 回滚 ----------
-- 调用方必须传 -v real=true (落盘) 或 -v real=false (干跑)
\if :real
  \echo '>>> mode = REAL  -> COMMIT'
  COMMIT;
\else
  \echo '>>> mode = DRY   -> ROLLBACK (未落盘)'
  ROLLBACK;
\endif
