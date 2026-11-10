-- ============================================================
-- organize_playin_classify.sql
-- 给 player_gamelog 增加 game_type 分类列，把"孤儿行"明确归类，
-- 使 Play-In(附加赛) 成为可识别的第一类数据，不再以 liminal 状态游离。
--
-- 分类口径：
--   play_in    : game_id_full ~ '^5[0-9]{7}$'  (349 行，2020-2022 附加赛)
--   preseason  : banned = TRUE (7722 行，季前赛，已 ban)
--   regular_season / playoffs : 与 dim_games 匹配的行（按 dim_games 的 RS/PO 标志分批回填）
--
-- 安全性：
--   - 先留回滚快照 player_gamelog_bak_gametype_20260817
--   - 加列是元数据操作，不重写表
--   - 小批(play_in/preseason)直接 UPDATE；RS/PO 按赛季分批避免全表大 UPDATE OOM
--   - 全程 SET max_parallel_workers_per_gather=0
-- 执行前提：Bash/DB 工具恢复后运行；运行前先确认 dim_games 的 RS/PO 区分列名。
-- ============================================================
SET max_parallel_workers_per_gather=0;

BEGIN;

-- 0) 回滚快照（执行前务必先建，确保可回退）
DROP TABLE IF EXISTS player_gamelog_bak_gametype_20260817;
CREATE TABLE player_gamelog_bak_gametype_20260817 AS
SELECT id, game_id_full, season, banned FROM player_gamelog;

-- 1) 加分类列（即时元数据操作）
ALTER TABLE player_gamelog ADD COLUMN IF NOT EXISTS game_type TEXT;

-- 2) Play-In：349 行，明确标为 play_in（保留，不 ban）
UPDATE player_gamelog
SET game_type = 'play_in'
WHERE game_id_full ~ '^5[0-9]{7}$';

-- 3) 季前赛：7722 banned 行，标为 preseason（与 play_in 同为孤儿兄弟类，保持分类一致）
UPDATE player_gamelog
SET game_type = 'preseason'
WHERE banned;

-- 4) RS/PO：与 dim_games 匹配的行，按 dim_games 的 RS/PO 标志分批回填。
--    【执行前确认 dim_games 区分列】假设列名为 <RS_PO_FLAG>，取值逻辑：
--      - 若 dim_games.playoffs IS TRUE  -> 'playoffs'
--      - 否则 -> 'regular_season'
--    以下为占位模板，确认列名后替换为实际 CASE（按 season 分批，每批 ~5万行）：
--    UPDATE player_gamelog pg
--    SET game_type = CASE WHEN dg.<RS_PO_FLAG> THEN 'playoffs' ELSE 'regular_season' END
--    FROM dim_games dg
--    WHERE pg.game_id_full = dg.game_id
--      AND pg.season = <SEASON_X>
--      AND pg.game_type IS NULL;
--    （若 dim_games 无显式 RS/PO 标志，则统一标 'league_game' 并在查询时经 dim_games 区分）

COMMIT;

-- 复核
SELECT game_type, COUNT(*) FROM player_gamelog GROUP BY game_type ORDER BY game_type;
SELECT 'playin_banned_should_be_0' AS chk, COUNT(*) FROM player_gamelog WHERE game_type='play_in' AND banned;
