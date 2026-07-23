-- db/player_shooting_404.sql
-- ============================================================================
-- player_shooting_404 —— 已确认失效/损坏的球员 slug 隔离表
--
-- 来源（详见 common/br_player_page.py）：
--   'http_404' : BR 返回 404 页面（Page Not Found），永久失效，不应再爬。
--   'corrupted': player_gamelog 赛季跨度异常（slug 复用/混入），永远抓不到真实页。
--
-- 作用：enumerate_players(priority_gap=True) 的 gap 查询 LEFT JOIN 本表并排除，
--   使缺口数变真实、爬虫不再对失效 slug 死循环空转（此前缺口永久卡在 2,904）。
--   同时 runner 的 get_gap() / coverage_report.sql 也扣除本表，DONE 判定诚实。
--
-- 连接串与口令：host=127.0.0.1 port=5433 dbname=nba user=postgres，
--   口令来自环境变量 PGPASSWORD（禁止硬编码）。建表走项目 .venv python 或经
--   run_player_shooting_backfill.sh 内置 DDL 步骤应用（幂等）。
-- ============================================================================

CREATE TABLE IF NOT EXISTS player_shooting_404 (
    slug       TEXT        PRIMARY KEY,            -- BR 球员页 slug
    first_seen TIMESTAMPTZ NOT NULL DEFAULT now(), -- 首次隔离时间
    note       TEXT        NULL                    -- 'http_404' / 'corrupted'
);

CREATE INDEX IF NOT EXISTS idx_ps404_first_seen ON player_shooting_404 (first_seen);
CREATE INDEX IF NOT EXISTS idx_ps404_note       ON player_shooting_404 (note);
