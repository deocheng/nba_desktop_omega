-- ═══════════════════════════════════════════════════════════════════════════
-- NBACore Studio v8 — DDL: game_videos table
-- ═══════════════════════════════════════════════════════════════════════════
-- Video Library source registration table.
--
-- One row per (gameid, season) — a single video source per game (v1 single-
-- offset approximation). Written ONLY by video_library_engine/db.py via a
-- dedicated ThreadedConnectionPool (designated writer, v8 §6).
--
-- All reads go through core.db.batch_query (SELECT-only).
-- All writes use parameterized INSERT ... ON CONFLICT DO UPDATE.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS game_videos (
    id                    SERIAL PRIMARY KEY,
    gameid                TEXT        NOT NULL,
    season                INTEGER     NOT NULL,
    source                TEXT        NOT NULL DEFAULT 'other',
    video_url             TEXT,
    local_path            TEXT,
    video_offset_seconds  NUMERIC(10,3) NOT NULL DEFAULT 0.0,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One source per game+season (UPSERT key).
    CONSTRAINT game_videos_gameid_season_key UNIQUE (gameid, season),

    -- source must be one of the allowed values.
    CONSTRAINT game_videos_source_chk
        CHECK (source IN ('youtube', 'local_file', 'cloud_drive', 'other'))
);

-- Helpful index for the LEFT JOIN with dim_games.
CREATE INDEX IF NOT EXISTS idx_game_videos_gameid_season
    ON game_videos (gameid, season);

COMMENT ON TABLE game_videos IS
    'Video Library source registration: one video per game (v1 single-offset).';
COMMENT ON COLUMN game_videos.video_offset_seconds IS
    'Seconds: video t=0 relative to Q1 0:00 (NUMERIC(10,3), default 0).';
