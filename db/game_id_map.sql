-- db/game_id_map.sql
-- ============================================================================
-- game_id_map —— 跨源比赛身份权威映射表（方案 i 核心）
-- 存储 BR gid <-> nba_api_id <-> ESPN event_id 的键空间解析结果。
-- 表内【不含任何 (x,y) 坐标列】，因此桥接写入绝不触碰坐标铁律。
-- 幂等：UNIQUE(br_gid) + upsert ON CONFLICT(br_gid) DO UPDATE。
-- ============================================================================
CREATE TABLE IF NOT EXISTS game_id_map (
    id              BIGSERIAL PRIMARY KEY,
    br_gid          VARCHAR(20)  NOT NULL,   -- BR game_id, e.g. '202401010BOS'
    nba_api_id      VARCHAR(20),             -- nba_api style, e.g. '0022300001'
    espn_event      VARCHAR(20),             -- ESPN Site API event id
    season          SMALLINT,
    game_date       DATE,
    home_abbr       VARCHAR(3),
    away_abbr       VARCHAR(3),
    home_pts        SMALLINT,
    away_pts        SMALLINT,
    pbp_under_api   BOOLEAN NOT NULL DEFAULT FALSE, -- PBP 存在于 nba_api_id 键下
    pbp_under_br    BOOLEAN NOT NULL DEFAULT FALSE, -- PBP 存在于 br_gid 键下
    espn_have       BOOLEAN NOT NULL DEFAULT FALSE, -- ESPN 盒式/坐标已入库
    matched_at      TIMESTAMP NOT NULL DEFAULT now(),
    match_method    VARCHAR(24),             -- 'dim_games' | 'anchor+espn' | 'espn_only' | 'unmatched'
    UNIQUE (br_gid)
);

CREATE INDEX IF NOT EXISTS idx_gim_api   ON game_id_map (nba_api_id);
CREATE INDEX IF NOT EXISTS idx_gim_espn  ON game_id_map (espn_event);
CREATE INDEX IF NOT EXISTS idx_gim_date  ON game_id_map (game_date);
