-- create_player_metrics_daily.sql
--
-- Append-only daily snapshot table for the advanced metrics that publish NO
-- historical depth (DARKO DPM / nbarapm RAPM / bball-index LEBRON).
--
-- Why: those three sources only ever expose "right now". We cannot backfill
-- history, so we manufacture it: one row per (date, metric, player) per day.
-- Over months the table becomes a real time series.
--
-- Idempotency: PK (snapshot_date, metric, player_key) means re-running on the
-- same day is an UPSERT, never a duplicate append.
--
-- EPM is deliberately NOT here: dunksandthrees already ships 25 seasons of
-- history in player_epm, so it needs no snapshot accumulation.

CREATE TABLE IF NOT EXISTS public.player_metrics_daily (
    snapshot_date  DATE        NOT NULL,
    metric         TEXT        NOT NULL,   -- 'dpm' | 'rapm' | 'lebron'
    player_key     TEXT        NOT NULL,   -- nba_id as text; fallback = name slug
    source         TEXT,                   -- 'darko.app' | 'nbarapm.com' | 'fanspo'
    nba_id         BIGINT,
    player_name    TEXT,
    team_abbr      TEXT,
    season_label   TEXT,                   -- e.g. '2025-26'
    val            NUMERIC,                -- headline metric
    val_o          NUMERIC,                -- offensive split
    val_d          NUMERIC,                -- defensive split
    extra          JSONB,                  -- everything else, verbatim
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT player_metrics_daily_pkey
        PRIMARY KEY (snapshot_date, metric, player_key),
    CONSTRAINT player_metrics_daily_metric_chk
        CHECK (metric IN ('dpm', 'rapm', 'lebron', 'epm'))
);

-- Time-series lookups: "give me Wembanyama's DPM over time".
CREATE INDEX IF NOT EXISTS idx_pmd_series
    ON public.player_metrics_daily (metric, player_key, snapshot_date);

-- "What did the whole league look like on date X" (join by nba_id).
CREATE INDEX IF NOT EXISTS idx_pmd_nbaid
    ON public.player_metrics_daily (metric, nba_id, snapshot_date);

COMMENT ON TABLE public.player_metrics_daily IS
    'Append-only daily snapshots of now-only metrics (DPM/RAPM/LEBRON). '
    'UPSERT by (snapshot_date, metric, player_key) so same-day reruns are idempotent.';
