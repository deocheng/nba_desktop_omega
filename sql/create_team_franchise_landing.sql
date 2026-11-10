-- franchise 队主页 /teams/{slug}/ 数据（第 18 类页）
-- 来源：BR franchise 落地页三大块
--   1) Team Index（Year-by-Year 战绩表，含 W-L / Finish / Playoffs 季后赛成绩）
--   2) Coaches（带队教练 +  tenure，教练更替即各行边界）
--   3) Playoffs（逐年季后赛明细，opponent + result）
-- 落盘规则同铁律：原始 HTML 原子缓存；本表只存结构化抽取结果。

CREATE TABLE IF NOT EXISTS team_franchise_index (
    team_abbr    text     NOT NULL,
    franchise_id integer,
    season       integer  NOT NULL,   -- "2025-26" -> 2026（赛季结束年）
    lg           text,
    team_name    text,
    w            integer,
    l            integer,
    wl_pct       numeric(5,3),
    finish       text,               -- 如 "1st of Central"
    srs          numeric(6,2),
    playoffs     text,               -- 季后赛成绩文本，如 "Won Finals" / "Lost Conf. Semis"
    source       text     DEFAULT 'basketball-reference',
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (team_abbr, season)
);

CREATE TABLE IF NOT EXISTS team_franchise_coaches (
    team_abbr    text     NOT NULL,
    franchise_id integer,
    coach_name   text     NOT NULL,
    years        text,                -- tenure 文本，如 "2010-2015" 或 "2010-2015, 2017-2018"
    reg_w        integer,
    reg_l        integer,
    reg_wl_pct   numeric(5,3),
    po_w         integer,
    po_l         integer,
    po_wl_pct    numeric(5,3),
    total_w      integer,
    total_l      integer,
    total_wl_pct numeric(5,3),
    source       text     DEFAULT 'basketball-reference',
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (team_abbr, coach_name, years)
);

CREATE TABLE IF NOT EXISTS team_franchise_playoffs (
    team_abbr    text     NOT NULL,
    franchise_id integer,
    season       integer  NOT NULL,
    opponent     text,
    result       text,                -- 如 "Won Finals (4-2) vs ..."
    source       text     DEFAULT 'basketball-reference',
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (team_abbr, season, opponent)
);

COMMENT ON TABLE team_franchise_index IS 'BR franchise 主页 Year-by-Year 战绩表（含季后赛成绩）';
COMMENT ON TABLE team_franchise_coaches IS 'BR franchise 主页 Coaches 表（带队教练 + tenure，教练更替边界）';
COMMENT ON TABLE team_franchise_playoffs IS 'BR franchise 主页 Playoffs 逐年季后赛明细';
