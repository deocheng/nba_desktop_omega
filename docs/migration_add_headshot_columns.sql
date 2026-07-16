-- ============================================================================
-- 增量迁移：dim_players 新增头像字段（幂等，可重复执行）
-- 配套文档：docs/ARCH_headshots_incremental.md
-- 执行方式（任选其一）：
--   psql "postgresql://postgres:$DB_PASSWORD@localhost:5433/nba" -f docs/migration_add_headshot_columns.sql
--   或 python -c "import psycopg2,os;c=psycopg2.connect(host='localhost',port=5433,dbname='nba',user='postgres',password=os.environ['DB_PASSWORD']);c.cursor().execute(open('docs/migration_add_headshot_columns.sql').read());c.commit()"
-- 设计决策：headshot_scraped_at 不设 DEFAULT now()，保持 NULL = 未抓过；
--           upsert 时显式写入 now()。这样 resume 语义最干净（NULL 必抓、ok 跳过）。
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'dim_players' AND column_name = 'headshot_path'
    ) THEN
        ALTER TABLE dim_players ADD COLUMN headshot_path text;
        RAISE NOTICE 'added dim_players.headshot_path';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'dim_players' AND column_name = 'headshot_url'
    ) THEN
        ALTER TABLE dim_players ADD COLUMN headshot_url text;
        RAISE NOTICE 'added dim_players.headshot_url';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'dim_players' AND column_name = 'headshot_status'
    ) THEN
        -- 枚举值（应用层约束，不建 CHECK 以保持迁移简单）：
        --   NULL      = 未尝试
        --   'ok'      = 成功落盘
        --   'missing' = BR 球员页本身无 headshot（与 failed 区分）
        --   'failed'  = 抓取/下载失败（可经 --resume 重试）
        ALTER TABLE dim_players ADD COLUMN headshot_status varchar(16);
        RAISE NOTICE 'added dim_players.headshot_status';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'dim_players' AND column_name = 'headshot_scraped_at'
    ) THEN
        ALTER TABLE dim_players ADD COLUMN headshot_scraped_at timestamp without time zone;
        RAISE NOTICE 'added dim_players.headshot_scraped_at';
    END IF;
END
$$;

-- 索引：加速 --resume 的「已 ok 跳过」与覆盖度统计查询
CREATE INDEX IF NOT EXISTS idx_dim_players_headshot_status
    ON dim_players (headshot_status);
