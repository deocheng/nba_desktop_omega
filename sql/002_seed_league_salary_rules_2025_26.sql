-- ============================================================================
-- T01 · 回填：2025-26 官方核实阈值（来源 NBA.com 2025-06-30）
-- 仅 2025-26 有数据（决策②：赛季切换预留，其他季空/禁用）。
-- 执行：
--   env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
--     psql -h localhost -p 5433 -d nba -f sql/002_seed_league_salary_rules_2025_26.sql
-- 纯参数化常量（v8 §6 受控例外，非用户输入拼装）。
-- ============================================================================
INSERT INTO league_salary_rules
  (league, season, salary_cap, luxury_tax, first_apron, second_apron,
   minimum_team_salary, mle_non_tax, mle_tax, mle_room, freeze_calendar, source_url)
VALUES
  ('NBA', '2025-26',
   154647000, 187895000, 195945000, 207824000,
   139182000,
   14104000, 5685000, 8781000,
   '{"moratorium":["2025-07-01","2025-07-06"],"trade_deadline":"2026-02-05","dec15_lock":true}'::jsonb,
   'https://www.nba.com/news/nba-salary-cap-set-2025-26-season')
ON CONFLICT (league, season) DO UPDATE SET
   salary_cap          = EXCLUDED.salary_cap,
   luxury_tax          = EXCLUDED.luxury_tax,
   first_apron         = EXCLUDED.first_apron,
   second_apron        = EXCLUDED.second_apron,
   minimum_team_salary = EXCLUDED.minimum_team_salary,
   mle_non_tax         = EXCLUDED.mle_non_tax,
   mle_tax             = EXCLUDED.mle_tax,
   mle_room            = EXCLUDED.mle_room,
   freeze_calendar     = EXCLUDED.freeze_calendar,
   source_url          = EXCLUDED.source_url,
   scraped_at          = now();
