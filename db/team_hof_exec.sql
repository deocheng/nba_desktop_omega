-- db/team_hof_exec.sql
-- ============================================================================
-- team_hof / team_executives
-- BR 球队页「名人堂(HoF)」与「高管(executives)」两张新表。
-- 纯新增 schema（全库此前无任何 hof / executives / hall / front / office 相关表）。
-- 数据来源：
--   HoF        : https://www.basketball-reference.com/teams/{abbr}/hof.html
--                （页面为 <div> 文本列表，按赛季小标题切块，非 <table>）
--   executives : https://www.basketball-reference.com/teams/{abbr}/executives.html
--                （页面为干净 <table>，但偶尔藏在 HTML 注释块里）
-- 连接串与口令：复用 common/bridge_constants.PG_DSN（口令来自环境变量 DB_PASSWORD，
--               禁止硬编码）。建表用项目 .venv 的 python 执行本文件或经 __main__ 应用。
-- ============================================================================

-- ---------------------------------------------------------------------------
-- team_hof —— 一粒度 = 一个 (队, 赛季, 球员) 的名人堂映射
--   DET 金数据：23 名去重球员 / 118 条 season_entries，本表即存这 118 行。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_hof (
    id           BIGSERIAL PRIMARY KEY,
    team_abbr    VARCHAR(3)  NOT NULL,        -- 规范 3 字母缩写 (canon_abbr)
    season       VARCHAR(7)  NOT NULL,        -- 赛季, 形如 '2013-14' (YYYY-YY)
    player_name  TEXT        NOT NULL,        -- 名人堂球员名 (原文, 暂不强桥接 dim_players)
    br_slug      TEXT        NULL,           -- BR 球员页 slug (可选, 顺手抓, 留待 name->id 桥接)
    scraped_at   TIMESTAMP   NOT NULL DEFAULT now(),
    UNIQUE (team_abbr, season, player_name)   -- 同 (队,赛季,球员) 视为同一行, upsert 覆盖
);

CREATE INDEX IF NOT EXISTS idx_th_team   ON team_hof (team_abbr);
CREATE INDEX IF NOT EXISTS idx_th_player ON team_hof (player_name);

-- ---------------------------------------------------------------------------
-- team_executives —— 一粒度 = 一个 (队, 任期序号 rk) 的高管 tenure
--   DET 金数据：22 条 tenure（含重复表头行需跳过）。start/end 保留原文 TEXT，
--   不强行转 DATE（混排 '1948' / '1954-03-27' / 'present'）。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_executives (
    id           BIGSERIAL PRIMARY KEY,
    team_abbr    VARCHAR(3)  NOT NULL,
    rk           INTEGER     NOT NULL,        -- 任期序号 (BR 表 Rk 列, 1..N)
    executive    TEXT        NOT NULL,
    start        TEXT        NOT NULL,        -- 保留原文: '1948' / '1954-03-27' / 'present'
    "end"        TEXT        NOT NULL,        -- end 是 SQL 保留字, 必须加双引号
    notes        TEXT        NULL,
    scraped_at   TIMESTAMP   NOT NULL DEFAULT now(),
    UNIQUE (team_abbr, rk)                   -- 同 (队, 序号) 视为同一行, upsert 覆盖
);

CREATE INDEX IF NOT EXISTS idx_te_team ON team_executives (team_abbr);
CREATE INDEX IF NOT EXISTS idx_te_exec ON team_executives (executive);
