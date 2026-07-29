-- player_shot_chart：BR 球员 shot chart 逐球散点（数据源已实测锁定）
--   来源：/players/{slug}/shooting/{year} 主队页 <div class="shot-area"> 内
--         每球一个 <div class="tooltip make|miss" style="top:Xpx;left:Ypx;" tip="...">
--   坐标：BR 500px 半场 SVG。x_px=left(0左→500右)，y_px=top(0远端对手篮→500近端本方篮)
--         x_norm=(left-250)/250∈[-1,1](左负右正,0=中线)；y_norm=top/500∈[0,1]
--   game 关联：dim_games(game_date, home/away_team_abbr) → game_id + season_type
--   season_type 归一：'Regular Season'→'Regular'，'Playoffs'→'Playoffs'
CREATE TABLE IF NOT EXISTS player_shot_chart (
    player_id     text        NOT NULL,
    season         bigint      NOT NULL,
    game_date      date,
    game_id        text,
    season_type    text,
    opponent_abbr  text,
    is_home        boolean,
    period         smallint,
    time_remaining text,
    made           boolean,
    shot_value     smallint,
    dist_ft        smallint,
    x_px           numeric(7,2),
    y_px           numeric(7,2),
    x_norm         numeric(8,4),
    y_norm         numeric(8,4),
    src             text        DEFAULT 'basketball-reference',
    created_at     timestamptz DEFAULT now(),
    CONSTRAINT uq_player_shot_chart UNIQUE
        (player_id, game_date, opponent_abbr, period, time_remaining, x_px, y_px)
);

CREATE INDEX IF NOT EXISTS idx_psc_player ON player_shot_chart(player_id);
CREATE INDEX IF NOT EXISTS idx_psc_game   ON player_shot_chart(game_id);
CREATE INDEX IF NOT EXISTS idx_psc_season ON player_shot_chart(player_id, season);
