-- ============================================================================
-- T02 · 预处理回填：识别并标记双向合同 (two-way, 决策④)
-- 识别口径（architecture.md §九 默认口径，v1 按此）：
--   1) notes JSONB 含 'two-way' / 'two_way' 关键词
--   OR 2) salary_2025_26 <= 600000 且该队合同数 > 15（两位数名额）
-- 标记后 is_two_way=TRUE 的球员在匹配/税档中按 $0 计（决策④）。
-- 执行：
--   env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
--     psql -h localhost -p 5433 -d nba -f sql/003_backfill_two_way_flag.sql
-- 纯固定常量 SQL（v8 §6 受控例外）。
-- ============================================================================
ALTER TABLE player_contracts
    ADD COLUMN IF NOT EXISTS is_two_way BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE player_contracts
SET is_two_way = TRUE
WHERE season = '2025-26'
  AND is_two_way = FALSE
  AND (
        notes::text ILIKE '%two-way%'
        OR notes::text ILIKE '%two_way%'
        OR (
            salary_2025_26 IS NOT NULL
            AND salary_2025_26 <= 600000
            AND team_abbr IN (
                SELECT team_abbr
                FROM player_contracts
                WHERE season = '2025-26'
                GROUP BY team_abbr
                HAVING count(*) > 15
            )
        )
  );
