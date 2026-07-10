-- ============================================================================
-- T01 · 建表：联盟级薪资规则常量（按 season 存储，可插拔 per-league）
-- 来源：architecture.md §十 ｜ 执行需加 proxy-unset 前缀
--   env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
--     psql -h localhost -p 5433 -d nba -f sql/001_create_league_salary_rules.sql
-- 纯 DDL 常量，非动态 SQL（v8 §6 受控例外）。
-- ============================================================================
CREATE TABLE IF NOT EXISTS league_salary_rules (
    id                  BIGSERIAL PRIMARY KEY,
    league             VARCHAR(16)  NOT NULL DEFAULT 'NBA',
    season             VARCHAR(8)   NOT NULL,
    salary_cap         BIGINT,
    luxury_tax         BIGINT,
    first_apron        BIGINT,
    second_apron       BIGINT,
    minimum_team_salary BIGINT,
    mle_non_tax        BIGINT,
    mle_tax            BIGINT,
    mle_room           BIGINT,
    freeze_calendar    JSONB,
    source_url         TEXT,
    scraped_at         TIMESTAMPTZ  DEFAULT now(),
    UNIQUE (league, season)
);

-- 规则管理接口（TRADE-10 / T11）按 season 读取/更新时的常用索引
CREATE INDEX IF NOT EXISTS idx_league_salary_rules_season
    ON league_salary_rules (league, season);
