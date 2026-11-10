-- ============================================================================
-- resolve_final13_null_salaries.sql
-- 目的: 清零 player_salaries_historical.team_abbr 最后 13 个 NULL
-- 方案 (用户 2026-08-17 选定): 回填 4 行可证实队属 + 删除 9 行幻影记录
-- 可回滚: 执行前先建全量快照 player_salaries_historical_bak_20260817_resolve13
--         删除的 9 行 id 见下方 DELETE; 回填的 4 行见 UPDATE。
-- ============================================================================

-- 0) 全量快照 (回滚基线)
DROP TABLE IF EXISTS player_salaries_historical_bak_20260817_resolve13;
CREATE TABLE player_salaries_historical_bak_20260817_resolve13 AS
SELECT * FROM player_salaries_historical;

-- 1) 回填 4 行 (均有可证实的当季 NBA 队属, 来源 Basketball-Reference / 球队官网核验)
--    Marquinhos Vieira 2007: 真实出场 13 场, New Orleans/Oklahoma City Hornets (NOK)
UPDATE player_salaries_historical SET team_abbr='NOK' WHERE id=2391 AND team_abbr IS NULL;
--    Tiny Gallon 2011: 真实出场 11 场, Milwaukee Bucks (MIL)
UPDATE player_salaries_historical SET team_abbr='MIL' WHERE id=4381 AND team_abbr IS NULL;
--    Robert Vaden 2011: OKC 合同/双向在身 (basketball-database 列 2010-11 NBA OKC), 0 出场
UPDATE player_salaries_historical SET team_abbr='OKC' WHERE id=4428 AND team_abbr IS NULL;
--    Charles Bediako 2024: SAS 双向合同在身 (2023-24), 0 NBA 出场
UPDATE player_salaries_historical SET team_abbr='SAS' WHERE id=11825 AND team_abbr IS NULL;

-- 2) 删除 9 行幻影 (simple_csv 占位, 当季无真实 NBA 队属, 薪资为重复占位数字)
--    Mike Gansey 2007      仅热火夏联签约即裁, 无 NBA 场
--    Brian Zoubek 2011/12/13 2010 签篮网即裁, 仅夏联
--    Tiny Gallon 2012/13    海外/发展联盟, 无 NBA
--    Robert Vaden 2012/13   交易至森林狼即裁/海外波恩
--    Tu Holloway 2013       仅独侠夏联, 土耳其联赛
DELETE FROM player_salaries_historical
WHERE id IN (2404, 4379, 4984, 5669, 4987, 5674, 4916, 5577, 5683);

-- 3) 复核 (应返回 0)
-- SELECT COUNT(*) FROM player_salaries_historical WHERE team_abbr IS NULL OR team_abbr='';
