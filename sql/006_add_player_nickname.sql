-- ============================================================================
-- 006_add_player_nickname.sql
-- ----------------------------------------------------------------------------
-- 新增球员「绰号(nickname)」维度。
--
-- 背景（主理人调查结论，已实测确认）:
--   * 全库唯一的 nickname 目前是 box score 里的 *球队* 绰号
--     (player1_team_nickname)，并非球员本人绰号 —— 球员本人绰号此前完全没有存。
--   * `player_bio` 不是表，而是 `dim_players` 的视图（见 nba_schema_only.sql L2140）。
--     因此绰号维度的「单一数据源」只能是 `dim_players.nickname`，
--     `player_bio` 视图只需重建成 SELECT 包含 nickname 即可自动暴露。
--   * BR 球员页 (/players/{letter}/{player_id}.html) 的绰号真实位置是
--     页面底部的 FAQ：`<h3>What are X's nicknames?</h3>` 后跟
--     `<p>{逗号分隔绰号列表} are nicknames for X.</p>`。
--     （经实测，#info 内的 `<span class="nickname">` 在现代/历史球员页均未出现，
--       故抽取器以 FAQ 为主、span 为辅，详见 common/player_nickname.py。）
--
-- 安全约束:
--   * 全部使用 `IF NOT EXISTS` / `CREATE OR REPLACE VIEW`，可重复执行（幂等）。
--   * `ADD COLUMN` 为 PG 在线 DDL（nullable 列不加锁重写），对 5433 在线实例安全。
--   * 不改 awards / play_by_play / headshots 任何逻辑，本次只新增绰号维度。
-- ============================================================================

-- 1) 主表加列（球员本人绰号，与 full_name / pronunciation 并列）
ALTER TABLE public.dim_players
    ADD COLUMN IF NOT EXISTS nickname text;

-- 2) 重建 player_bio 视图，使其暴露 nickname
--    （dim_players 加了列后，旧视图定义不会自动包含新列，必须重建）
DROP VIEW IF EXISTS public.player_bio;
CREATE VIEW public.player_bio AS
 SELECT player_id,
    player_name,
    full_name,
    pronunciation,
    "position",
    shoots,
    height_display,
    height_cm,
    weight_lbs,
    weight_kg,
    birth_date,
    birth_city,
    birth_state_country,
    nationality,
    college,
    high_school,
    recruiting_rank,
    draft_info,
    experience,
    nba_debut,
    source_url,
    scraped_at,
    nickname
   FROM public.dim_players;

-- 3) 必要索引：绰号大多为 NULL，用部分索引 (WHERE nickname IS NOT NULL) 仅索引有值行，
--    支撑「按绰号检索球员」且几乎零写入开销。
CREATE INDEX IF NOT EXISTS idx_dim_players_nickname
    ON public.dim_players (nickname)
    WHERE nickname IS NOT NULL;

-- 4) 注释（可选，便于后续排查）
COMMENT ON COLUMN public.dim_players.nickname IS
    '球员本人绰号（来自 Basketball-Reference 球员页 FAQ；多名时为逗号分隔列表）。';
