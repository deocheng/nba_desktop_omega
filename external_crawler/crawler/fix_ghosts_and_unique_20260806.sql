-- ============================================================================
-- 全套清理: 幽灵行 + gamelog 标签修正 + 附加赛补ID + 全明星解耦 + 唯一约束
-- 日期: 2026-08-06   授权: q-0(全套一次做完) + q-1(全明星解耦)
-- ----------------------------------------------------------------------------
-- 证据基础(均已实跑确认):
--   * 2024/2025 各多出 99/8 行常规赛 nba_api_id IS NULL 行, 三重证据证冗余:
--       1) 带ID的1230行恰好铺满官方ID空间(2230/2240 0001..1230 无缺无越界)
--       2) 每队带ID场次精确=82
--       3) 107行全部能在带ID集合找到对应真实比赛(队标互换分不换 / 改期原日期)
--   * 90行 gamelog.game_id_full 指向幽灵: 84行数字gameid已指向真场(仅标签错),
--     6行(gameid=52300201)是2024东部附加赛决胜局 202404190MIA 的数据。
--   * 附加赛2幽灵 202404160CHO/DEN(占常规赛ID 22300122/23) 比分=2023-11-01拷贝,
--     HOU/MIN当年未进附加赛, 无gamelog挂载 -> 删。
--   * 202404170PHI(MIA@PHI)真实但无任何数据证据 -> 不臆造ID, 保持NULL, 不删。
--   * 全明星5季(1961-1977)整季3前缀合成ID, 无2前缀体系。003=All-Star为正确号段,
--     真正错的是常规赛首场借用了003 -> 常规赛首场行 3->2 前缀翻转(-10000000),
--     全明星行保留合规ID。目标5个2前缀ID全空闲。
-- 用法: psql ... -v real=false -f 本文件   # 干跑(ROLLBACK)
--       psql ... -v real=true  -f 本文件   # 落盘(COMMIT)
-- ============================================================================
\set ON_ERROR_STOP on
BEGIN;

-- ============================ 0. 备份 ============================
DROP TABLE IF EXISTS dim_games_bak_20260806d;
CREATE TABLE dim_games_bak_20260806d AS
SELECT * FROM dim_games
WHERE (season IN (2024,2025) AND season_type='Regular Season' AND nba_api_id IS NULL)  -- 107幽灵
   OR game_id IN ('202404160CHO','202404160DEN','202404190MIA')                          -- 附加赛3行
   OR nba_api_id IN (36000001,36600001,37000001,37500001,37600027);                      -- 全明星10行

DROP TABLE IF EXISTS player_gamelog_bak_20260806d;
CREATE TABLE player_gamelog_bak_20260806d AS
SELECT * FROM player_gamelog
WHERE game_id_full IN (
  SELECT game_id FROM dim_games
  WHERE season IN (2024,2025) AND season_type='Regular Season' AND nba_api_id IS NULL);

-- ============================ 安全闸 ============================
DO $$
DECLARE n int;
BEGIN
  -- G1: 107幽灵数量精确
  SELECT count(*) INTO n FROM dim_games
   WHERE season IN (2024,2025) AND season_type='Regular Season' AND nba_api_id IS NULL;
  IF n <> 107 THEN RAISE EXCEPTION 'G1 FAIL: 常规赛幽灵=%<>107', n; END IF;

  -- G2: 附加赛补ID目标空闲
  SELECT count(*) INTO n FROM dim_games WHERE nba_api_id=52300201;
  IF n <> 0 THEN RAISE EXCEPTION 'G2 FAIL: 52300201 已被占用(%行)', n; END IF;

  -- G3: 全明星2前缀目标空闲
  SELECT count(*) INTO n FROM dim_games
   WHERE nba_api_id IN (26000001,26600001,27000001,27500001,27600027);
  IF n <> 0 THEN RAISE EXCEPTION 'G3 FAIL: 2前缀目标已占用(%行)', n; END IF;

  -- G4: game_referees 不引用任何待删幽灵(107 + 2附加赛)
  SELECT count(*) INTO n FROM game_referees r WHERE r.game_id IN (
    SELECT game_id FROM dim_games
     WHERE season IN (2024,2025) AND season_type='Regular Season' AND nba_api_id IS NULL
    UNION ALL SELECT '202404160CHO' UNION ALL SELECT '202404160DEN');
  IF n <> 0 THEN RAISE EXCEPTION 'G4 FAIL: game_referees引用待删幽灵%行', n; END IF;

  -- G5: 附加赛2幽灵无gamelog挂载
  SELECT count(*) INTO n FROM player_gamelog WHERE game_id_full IN ('202404160CHO','202404160DEN');
  IF n <> 0 THEN RAISE EXCEPTION 'G5 FAIL: 附加赛幽灵有gamelog%行', n; END IF;

  RAISE NOTICE '全部安全闸通过';
END $$;

-- ==================== A. 补附加赛决胜局ID(有6行gamelog佐证) ====================
UPDATE dim_games SET nba_api_id=52300201 WHERE game_id='202404190MIA' AND nba_api_id IS NULL;

-- ==================== B. 修 90 行 gamelog.game_id_full ====================
-- B1: 6行附加赛决胜局数据 -> 202404190MIA
UPDATE player_gamelog SET game_id_full='202404190MIA'
WHERE gameid='52300201' AND game_id_full='202311160CHI';

-- B2: 84行标签错行 -> 数字gameid所指向的真场game_id
UPDATE player_gamelog p SET game_id_full=d.game_id
FROM dim_games d
WHERE d.nba_api_id::text = p.gameid
  AND p.game_id_full IN (
    SELECT game_id FROM dim_games
    WHERE season IN (2024,2025) AND season_type='Regular Season' AND nba_api_id IS NULL)
  AND p.gameid <> '52300201';

-- B校验: 改完后不应再有 gamelog 挂在107幽灵上
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM player_gamelog WHERE game_id_full IN (
    SELECT game_id FROM dim_games
     WHERE season IN (2024,2025) AND season_type='Regular Season' AND nba_api_id IS NULL);
  IF n <> 0 THEN RAISE EXCEPTION 'B FAIL: 仍有%行gamelog挂在幽灵上', n; END IF;
  RAISE NOTICE 'B OK: gamelog标签已全部改指向真场';
END $$;

-- ==================== C. 删 107 行常规赛幽灵 ====================
DELETE FROM dim_games
WHERE season IN (2024,2025) AND season_type='Regular Season' AND nba_api_id IS NULL;

-- ==================== D. 删 2 行附加赛幽灵 ====================
DELETE FROM dim_games WHERE game_id IN ('202404160CHO','202404160DEN');

-- ==================== E. 全明星解耦: 常规赛首场 3->2 前缀翻转 ====================
UPDATE dim_games SET nba_api_id = nba_api_id - 10000000
WHERE game_id IN ('196010190CIN','196610150BOS','197010130NYK','197510230CLE','197610260CHI')
  AND season_type='Regular Season'
  AND nba_api_id IN (36000001,36600001,37000001,37500001,37600027);

-- ==================== F. 加唯一约束 ====================
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM (
    SELECT nba_api_id FROM dim_games WHERE nba_api_id IS NOT NULL
    GROUP BY 1 HAVING count(*)>1) t;
  IF n <> 0 THEN RAISE EXCEPTION 'F FAIL: 仍有%组非NULL重复, 不能加唯一约束', n; END IF;
END $$;
DROP INDEX IF EXISTS ux_dim_games_nba_api_id;
CREATE UNIQUE INDEX ux_dim_games_nba_api_id ON dim_games(nba_api_id) WHERE nba_api_id IS NOT NULL;

-- ============================ 自校验 ============================
\echo '--- V1: 各季常规赛场次(2024/2025应=1230) ---'
SELECT season, count(*) games, count(nba_api_id) with_id, count(*) FILTER (WHERE nba_api_id IS NULL) null_id
FROM dim_games WHERE season IN (2024,2025,2026) AND season_type='Regular Season' GROUP BY 1 ORDER BY 1;

\echo '--- V2: 2024 Play-In(应6场) ---'
SELECT count(*) playin FROM dim_games WHERE season=2024 AND season_type='Play-In';

\echo '--- V3: 附加赛决胜局已补ID ---'
SELECT game_id, nba_api_id FROM dim_games WHERE game_id='202404190MIA';

\echo '--- V4: 6行附加赛gamelog已归位 ---'
SELECT game_id_full, gameid, count(*) FROM player_gamelog WHERE gameid='52300201' GROUP BY 1,2;

\echo '--- V5: 全明星解耦后(5组各独占, RS=2前缀 AS=3前缀) ---'
SELECT nba_api_id, game_id, season_type FROM dim_games
WHERE nba_api_id IN (26000001,26600001,27000001,27500001,27600027,36000001,36600001,37000001,37500001,37600027)
ORDER BY nba_api_id;

\echo '--- V6: 全库非NULL重复组(应0) ---'
SELECT count(*) dup_groups FROM (SELECT nba_api_id FROM dim_games WHERE nba_api_id IS NOT NULL GROUP BY 1 HAVING count(*)>1) t;

\echo '--- V7: 唯一索引已建 ---'
SELECT indexname FROM pg_indexes WHERE tablename='dim_games' AND indexname='ux_dim_games_nba_api_id';

\echo '--- V8: 备份表行数 ---'
SELECT 'dim_bak' t, count(*) n FROM dim_games_bak_20260806d
UNION ALL SELECT 'gamelog_bak', count(*) FROM player_gamelog_bak_20260806d;

\if :real
  \echo '>>> real=true -> COMMIT'
  COMMIT;
\else
  \echo '>>> real=false -> ROLLBACK (干跑)'
  ROLLBACK;
\endif
