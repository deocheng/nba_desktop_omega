-- ============================================================
-- organize_playin_dates.sql
-- 为 Play-In(附加赛) 13 场真实比赛建日期查找表。
-- 日期来源：NBA.com 官方比赛页 + Basketball-Reference box score 页逐场核实
--   (basketball-reference.com/boxscores/202008150POR.html 标题即
--    "Play-In Game: Grizzlies vs Trail Blazers, August 15, 2020")。
-- 非库内字段，纯外部权威核实值，可回滚（DROP TABLE 即可）。
-- 执行前提：Bash/DB 工具恢复后运行。
-- ============================================================
SET max_parallel_workers_per_gather=0;

DROP TABLE IF EXISTS playin_game_dates;
CREATE TABLE playin_game_dates (
    game_id_full TEXT PRIMARY KEY,
    game_date    DATE NOT NULL,
    season       INT  NOT NULL,
    note         TEXT
);

INSERT INTO playin_game_dates (game_id_full, game_date, season, note) VALUES
    ('51900111', '2020-08-15', 2020, 'MEM@POR 泡泡赛季西部8v9单场附加赛'),
    ('52000101', '2021-05-18', 2021, 'BOS@WAS 东部7v8'),
    ('52000111', '2021-05-18', 2021, 'IND@CHO 东部9v10'),
    ('52000121', '2021-05-19', 2021, 'GSW@LAL 西部7v8'),
    ('52000131', '2021-05-19', 2021, 'MEM@SAS 西部9v10'),
    ('52000201', '2021-05-20', 2021, 'WAS@IND 东部败者组'),
    ('52000211', '2021-05-21', 2021, 'GSW@MEM 西部败者组'),
    ('52100101', '2022-04-12', 2022, 'BRK@CLE 东部7v8'),
    ('52100111', '2022-04-13', 2022, 'ATL@CHO 东部9v10'),
    ('52100121', '2022-04-12', 2022, 'LAC@MIN 西部7v8'),
    ('52100131', '2022-04-13', 2022, 'NOP@SAS 西部9v10'),
    ('52100201', '2022-04-15', 2022, 'ATL@CLE 东部败者组'),
    ('52100211', '2022-04-15', 2022, 'LAC@NOP 西部败者组')
;

-- 复核：应 13 行
SELECT COUNT(*) AS playin_games FROM playin_game_dates;
