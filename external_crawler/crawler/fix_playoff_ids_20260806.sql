-- ============================================================================
-- 修复 2026 季后赛 6 行错挂"常规赛 ID"
-- 日期: 2026-08-06
-- 背景: dim_games.nba_api_id 无唯一约束, 回填脚本按"队对"匹配时抓到了同两队之间
--       的常规赛场次 ID, 导致 6 场季后赛与 6 场常规赛共用同一 nba_api_id。
-- 定案依据:
--   1) NBA 季后赛 ID 结构 = 4 | 25 | 0 | R(轮次) | S(系列,0起) | G(场次)
--      已存在的 79 场完全吻合该结构, 空缺位置唯一确定。
--   2) play_by_play 独立副源: 6 个目标 ID 的最终比分 + 参赛双方与 dim_games
--      对应行 100% 吻合 (见下方注释)。
--   3) 42500127 经查为幻影 (NYK/ATL 系列 4-2 结束, 无第 7 场, PBP 无记录),
--      真正空缺是 42500205。
-- 影响面: 仅 dim_games 6 行。player_gamelog 在新旧 ID 与对应 BR game_id 下
--         均为 0 行 (已核实), 无需重映射。
-- 用法: psql ... -v real=false -f 本文件   # 干跑
--       psql ... -v real=true  -f 本文件   # 落盘
-- ============================================================================
\set ON_ERROR_STOP on

BEGIN;

-- ---------- 备份 ----------
DROP TABLE IF EXISTS dim_games_bak_20260806c;
CREATE TABLE dim_games_bak_20260806c AS
SELECT game_id, game_date, season, season_type, nba_api_id,
       away_team_abbr, home_team_abbr, away_pts, home_pts
FROM dim_games
WHERE season = 2026 AND season_type = 'Playoffs';

-- ---------- 映射表 ----------
CREATE TEMP TABLE po_fix(game_id text, old_id bigint, new_id bigint, note text) ON COMMIT DROP;
INSERT INTO po_fix VALUES
 -- BR game_id      错误ID      正确ID     结构定位 / PBP 比分核对
 ('202604190DET', 22500875, 42500101, 'R1S0G1 ORL@DET 112-101 | pbp h101 a112 DET,ORL'),
 ('202605020BOS', 22500021, 42500117, 'R1S1G7 PHI@BOS 109-100 | pbp h100 a109 BOS,PHI'),
 ('202605010TOR', 22500022, 42500136, 'R1S3G6 CLE@TOR 110-112 | pbp h112 a110 CLE,TOR'),
 ('202605040SAS', 22500552, 42500231, 'R2S3G1 MIN@SAS 104-102 | pbp h102 a104 MIN,SAS'),
 ('202605050DET', 22500884, 42500201, 'R2S0G1 CLE@DET 101-111 | pbp h111 a101 CLE,DET'),
 ('202605130DET', 22500494, 42500205, 'R2S0G5 CLE@DET 117-113 | pbp h113 a117 CLE,DET');

-- ---------- 安全闸 1: 6 行必须存在且当前 ID 与预期一致 ----------
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n
  FROM po_fix f JOIN dim_games d ON d.game_id = f.game_id AND d.nba_api_id = f.old_id
  WHERE d.season = 2026 AND d.season_type = 'Playoffs';
  IF n <> 6 THEN RAISE EXCEPTION 'GATE1 FAILED: 仅匹配到 % / 6 行, 库状态与预期不符', n; END IF;
  RAISE NOTICE 'GATE1 OK: 6 行待修目标锁定';
END $$;

-- ---------- 安全闸 2: 6 个目标 ID 必须完全空闲 ----------
DO $$
DECLARE n int; s text;
BEGIN
  SELECT count(*), coalesce(string_agg(d.game_id||'='||d.nba_api_id, ','), '')
    INTO n, s
  FROM dim_games d JOIN po_fix f ON d.nba_api_id = f.new_id;
  IF n <> 0 THEN RAISE EXCEPTION 'GATE2 FAILED: 目标 ID 已被占用 -> %', s; END IF;
  RAISE NOTICE 'GATE2 OK: 6 个目标 ID 均空闲';
END $$;

-- ---------- 安全闸 3: 新旧 ID 与 BR game_id 在 gamelog 中均无挂载行 ----------
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM player_gamelog p
  WHERE p.gameid IN (SELECT old_id::text FROM po_fix)
     OR p.gameid IN (SELECT new_id::text FROM po_fix)
     OR p.game_id_full IN (SELECT game_id FROM po_fix);
  IF n <> 0 THEN RAISE EXCEPTION 'GATE3 FAILED: gamelog 存在 % 行挂载, 需先处理重映射', n; END IF;
  RAISE NOTICE 'GATE3 OK: gamelog 无关联行, 本次仅改 dim_games';
END $$;

-- ---------- 执行修复 ----------
UPDATE dim_games d
SET nba_api_id = f.new_id
FROM po_fix f
WHERE d.game_id = f.game_id
  AND d.season = 2026 AND d.season_type = 'Playoffs';

-- ---------- 自校验 ----------
\echo '--- V1: 2026 季后赛总览 (应 85 场 / 85 个 ID / 全部 4 前缀 / 无重复) ---'
SELECT count(*) AS games,
       count(nba_api_id) AS with_id,
       count(DISTINCT nba_api_id) AS distinct_id,
       count(*) FILTER (WHERE left(nba_api_id::text,1) <> '4') AS bad_prefix
FROM dim_games WHERE season = 2026 AND season_type = 'Playoffs';

\echo '--- V2: 修复后 6 行明细 ---'
SELECT d.game_id, d.game_date, d.away_team_abbr||'@'||d.home_team_abbr AS mu,
       d.away_pts||'-'||d.home_pts AS sc, f.old_id, d.nba_api_id AS new_id
FROM dim_games d JOIN po_fix f ON d.game_id = f.game_id ORDER BY d.nba_api_id;

\echo '--- V3: 6 场原主常规赛现在应各自独占 ID ---'
SELECT nba_api_id, count(*) AS holders, string_agg(game_id||'/'||season_type, ' + ') AS who
FROM dim_games
WHERE nba_api_id IN (22500875,22500021,22500022,22500552,22500884,22500494)
GROUP BY 1 ORDER BY 1;

\echo '--- V4: 全库 nba_api_id 重复组 (本次应从 13 组降至 7 组) ---'
SELECT count(*) AS dup_groups FROM (
  SELECT nba_api_id FROM dim_games WHERE nba_api_id IS NOT NULL
  GROUP BY 1 HAVING count(*) > 1
) t;

\echo '--- V5: 备份表行数 (应 85) ---'
SELECT count(*) AS bak_rows FROM dim_games_bak_20260806c;

\if :real
  \echo '>>> real=true -> COMMIT'
  COMMIT;
\else
  \echo '>>> real=false -> ROLLBACK (干跑)'
  ROLLBACK;
\endif
