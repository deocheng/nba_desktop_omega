-- ============================================================================
-- 007_add_player_bio_ext.sql — 球员主数据维度增量（bio_ext）
-- ----------------------------------------------------------------------------
-- 覆盖 7 个 dim_players 缺口 + 1 个归一化荣誉表：
--   * 1:1 主属性（落 dim_players 加列）：aba_debut / died / hof_* /
--     career_length_years / relatives / jersey_numbers / career_honors_text
--   * 1:N 事实（新建 player_career_honors）：生涯荣誉归一化，可索引查询
--
-- 幂等约束：
--   * 加列全部 ADD COLUMN IF NOT EXISTS（全 nullable，在线 DDL 安全）
--   * 建表 / 建索引全部 IF NOT EXISTS
--   * 视图 DROP VIEW + CREATE VIEW（否则新列不暴露）
--
-- 安全约束：
--   * 不改 awards / gamelog / pbp / headshots 任何逻辑
--   * is_hall_of_famer 为普通布尔列（非生成列），由 upsert 维护 =
--     (hof_inducted_year IS NOT NULL)，避免 STORED 生成列表重写
--   * 不重启 5433 PG、不杀 9222 Chrome
--
-- 配套设计：docs/ARCH_player_bio_ext.md §4.1
-- ============================================================================

-- (1) dim_players 加列（player_bio 是视图，新列只能落 dim_players）
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS aba_debut             date;
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS died                date;   -- 离世日期（NULL=在世/未知），仅已故球员 BR 页有 Died: 行
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS hof_inducted_year     integer;
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS hof_as                text;
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS is_hall_of_famer     boolean;
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS career_length_years  integer;
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS relatives            text;
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS jersey_numbers        text[];
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS career_honors_text   text[];
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS bio_ext_scraped_at   timestamp without time zone;

-- (2) 新建归一化荣誉表（与 awards 三表解耦；awards 来自 seasonal 页面）
CREATE TABLE IF NOT EXISTS public.player_career_honors (
    id           bigserial PRIMARY KEY,
    player_id    text NOT NULL REFERENCES public.dim_players(player_id) ON DELETE CASCADE,
    honor_raw    text NOT NULL,          -- 原始文本: "16x All Star" / "1983 NBA Champ" / "Hall of Fame"
    honor_type   text NOT NULL,          -- 归一化枚举(见下)
    honor_count  integer,                -- "16x"→16；无次数→NULL
    honor_year   integer,                -- "1983 NBA Champ"→1983；"1993 HoF"→1993；无→NULL
    honor_detail text,                   -- 补充: HoF 的 "Player"；NBA 75th 的 "Team"
    source_url   text,
    scraped_at   timestamp without time zone DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pch_player ON public.player_career_honors(player_id);
CREATE INDEX IF NOT EXISTS idx_pch_type   ON public.player_career_honors(honor_type);

-- (3) 索引：resume 哨兵 + 名人堂过滤
CREATE INDEX IF NOT EXISTS idx_dp_bio_ext_ts ON public.dim_players(bio_ext_scraped_at);
CREATE INDEX IF NOT EXISTS idx_dp_hof        ON public.dim_players(is_hall_of_famer)
    WHERE is_hall_of_famer = true;

-- (4) 重建 player_bio 视图（含 nickname / headshot_* / 本次新列；SELECT * 同步机制）
DROP VIEW IF EXISTS public.player_bio;
CREATE VIEW public.player_bio AS
 SELECT player_id, player_name, full_name, pronunciation, "position", shoots,
        height_display, height_cm, weight_lbs, weight_kg, birth_date, birth_city,
        birth_state_country, nationality, college, high_school, recruiting_rank,
        draft_info, experience, nba_debut, source_url, scraped_at,
        nickname,                                  -- 来自 006
        headshot_path, headshot_url, headshot_status, headshot_scraped_at, -- 来自 headshots 增量
        aba_debut, died, hof_inducted_year, hof_as, is_hall_of_famer,
        career_length_years, relatives, jersey_numbers, career_honors_text,
        bio_ext_scraped_at
   FROM public.dim_players;

-- (5) 注释（正确拼写：COMMENT ON COLUMN）
COMMENT ON COLUMN public.dim_players.relatives           IS '亲属（BR 球员页 Relatives 行，多名逗号/分号分隔）';
COMMENT ON COLUMN public.dim_players.aba_debut           IS 'ABA 首秀日期（NULL=从未打 ABA）';
COMMENT ON COLUMN public.dim_players.died                IS '离世日期（NULL=在世或未知）；仅已故球员 BR 页有 Died: 行';
COMMENT ON COLUMN public.dim_players.hof_inducted_year   IS '名人堂入选年份（NULL=非名人堂）';
COMMENT ON COLUMN public.dim_players.hof_as              IS '名人堂入选身份（Player/Coach/Contributor）';
COMMENT ON COLUMN public.dim_players.is_hall_of_famer    IS '是否名人堂（由 hof_inducted_year 派生，upsert 维护）';
COMMENT ON COLUMN public.dim_players.career_length_years IS '生涯长度（年），冗余存储 BR 页 Career Length';
COMMENT ON COLUMN public.dim_players.jersey_numbers      IS '生涯球衣号码（去重数组）';
COMMENT ON COLUMN public.dim_players.career_honors_text  IS '生涯荣誉清单（去重数组，player_career_honors 的展示镜像）';
COMMENT ON COLUMN public.dim_players.bio_ext_scraped_at  IS 'bio_ext 回填时间戳（resume 哨兵：NULL=待抓取）';
COMMENT ON TABLE  public.player_career_honors            IS '球员生涯荣誉归一化表（来自 BR 球员页 #bling 荣誉块）';
