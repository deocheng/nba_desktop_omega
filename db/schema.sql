-- ============================================================================
-- db/schema.sql — nba 库完整 DDL（**仅结构，不含任何数据行**）
-- ============================================================================
-- 用途：CI 的 test job 用它在一次性 postgres 上还原 schema，
--       让「需要库结构」的测试在 CI 里真跑（而不是一律 skip）。
--       往返验证：psql -v ON_ERROR_STOP=1 -f db/schema.sql → 197 张表，
--       与生产库 information_schema.tables 计数完全一致，零错误，耗时 ~0.3s。
--
-- 生成方式（唯一权威来源 = 生产库结构，非手工维护）：
--   pg_dump -h 127.0.0.1 -p 5433 -U postgres -d nba --           --schema-only --no-owner --no-privileges --no-comments
--
-- 重新生成后必须做的两项核对：
--   1) 表数与生产库一致：
--      psql -h 127.0.0.1 -p 5433 -U postgres -d nba -tAc \
--        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
--   2) 干净库往返还原零错误（见 tools/verify_ci_schema.sh）。
--
-- ⚠️ 本文件只描述结构；数据由生产库/爬虫写入，**严禁**把数据行混入此处
--    （数据文件不入库的仓库铁律：见 .gitignore 的 *.csv / *.parquet 规则）。
-- ⚠️ \restrict / \unrestrict 伪指令已被剥除 —— 那是 PG18.3+ pg_dump 的
--    转储安全特性，老版本 psql 不识别会直接报错，CI 的 postgres 镜像版本
--    不可控，剥除后兼容性最稳。
-- ============================================================================

--
-- PostgreSQL database dump
--


-- Dumped from database version 18.6 (Homebrew)
-- Dumped by pg_dump version 18.6 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: analytics; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA analytics;


--
-- Name: fiba; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA fiba;


--
-- Name: unaccent; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;


--
-- Name: canon_pos(text); Type: FUNCTION; Schema: analytics; Owner: -
--

CREATE FUNCTION analytics.canon_pos(p text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    AS $$
DECLARE lp text;
BEGIN
  lp := lower(coalesce(p, ''));
  IF lp LIKE '%point guard%' OR lp = 'pg' OR lp = 'point' THEN RETURN 'PG';
  ELSIF lp LIKE '%shooting guard%' OR lp = 'sg' OR lp = 'shooting' THEN RETURN 'SG';
  ELSIF lp LIKE '%small forward%' OR lp = 'sf' OR lp = 'small' THEN RETURN 'SF';
  ELSIF lp LIKE '%power forward%' OR lp = 'pf' OR lp = 'power' THEN RETURN 'PF';
  ELSIF lp LIKE '%center%' OR lp = 'centre' OR lp = 'c' THEN RETURN 'C';
  ELSIF lp LIKE '%guard%' THEN RETURN 'G';
  ELSIF lp LIKE '%forward%' THEN RETURN 'F';
  ELSE RETURN 'UNK';
  END IF;
END;
$$;


--
-- Name: ft_to_m(numeric); Type: FUNCTION; Schema: analytics; Owner: -
--

CREATE FUNCTION analytics.ft_to_m(ft numeric) RETURNS numeric
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT round(coalesce(ft, 0) * 0.3048, 2);
$$;


--
-- Name: height_to_cm(text); Type: FUNCTION; Schema: analytics; Owner: -
--

CREATE FUNCTION analytics.height_to_cm(h text) RETURNS numeric
    LANGUAGE plpgsql IMMUTABLE
    AS $_$
DECLARE
  s  text;
  a  text[];
  ft numeric; inc numeric;
BEGIN
  IF h IS NULL THEN RETURN NULL; END IF;
  s := regexp_replace(h, '[^0-9.]', ' ', 'g');   -- 非数字/点 → 空格（连字符/撇号都清掉）
  s := trim(s);
  IF s = '' THEN RETURN NULL; END IF;
  a := regexp_split_to_array(s, '\s+');           -- 按空白拆分（容错多空格）
  a := array(SELECT x FROM unnest(a) x WHERE x <> '');
  IF array_length(a, 1) = 1 THEN
    IF a[1] ~ '^[0-9]+(\.[0-9]+)?$' THEN
      IF a[1]::numeric BETWEEN 100 AND 280 THEN RETURN round(a[1]::numeric, 0);        -- 已是 cm
      ELSIF a[1]::numeric BETWEEN 48 AND 99 THEN RETURN round(a[1]::numeric * 2.54, 1); -- 英寸
      ELSE RETURN NULL;
      END IF;
    END IF;
    RETURN NULL;
  END IF;
  ft  := a[1]::numeric;
  inc := COALESCE(a[2]::numeric, 0);
  RETURN round((ft * 12 + inc) * 2.54, 1);
EXCEPTION WHEN others THEN RETURN NULL;
END;
$_$;


--
-- Name: inches_to_cm(numeric); Type: FUNCTION; Schema: analytics; Owner: -
--

CREATE FUNCTION analytics.inches_to_cm(inc numeric) RETURNS numeric
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT round(coalesce(inc, 0) * 2.54, 1);
$$;


--
-- Name: lbs_to_kg(numeric); Type: FUNCTION; Schema: analytics; Owner: -
--

CREATE FUNCTION analytics.lbs_to_kg(lbs numeric) RETURNS numeric
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT round(coalesce(lbs, 0) * 0.45359237, 1);
$$;


--
-- Name: weight_to_kg_safe(numeric); Type: FUNCTION; Schema: analytics; Owner: -
--

CREATE FUNCTION analytics.weight_to_kg_safe(w numeric, OUT kg numeric, OUT suspect boolean) RETURNS record
    LANGUAGE plpgsql IMMUTABLE
    AS $$
BEGIN
  IF w IS NULL THEN kg := NULL; suspect := false; RETURN; END IF;
  IF w < 114 THEN kg := round(w, 1); suspect := true;        -- lb 列里的 kg 误标
  ELSE            kg := round(w * 0.45359237, 1); suspect := false;
  END IF;
END;
$$;


--
-- Name: compute_clutch_for_season(integer, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.compute_clutch_for_season(p_year integer, p_batch integer DEFAULT 150) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
  v_games text[];
  v_batch text[];
  v_i int;
  v_n int;
BEGIN
  SELECT array_agg(g ORDER BY g) INTO v_games
  FROM (SELECT DISTINCT game_id AS g FROM fct_pbp_shots WHERE season = p_year) s;
  IF v_games IS NULL THEN RETURN 0; END IF;
  v_n := array_length(v_games, 1);
  FOR v_i IN 1 .. v_n BY p_batch LOOP
    v_batch := v_games[v_i : LEAST(v_i + p_batch - 1, v_n)];
    WITH game_teams AS (
      SELECT game_id, min(team) AS team_a, max(team) AS team_b
      FROM fct_pbp_shots WHERE season = p_year AND game_id = ANY(v_batch)
      GROUP BY game_id
    ),
    ordered AS (
      SELECT f.id, f.game_id, f.period, f.qrem, f.team, f.is_make, f.shot_type,
             gt.team_a, gt.team_b,
        CASE WHEN f.shot_type='3pt' THEN 3 WHEN f.shot_type='ft' THEN 1 ELSE 2 END AS pts_if_made,
        row_number() OVER (PARTITION BY f.game_id ORDER BY f.period, f.qrem, f.src_ctid) AS ord
      FROM fct_pbp_shots f JOIN game_teams gt ON gt.game_id = f.game_id
      WHERE f.season = p_year AND f.game_id = ANY(v_batch)
    ),
    margin_run AS (
      SELECT id, game_id, ord, team, is_make, shot_type, period, qrem,
        sum(CASE WHEN team=team_a THEN pts_if_made WHEN team=team_b THEN -pts_if_made ELSE 0 END)
           FILTER (WHERE is_make)
           OVER (PARTITION BY game_id ORDER BY ord ROWS UNBOUNDED PRECEDING) AS mr
      FROM ordered
    ),
    shot_margin AS (
      SELECT id, game_id, period, qrem, shot_type,
        abs(lag(mr) OVER (PARTITION BY game_id ORDER BY ord)) AS margin_before
      FROM margin_run
    ),
    clutch AS (
      SELECT id, ((period=4 AND qrem<=300) OR period>4) AND margin_before<=5 AS is_clutch
      FROM shot_margin
    )
    UPDATE fct_pbp_shots t SET is_clutch = c.is_clutch
    FROM clutch c WHERE t.id = c.id AND t.game_id = ANY(v_batch);
  END LOOP;
  RETURN v_n;
END;
$$;


--
-- Name: norm_name(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.norm_name(text) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $_$
SELECT lower(trim(regexp_replace(
  translate($1,
    'ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝİŞĞŽŒàáâãäåæçèéêëìíîïðñòóôõöøùúûüýışğžœ',
    'AAAAAAACEEEEIIIIDNOOOOOOUUUUYISGZOEaaaaaaaceeeeiiiidnoooooouuuuyisgzo'),
  '\s+(III|II|IV|Jr\.?|Sr\.?)$', '', 'g')))
$_$;


--
-- Name: parse_qrem(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.parse_qrem(clock text) RETURNS smallint
    LANGUAGE plpgsql IMMUTABLE
    AS $_$
DECLARE m int; s int;
BEGIN
  IF clock IS NULL OR clock = '' THEN RETURN NULL; END IF;
  -- ISO 时长: PT<M>M<SS>.00S
  IF clock ~ '^PT[0-9]+M[0-9]+' THEN
    m := substring(clock from 'PT([0-9]+)M')::int;
    s := substring(clock from 'M([0-9]+)')::int;
    RETURN (m*60 + s)::smallint;
  END IF;
  -- M:SS
  IF clock ~ '^[0-9]+:[0-9]+$' THEN
    RETURN (substring(clock from '^([0-9]+)')::int * 60
            + substring(clock from ':([0-9]+)')::int)::smallint;
  END IF;
  -- 十进制秒
  IF clock ~ '^[0-9]+\.[0-9]+$' THEN
    RETURN substring(clock from '^([0-9]+)')::int::smallint;
  END IF;
  RETURN NULL;
END;
$_$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: external_player_status; Type: TABLE; Schema: analytics; Owner: -
--

CREATE TABLE analytics.external_player_status (
    id integer NOT NULL,
    br_player_id text NOT NULL,
    player_name text,
    season integer NOT NULL,
    event_type text NOT NULL,
    category text DEFAULT '非篮球事件'::text NOT NULL,
    reason text,
    source text,
    report_date date,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: external_player_status_id_seq; Type: SEQUENCE; Schema: analytics; Owner: -
--

CREATE SEQUENCE analytics.external_player_status_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: external_player_status_id_seq; Type: SEQUENCE OWNED BY; Schema: analytics; Owner: -
--

ALTER SEQUENCE analytics.external_player_status_id_seq OWNED BY analytics.external_player_status.id;


--
-- Name: fact_player_season_stats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fact_player_season_stats (
    season bigint,
    lg text,
    player text,
    player_id text,
    age double precision,
    team text,
    pos text,
    g bigint,
    gs double precision,
    mp double precision,
    fg bigint,
    fga bigint,
    fg_percent double precision,
    x3p double precision,
    x3pa double precision,
    x3p_percent double precision,
    x2p double precision,
    x2pa double precision,
    x2p_percent double precision,
    e_fg_percent double precision,
    ft bigint,
    fta bigint,
    ft_percent double precision,
    orb double precision,
    drb double precision,
    trb double precision,
    ast bigint,
    stl double precision,
    blk double precision,
    tov double precision,
    pf double precision,
    pts bigint,
    trp_dbl double precision,
    per double precision,
    ts_percent double precision,
    x3p_ar double precision,
    f_tr double precision,
    orb_percent double precision,
    drb_percent double precision,
    trb_percent double precision,
    ast_percent double precision,
    stl_percent double precision,
    blk_percent double precision,
    tov_percent double precision,
    usg_percent double precision,
    ows double precision,
    dws double precision,
    ws double precision,
    ws_48 double precision,
    obpm double precision,
    dbpm double precision,
    bpm double precision,
    vorp double precision,
    fg_per_100_poss double precision,
    fga_per_100_poss double precision,
    x3p_per_100_poss double precision,
    x3pa_per_100_poss double precision,
    x2p_per_100_poss double precision,
    x2pa_per_100_poss double precision,
    ft_per_100_poss double precision,
    fta_per_100_poss double precision,
    orb_per_100_poss double precision,
    drb_per_100_poss double precision,
    trb_per_100_poss double precision,
    ast_per_100_poss double precision,
    stl_per_100_poss double precision,
    blk_per_100_poss double precision,
    tov_per_100_poss double precision,
    pf_per_100_poss double precision,
    pts_per_100_poss double precision,
    o_rtg double precision,
    d_rtg double precision,
    season_type character varying(20),
    id integer NOT NULL,
    weight numeric
);


--
-- Name: player_season_info; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_season_info (
    season bigint,
    lg text,
    player text,
    player_id text,
    age double precision,
    team text,
    pos text,
    experience bigint,
    weight numeric
);


--
-- Name: mv_player_season_trend; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.mv_player_season_trend AS
 SELECT f.player_id,
    f.player,
    f.season,
    f.season_type,
    max(f.age) AS age,
    max(psi.experience) AS experience,
    array_agg(DISTINCT f.team) FILTER (WHERE (f.team <> '2TM'::text)) AS team_list,
    sum(f.g) AS g_total,
    sum(f.mp) AS mp_total,
    sum(f.pts) AS pts_total,
    sum(f.trb) AS trb_total,
    sum(f.ast) AS ast_total,
    sum(f.fg) AS fg_total,
    sum(f.fga) AS fga_total,
        CASE
            WHEN (sum(f.mp) > (0)::double precision) THEN (sum((f.fg_percent * f.mp)) / sum(f.mp))
            ELSE NULL::double precision
        END AS fg_pct_w,
        CASE
            WHEN (sum(f.mp) > (0)::double precision) THEN (sum((f.x3p_percent * f.mp)) / sum(f.mp))
            ELSE NULL::double precision
        END AS fg3_pct_w,
        CASE
            WHEN (sum(f.mp) > (0)::double precision) THEN (sum((f.ft_percent * f.mp)) / sum(f.mp))
            ELSE NULL::double precision
        END AS ft_pct_w,
        CASE
            WHEN (sum(f.mp) > (0)::double precision) THEN (sum((f.ts_percent * f.mp)) / sum(f.mp))
            ELSE NULL::double precision
        END AS ts_pct_w,
        CASE
            WHEN (sum(f.mp) > (0)::double precision) THEN (sum((f.e_fg_percent * f.mp)) / sum(f.mp))
            ELSE NULL::double precision
        END AS efg_pct_w,
    avg(f.ws) AS ws,
    avg(f.vorp) AS vorp,
    avg(f.bpm) AS bpm,
    avg(f.obpm) AS obpm,
    avg(f.dbpm) AS dbpm,
    avg(f.per) AS per,
    avg(f.usg_percent) AS usg_pct_w,
    avg(f.ws_48) AS ws_48,
    (( SELECT max(fact_player_season_stats.season) AS max
           FROM public.fact_player_season_stats) = f.season) AS is_partial_season
   FROM (public.fact_player_season_stats f
     LEFT JOIN public.player_season_info psi ON (((psi.player_id = f.player_id) AND (psi.season = f.season))))
  WHERE (f.season >= 2016)
  GROUP BY f.player_id, f.player, f.season, f.season_type;


--
-- Name: dim_players; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_players (
    player_id character varying(32) NOT NULL,
    player_name text NOT NULL,
    full_name text,
    pronunciation text,
    "position" text,
    shoots text,
    height_display text,
    height_cm integer,
    weight_lbs integer,
    weight_kg integer,
    birth_date date,
    birth_city text,
    birth_state_country text,
    nationality text,
    college text,
    high_school text,
    recruiting_rank text,
    draft_info text,
    experience text,
    nba_debut text,
    source_url text,
    scraped_at timestamp without time zone DEFAULT now(),
    year_from integer,
    year_to integer,
    headshot_path text,
    headshot_url text,
    headshot_status character varying(16),
    headshot_scraped_at timestamp without time zone,
    nickname text,
    aba_debut date,
    died date,
    hof_inducted_year integer,
    hof_as text,
    is_hall_of_famer boolean,
    career_length_years integer,
    relatives text,
    jersey_numbers text[],
    career_honors_text text[],
    bio_ext_scraped_at timestamp without time zone,
    player_page_extras_scraped_at timestamp without time zone
);


--
-- Name: injuries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.injuries (
    id integer NOT NULL,
    report_date date NOT NULL,
    player_name text NOT NULL,
    team_abbr text,
    injury text,
    status text,
    source text DEFAULT 'basketball-reference'::text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    description text,
    body_part character varying(64),
    source_url text,
    scraped_at timestamp without time zone DEFAULT now(),
    crawl_date date DEFAULT CURRENT_DATE
);


--
-- Name: play_by_play; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play (
    id bigint CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
)
PARTITION BY RANGE (season);


--
-- Name: player_gamelog; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog (
    id bigint NOT NULL,
    gameid character varying(10) NOT NULL,
    player character varying(50) NOT NULL,
    team character varying(10),
    season smallint,
    fg smallint DEFAULT 0,
    fga smallint DEFAULT 0,
    fg3 smallint DEFAULT 0,
    fga3 smallint DEFAULT 0,
    ft smallint DEFAULT 0,
    fta smallint DEFAULT 0,
    orb smallint DEFAULT 0,
    drb smallint DEFAULT 0,
    trb smallint DEFAULT 0,
    ast smallint DEFAULT 0,
    stl smallint DEFAULT 0,
    blk smallint DEFAULT 0,
    tov smallint DEFAULT 0,
    pf smallint DEFAULT 0,
    pts smallint DEFAULT 0,
    plus_minus smallint DEFAULT 0,
    fg_pct numeric(5,1) DEFAULT 0,
    ft_pct numeric(5,1) DEFAULT 0,
    fg3_pct numeric(5,1) DEFAULT 0,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    nba_player_id bigint,
    fbpts integer,
    fbptsa integer,
    fbptsm integer,
    pip integer,
    pipa integer,
    pipm integer,
    blka integer,
    tech_fouls integer,
    court_status character varying(10),
    seconds_played integer,
    fgm integer,
    tpm integer,
    tpa integer,
    ftm integer,
    oreb integer,
    dreb integer,
    reb integer,
    team_id bigint,
    team_abbreviation character varying(10),
    player_id character varying(32),
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32),
    weight numeric,
    banned boolean DEFAULT false NOT NULL,
    game_type text
);


--
-- Name: player_id_bridge; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_id_bridge (
    nba_player_id text,
    player_name character varying NOT NULL,
    br_player_id character varying(32) NOT NULL,
    match_strategy character varying(50)
);


--
-- Name: v_data_quality_flags; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_data_quality_flags AS
 SELECT 'player_gamelog'::text AS table_name,
    'player_id'::text AS column_name,
    'null_key'::text AS issue_type,
        CASE
            WHEN (((1.0 * (count(*) FILTER (WHERE (player_gamelog.player_id IS NULL)))::numeric) / (count(*))::numeric) > 0.6) THEN 'CRITICAL'::text
            WHEN (((1.0 * (count(*) FILTER (WHERE (player_gamelog.player_id IS NULL)))::numeric) / (count(*))::numeric) > 0.3) THEN 'WARN'::text
            ELSE 'INFO'::text
        END AS severity,
    round(((1.0 * (count(*) FILTER (WHERE (player_gamelog.player_id IS NULL)))::numeric) / (count(*))::numeric), 3) AS metric_value,
    now() AS detected_at
   FROM public.player_gamelog
UNION ALL
 SELECT 'weight'::text AS table_name,
    'weight'::text AS column_name,
    'unit_mismatch'::text AS issue_type,
    'CRITICAL'::text AS severity,
    round((( SELECT avg(fact_player_season_stats.weight) AS avg
           FROM public.fact_player_season_stats) / ( SELECT avg(dim_players.weight_kg) AS avg
           FROM public.dim_players)), 2) AS metric_value,
    now() AS detected_at
UNION ALL
 SELECT 'player_id_bridge'::text AS table_name,
    'nba_player_id'::text AS column_name,
    'identity_1_to_n'::text AS issue_type,
        CASE
            WHEN (count(*) FILTER (WHERE (player_id_bridge.nba_player_id IS NULL)) > 0) THEN 'CRITICAL'::text
            ELSE 'WARN'::text
        END AS severity,
    count(*) FILTER (WHERE (player_id_bridge.nba_player_id IS NULL)) AS metric_value,
    now() AS detected_at
   FROM public.player_id_bridge
UNION ALL
 SELECT 'play_by_play'::text AS table_name,
    'x'::text AS column_name,
    'coord_coverage'::text AS issue_type,
        CASE
            WHEN (((1.0 * (count(*) FILTER (WHERE (play_by_play.x IS NOT NULL)))::numeric) / (count(*))::numeric) < 0.5) THEN 'WARN'::text
            ELSE 'INFO'::text
        END AS severity,
    round(((1.0 * (count(*) FILTER (WHERE (play_by_play.x IS NOT NULL)))::numeric) / (count(*))::numeric), 3) AS metric_value,
    now() AS detected_at
   FROM public.play_by_play
  GROUP BY play_by_play.source
UNION ALL
 SELECT 'injuries'::text AS table_name,
    'report_date'::text AS column_name,
    'future_date'::text AS issue_type,
        CASE
            WHEN (count(*) FILTER (WHERE (injuries.report_date > CURRENT_DATE)) > 0) THEN 'CRITICAL'::text
            ELSE 'INFO'::text
        END AS severity,
    count(*) FILTER (WHERE (injuries.report_date > CURRENT_DATE)) AS metric_value,
    now() AS detected_at
   FROM public.injuries
UNION ALL
 SELECT 'fact_player_season_stats'::text AS table_name,
    'vorp'::text AS column_name,
    'null_rate'::text AS issue_type,
        CASE
            WHEN (((1.0 * (count(*) FILTER (WHERE (fact_player_season_stats.vorp IS NULL)))::numeric) / (count(*))::numeric) > 0.3) THEN 'WARN'::text
            ELSE 'INFO'::text
        END AS severity,
    round(((1.0 * (count(*) FILTER (WHERE (fact_player_season_stats.vorp IS NULL)))::numeric) / (count(*))::numeric), 3) AS metric_value,
    now() AS detected_at
   FROM public.fact_player_season_stats
  WHERE (fact_player_season_stats.season >= 2016)
UNION ALL
 SELECT 'play_by_play'::text AS table_name,
    'dist'::text AS column_name,
    'physically_impossible'::text AS issue_type,
        CASE
            WHEN (count(*) FILTER (WHERE (play_by_play.dist > 94)) > 0) THEN 'WARN'::text
            ELSE 'INFO'::text
        END AS severity,
    count(*) FILTER (WHERE (play_by_play.dist > 94)) AS metric_value,
    now() AS detected_at
   FROM public.play_by_play;


--
-- Name: player_shooting; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_shooting (
    season bigint,
    lg text,
    player text,
    player_id text,
    age bigint,
    team text,
    pos text,
    g bigint,
    gs bigint,
    mp bigint,
    fg_percent double precision,
    avg_dist_fga double precision,
    percent_fga_from_x2p_range double precision,
    percent_fga_from_x0_3_range double precision,
    percent_fga_from_x3_10_range double precision,
    percent_fga_from_x10_16_range double precision,
    percent_fga_from_x16_3p_range double precision,
    percent_fga_from_x3p_range double precision,
    fg_percent_from_x2p_range double precision,
    fg_percent_from_x0_3_range double precision,
    fg_percent_from_x3_10_range double precision,
    fg_percent_from_x10_16_range double precision,
    fg_percent_from_x16_3p_range double precision,
    fg_percent_from_x3p_range double precision,
    percent_assisted_x2p_fg double precision,
    percent_assisted_x3p_fg double precision,
    percent_dunks_of_fga double precision,
    num_of_dunks bigint,
    percent_corner_3s_of_3pa double precision,
    corner_3_point_percent double precision,
    num_heaves_attempted bigint,
    num_heaves_made bigint,
    season_type character varying(20) DEFAULT 'Regular'::character varying,
    weight numeric
);


--
-- Name: v_dq_weight_units; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_dq_weight_units AS
 SELECT 'fact_player_season_stats'::text AS src,
    fact_player_season_stats.player_id,
    (fact_player_season_stats.season)::text AS season,
    fact_player_season_stats.weight,
    (analytics.weight_to_kg_safe(fact_player_season_stats.weight)).suspect AS suspect_kg_in_lbs
   FROM public.fact_player_season_stats
  WHERE ((fact_player_season_stats.weight IS NOT NULL) AND (analytics.weight_to_kg_safe(fact_player_season_stats.weight)).suspect)
UNION ALL
 SELECT 'player_gamelog'::text AS src,
    (player_gamelog.player_id)::text AS player_id,
    (player_gamelog.season)::text AS season,
    player_gamelog.weight,
    (analytics.weight_to_kg_safe(player_gamelog.weight)).suspect AS suspect_kg_in_lbs
   FROM public.player_gamelog
  WHERE ((player_gamelog.weight IS NOT NULL) AND (analytics.weight_to_kg_safe(player_gamelog.weight)).suspect)
UNION ALL
 SELECT 'player_shooting'::text AS src,
    player_shooting.player_id,
    (player_shooting.season)::text AS season,
    player_shooting.weight,
    (analytics.weight_to_kg_safe(player_shooting.weight)).suspect AS suspect_kg_in_lbs
   FROM public.player_shooting
  WHERE ((player_shooting.weight IS NOT NULL) AND (analytics.weight_to_kg_safe(player_shooting.weight)).suspect);


--
-- Name: v_gamelog_outlier; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_gamelog_outlier AS
 WITH base AS (
         SELECT player_gamelog.player_id,
            player_gamelog.season,
            player_gamelog.gameid,
            unnest(ARRAY['pts'::text, 'trb'::text, 'ast'::text, 'stl'::text, 'blk'::text, 'tov'::text]) AS metric,
            unnest(ARRAY[player_gamelog.pts, player_gamelog.trb, player_gamelog.ast, player_gamelog.stl, player_gamelog.blk, player_gamelog.tov]) AS val
           FROM public.player_gamelog
          WHERE ((player_gamelog.player_id IS NOT NULL) AND (player_gamelog.season >= 2016))
        ), peer AS (
         SELECT base.player_id,
            base.season,
            base.metric,
            avg(base.val) AS pm,
            stddev(base.val) AS ps
           FROM base
          GROUP BY base.player_id, base.season, base.metric
        )
 SELECT b.player_id,
    b.season,
    b.gameid,
    b.metric,
    b.val,
    p.pm,
    p.ps,
    (((b.val)::numeric - p.pm) / NULLIF(p.ps, (0)::numeric)) AS z
   FROM (base b
     JOIN peer p USING (player_id, season, metric))
  WHERE (b.val IS NOT NULL);


--
-- Name: league_salary_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.league_salary_rules (
    id bigint NOT NULL,
    league character varying(16) DEFAULT 'NBA'::character varying NOT NULL,
    season character varying(8) NOT NULL,
    salary_cap bigint,
    luxury_tax bigint,
    first_apron bigint,
    second_apron bigint,
    minimum_team_salary bigint,
    mle_non_tax bigint,
    mle_tax bigint,
    mle_room bigint,
    freeze_calendar jsonb,
    source_url text,
    scraped_at timestamp with time zone DEFAULT now()
);


--
-- Name: player_contracts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_contracts (
    team_abbr character varying(8) NOT NULL,
    season character varying(8) NOT NULL,
    player_id character varying(32) NOT NULL,
    player_name text NOT NULL,
    age integer,
    salary_2025_26 bigint,
    salary_2026_27 bigint,
    salary_2027_28 bigint,
    salary_2028_29 bigint,
    salary_2029_30 bigint,
    salary_2030_31 bigint,
    opt_2025_26 character varying(20),
    opt_2026_27 character varying(20),
    opt_2027_28 character varying(20),
    opt_2028_29 character varying(20),
    opt_2029_30 character varying(20),
    opt_2030_31 character varying(20),
    guaranteed bigint,
    is_partial boolean DEFAULT false,
    notes jsonb,
    source_url text,
    scraped_at timestamp without time zone DEFAULT now() NOT NULL,
    is_two_way boolean DEFAULT false NOT NULL,
    weight numeric
);


--
-- Name: player_epm; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_epm (
    nba_player_id text NOT NULL,
    br_player_id character varying(32),
    player_name text NOT NULL,
    season integer NOT NULL,
    game_dt date,
    team_id bigint,
    team_alias text,
    age integer,
    "position" text,
    epm_off numeric,
    epm_def numeric,
    epm_tot numeric,
    epm_tot_change numeric,
    off_rk integer,
    def_rk integer,
    tot_rk integer,
    n_rapm integer,
    n integer,
    p_pct_start numeric,
    p_t_poss_48 numeric,
    p_mp_48 numeric,
    p_usg numeric,
    p_pts_100 numeric,
    p_tspct numeric,
    p_efg numeric,
    p_ast_100 numeric,
    p_tov_100 numeric,
    p_orb_100 numeric,
    p_drb_100 numeric,
    p_stl_100 numeric,
    p_blk_100 numeric,
    raw jsonb NOT NULL,
    source text DEFAULT 'dunksandthrees.com/epm'::text NOT NULL,
    scraped_at timestamp without time zone DEFAULT now()
);


--
-- Name: player_epm_actual; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_epm_actual (
    nba_player_id text NOT NULL,
    br_player_id character varying(32),
    player_name text NOT NULL,
    season integer NOT NULL,
    seasontype integer DEFAULT 2 NOT NULL,
    game_dt date,
    team_id bigint,
    team_alias text,
    age integer,
    pos_text text,
    gp integer,
    mp numeric,
    mpg numeric,
    epm_off numeric,
    epm_def numeric,
    epm_tot numeric,
    ewins numeric,
    off_rk integer,
    def_rk integer,
    tot_rk integer,
    usg numeric,
    tspct numeric,
    efg numeric,
    fg2pct numeric,
    fg3pct numeric,
    ftpct numeric,
    orbpct numeric,
    drbpct numeric,
    astpct numeric,
    topct numeric,
    stlpct numeric,
    blkpct numeric,
    raw jsonb NOT NULL,
    source text DEFAULT 'dunksandthrees.com/epm/actual'::text,
    scraped_at timestamp without time zone DEFAULT now()
);


--
-- Name: v_player_2025_26_trio; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_2025_26_trio AS
 WITH actual AS (
         SELECT DISTINCT ON (player_epm_actual.br_player_id) player_epm_actual.nba_player_id,
            player_epm_actual.br_player_id,
            player_epm_actual.player_name,
            player_epm_actual.season,
            player_epm_actual.seasontype,
            player_epm_actual.game_dt,
            player_epm_actual.team_id,
            player_epm_actual.team_alias,
            player_epm_actual.age,
            player_epm_actual.pos_text,
            player_epm_actual.gp,
            player_epm_actual.mp,
            player_epm_actual.mpg,
            player_epm_actual.epm_off,
            player_epm_actual.epm_def,
            player_epm_actual.epm_tot,
            player_epm_actual.ewins,
            player_epm_actual.off_rk,
            player_epm_actual.def_rk,
            player_epm_actual.tot_rk,
            player_epm_actual.usg,
            player_epm_actual.tspct,
            player_epm_actual.efg,
            player_epm_actual.fg2pct,
            player_epm_actual.fg3pct,
            player_epm_actual.ftpct,
            player_epm_actual.orbpct,
            player_epm_actual.drbpct,
            player_epm_actual.astpct,
            player_epm_actual.topct,
            player_epm_actual.stlpct,
            player_epm_actual.blkpct,
            player_epm_actual.raw,
            player_epm_actual.source,
            player_epm_actual.scraped_at
           FROM public.player_epm_actual
          WHERE (player_epm_actual.season = 2026)
          ORDER BY player_epm_actual.br_player_id, player_epm_actual.nba_player_id
        ), proj AS (
         SELECT player_epm.br_player_id,
            avg(player_epm.epm_tot) AS epm_tot
           FROM public.player_epm
          WHERE (player_epm.season = 2026)
          GROUP BY player_epm.br_player_id
        ), sal AS (
         SELECT player_contracts.player_id,
            max(player_contracts.salary_2025_26) AS salary_2025_26,
            bool_or(player_contracts.is_two_way) AS is_two_way,
            max(player_contracts.guaranteed) AS guaranteed
           FROM public.player_contracts
          WHERE ((player_contracts.season)::text = '2025-26'::text)
          GROUP BY player_contracts.player_id
        ), cap AS (
         SELECT league_salary_rules.salary_cap,
            league_salary_rules.luxury_tax
           FROM public.league_salary_rules
          WHERE ((league_salary_rules.season)::text = '2025-26'::text)
        )
 SELECT a.br_player_id,
    a.nba_player_id,
    a.player_name,
    a.team_alias,
    a.team_id,
    a.age,
    a.pos_text AS "position",
    a.epm_off,
    a.epm_def,
    a.epm_tot,
    proj.epm_tot AS epm_tot_proj,
    (a.epm_tot - proj.epm_tot) AS epm_delta,
    a.ewins,
    a.off_rk,
    a.def_rk,
    a.tot_rk,
    a.gp,
    a.mp,
    a.mpg,
    sal.salary_2025_26 AS salary,
    sal.is_two_way,
    sal.guaranteed,
    cap.salary_cap,
    cap.luxury_tax,
    (sal.salary_2025_26 IS NOT NULL) AS salary_present,
        CASE
            WHEN ((cap.salary_cap > 0) AND (sal.salary_2025_26 IS NOT NULL)) THEN round(((sal.salary_2025_26)::numeric / (cap.salary_cap)::numeric), 6)
            ELSE NULL::numeric
        END AS salary_cap_share,
        CASE
            WHEN ((cap.salary_cap > 0) AND (sal.salary_2025_26 IS NOT NULL)) THEN round((((sal.salary_2025_26)::numeric / (cap.salary_cap)::numeric) * (100)::numeric), 3)
            ELSE NULL::numeric
        END AS salary_cap_share_pct
   FROM (((actual a
     LEFT JOIN proj ON (((a.br_player_id)::text = (proj.br_player_id)::text)))
     LEFT JOIN sal ON (((a.br_player_id)::text = (sal.player_id)::text)))
     CROSS JOIN cap)
  WHERE (a.season = 2026);


--
-- Name: v_player_aging_curve; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_aging_curve AS
 SELECT age,
    count(DISTINCT player_id) AS n_players,
    round(avg((pts_total / NULLIF(g_total, (0)::numeric))), 2) AS avg_pts_pg,
    round((avg(ts_pct_w))::numeric, 3) AS avg_ts_pct,
    round((avg(ws))::numeric, 2) AS avg_ws,
    round((avg(vorp))::numeric, 2) AS avg_vorp,
    round((avg(usg_pct_w))::numeric, 1) AS avg_usg_pct
   FROM analytics.mv_player_season_trend
  WHERE (((season_type)::text = 'Regular'::text) AND (age IS NOT NULL))
  GROUP BY age
  ORDER BY age;


--
-- Name: v_player_career_arc; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_career_arc AS
 WITH t AS (
         SELECT mv_player_season_trend.player_id,
            mv_player_season_trend.season,
            sum(mv_player_season_trend.pts_total) OVER w AS cum_pts,
            sum(mv_player_season_trend.trb_total) OVER w AS cum_trb,
            sum(mv_player_season_trend.ast_total) OVER w AS cum_ast,
            sum(mv_player_season_trend.ws) OVER w AS cum_ws,
            sum(mv_player_season_trend.g_total) OVER w AS cum_games,
            count(*) OVER w AS seasons_played
           FROM analytics.mv_player_season_trend
          WHERE ((mv_player_season_trend.season_type)::text = 'Regular'::text)
          WINDOW w AS (PARTITION BY mv_player_season_trend.player_id ORDER BY mv_player_season_trend.season)
        )
 SELECT player_id,
    season,
    cum_pts,
    cum_trb,
    cum_ast,
    cum_ws,
    cum_games,
    seasons_played,
        CASE
            WHEN ((cum_pts >= (10000)::numeric) AND (lag(cum_pts) OVER (PARTITION BY player_id ORDER BY season) < (10000)::numeric)) THEN season
            ELSE NULL::bigint
        END AS milestone_10k_pts_season
   FROM t
  ORDER BY player_id, season;


--
-- Name: v_player_cohort_percentiles; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_cohort_percentiles AS
 WITH base AS (
         SELECT f.player_id,
            f.season,
            f.season_type,
            analytics.canon_pos(d."position") AS cpos,
            unnest(ARRAY['pts_pg'::text, 'ts_pct'::text, 'ws'::text, 'vorp'::text, 'bpm'::text, 'usg_pct'::text, 'ast_pct'::text]) AS metric,
            unnest(ARRAY[((f.pts / NULLIF(f.g, 0)))::double precision, f.ts_percent, f.ws, f.vorp, f.bpm, f.usg_percent, f.ast_percent]) AS val
           FROM (public.fact_player_season_stats f
             JOIN public.dim_players d ON (((d.player_id)::text = f.player_id)))
          WHERE ((f.season >= 2016) AND (f.team <> '2TM'::text))
        )
 SELECT player_id,
    season,
    season_type,
    cpos,
    metric,
    val,
    percent_rank() OVER (PARTITION BY cpos, season, season_type ORDER BY val) AS pct
   FROM base
  WHERE (val IS NOT NULL);


--
-- Name: v_player_contribution_split; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_contribution_split AS
 SELECT player_id,
    player,
    season,
    season_type,
    team,
    obpm,
    dbpm,
    (obpm + dbpm) AS bpm,
    ows,
    dws,
    ws,
    ws_48,
    o_rtg,
    d_rtg,
        CASE
            WHEN ((ows + dws) > (0)::double precision) THEN (ows / (ows + dws))
            ELSE NULL::double precision
        END AS off_def_ws_ratio,
        CASE
            WHEN ((obpm + dbpm) <> (0)::double precision) THEN (obpm / (obpm + dbpm))
            ELSE NULL::double precision
        END AS off_def_bpm_ratio
   FROM public.fact_player_season_stats
  WHERE ((season >= 2016) AND (team <> '2TM'::text));


--
-- Name: v_player_injury_risk; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_injury_risk AS
 SELECT player_name,
    count(*) AS injury_count,
    max(report_date) AS last_report_date,
    (CURRENT_DATE - max(report_date)) AS days_since_last,
    count(*) FILTER (WHERE (report_date > CURRENT_DATE)) AS future_dated_count
   FROM public.injuries
  GROUP BY player_name;


--
-- Name: v_player_physical_metric; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_physical_metric AS
 SELECT player_id,
    height_cm,
    round(((height_cm)::numeric / 100.0), 2) AS height_m,
    weight_kg,
    weight_lbs,
    analytics.height_to_cm(height_display) AS height_cm_parsed,
    height_display
   FROM public.dim_players p
  WHERE (player_id IS NOT NULL);


--
-- Name: player_play_by_play; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_play_by_play (
    season bigint,
    lg text,
    player text,
    player_id text,
    age bigint,
    team text,
    pos text,
    g bigint,
    gs bigint,
    mp bigint,
    pg_percent double precision,
    sg_percent double precision,
    sf_percent double precision,
    pf_percent double precision,
    c_percent double precision,
    on_court_plus_minus_per_100_poss double precision,
    net_plus_minus_per_100_poss double precision,
    bad_pass_turnover bigint,
    lost_ball_turnover bigint,
    shooting_foul_committed bigint,
    offensive_foul_committed bigint,
    shooting_foul_drawn bigint,
    offensive_foul_drawn double precision,
    points_generated_by_assists bigint,
    and1 bigint,
    fga_blocked bigint,
    weight numeric
);


--
-- Name: v_player_role_composition; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_role_composition AS
 SELECT season,
    team,
    player,
    player_id,
    pg_percent,
    sg_percent,
    sf_percent,
    pf_percent,
    c_percent,
    on_court_plus_minus_per_100_poss,
    net_plus_minus_per_100_poss
   FROM public.player_play_by_play
  WHERE ((season >= 2016) AND (team <> '2TM'::text));


--
-- Name: player_salaries_historical; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_salaries_historical (
    id integer NOT NULL,
    player_name text NOT NULL,
    salary integer NOT NULL,
    season integer NOT NULL,
    team_abbr character varying(8),
    "position" character varying(8),
    age double precision,
    source character varying(64) DEFAULT 'public_dataset'::character varying,
    imported_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: v_player_salary_anomaly; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_salary_anomaly AS
 WITH reg AS (
         SELECT s_1.season,
            regr_slope(f_1.ws, (s_1.salary)::double precision) AS k,
            regr_intercept(f_1.ws, (s_1.salary)::double precision) AS b
           FROM (public.player_salaries_historical s_1
             JOIN public.fact_player_season_stats f_1 ON (((f_1.player = s_1.player_name) AND (f_1.season = s_1.season) AND (f_1.team = (s_1.team_abbr)::text))))
          WHERE ((f_1.season >= 2016) AND (f_1.team <> '2TM'::text))
          GROUP BY s_1.season
        )
 SELECT f.player_id,
    f.season,
    s.salary,
    f.ws AS actual_ws,
    ((r.k * (s.salary)::double precision) + r.b) AS predicted_ws,
    (f.ws - ((r.k * (s.salary)::double precision) + r.b)) AS residual
   FROM ((public.fact_player_season_stats f
     JOIN public.player_salaries_historical s ON (((s.player_name = f.player) AND (s.season = f.season) AND ((s.team_abbr)::text = f.team))))
     JOIN reg r ON ((r.season = f.season)))
  WHERE ((f.season >= 2016) AND (f.team <> '2TM'::text));


--
-- Name: v_player_salary_value; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_salary_value AS
 SELECT f.player_id,
    f.player,
    f.season,
    f.team,
    s.salary,
    s.source,
    f.ws,
    f.vorp,
        CASE
            WHEN (f.ws > (0)::double precision) THEN ((s.salary)::double precision / f.ws)
            ELSE NULL::double precision
        END AS salary_per_ws,
        CASE
            WHEN (f.vorp <> (0)::double precision) THEN ((s.salary)::double precision / NULLIF(f.vorp, (0)::double precision))
            ELSE NULL::double precision
        END AS salary_per_vorp
   FROM (public.fact_player_season_stats f
     JOIN public.player_salaries_historical s ON (((s.player_name = f.player) AND (s.season = f.season) AND ((s.team_abbr)::text = f.team))))
  WHERE ((f.season >= 2016) AND (f.team <> '2TM'::text));


--
-- Name: v_player_shot_dist_metric; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_shot_dist_metric AS
 SELECT player_id,
    season,
    season_type,
    avg_dist_fga,
    analytics.ft_to_m((avg_dist_fga)::numeric) AS avg_dist_m
   FROM public.player_shooting
  WHERE (avg_dist_fga IS NOT NULL);


--
-- Name: v_player_shot_profile; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_shot_profile AS
 SELECT ps.season,
    ps.season_type,
    ps.team,
    ps.player,
    COALESCE(ps.player_id, (d.player_id)::text) AS player_id,
    ps.g,
    ps.mp,
    ps.avg_dist_fga,
    ps.percent_fga_from_x0_3_range,
    ps.percent_fga_from_x3_10_range,
    ps.percent_fga_from_x10_16_range,
    ps.percent_fga_from_x16_3p_range,
    ps.percent_fga_from_x3p_range,
    ps.fg_percent_from_x0_3_range,
    ps.fg_percent_from_x3_10_range,
    ps.fg_percent_from_x10_16_range,
    ps.fg_percent_from_x16_3p_range,
    ps.fg_percent_from_x3p_range,
    ps.percent_assisted_x2p_fg,
    ps.percent_assisted_x3p_fg,
    ps.percent_dunks_of_fga
   FROM (public.player_shooting ps
     LEFT JOIN public.dim_players d ON ((d.player_name = ps.player)))
  WHERE (ps.season >= 2016);


--
-- Name: v_player_stat_zscores; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_stat_zscores AS
 WITH base AS (
         SELECT f.player_id,
            f.player,
            f.season,
            f.season_type,
            analytics.canon_pos(d."position") AS cpos,
            unnest(ARRAY['pts'::text, 'mp'::text, 'ts_pct'::text, 'vorp'::text, 'ws'::text, 'usg_pct'::text, 'bpm'::text]) AS metric,
            unnest(ARRAY[(f.pts)::double precision, f.mp, f.ts_percent, f.vorp, f.ws, f.usg_percent, f.bpm]) AS val
           FROM (public.fact_player_season_stats f
             JOIN public.dim_players d ON (((d.player_id)::text = f.player_id)))
          WHERE (f.season >= 2016)
        ), peer AS (
         SELECT base.season,
            base.season_type,
            base.cpos,
            base.metric,
            avg(base.val) AS pm,
            stddev(base.val) AS ps
           FROM base
          GROUP BY base.season, base.season_type, base.cpos, base.metric
        )
 SELECT b.player_id,
    b.player,
    b.season,
    b.season_type,
    b.cpos,
    b.metric,
    b.val,
    p.pm AS peer_mean,
    p.ps AS peer_std,
    ((b.val - p.pm) / NULLIF(p.ps, (0)::double precision)) AS z_score
   FROM (base b
     JOIN peer p USING (season, season_type, cpos, metric))
  WHERE (b.val IS NOT NULL);


--
-- Name: v_player_tenure_curve; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_tenure_curve AS
 SELECT experience,
    count(DISTINCT player_id) AS n_players,
    round(avg((pts_total / NULLIF(g_total, (0)::numeric))), 2) AS avg_pts_pg,
    round((avg(ws))::numeric, 2) AS avg_ws,
    round((avg(ts_pct_w))::numeric, 3) AS avg_ts_pct,
    round((avg(usg_pct_w))::numeric, 1) AS avg_usg_pct
   FROM analytics.mv_player_season_trend
  WHERE (((season_type)::text = 'Regular'::text) AND (experience IS NOT NULL))
  GROUP BY experience
  ORDER BY experience;


--
-- Name: v_player_yoy_momentum; Type: VIEW; Schema: analytics; Owner: -
--

CREATE VIEW analytics.v_player_yoy_momentum AS
 WITH base AS (
         SELECT mv_player_season_trend.player_id,
            mv_player_season_trend.season,
            (mv_player_season_trend.pts_total / NULLIF(mv_player_season_trend.g_total, (0)::numeric)) AS pts_pg,
            mv_player_season_trend.ts_pct_w,
            mv_player_season_trend.ws,
            mv_player_season_trend.vorp,
            mv_player_season_trend.bpm,
            mv_player_season_trend.usg_pct_w,
            mv_player_season_trend.per
           FROM analytics.mv_player_season_trend
          WHERE ((mv_player_season_trend.season_type)::text = 'Regular'::text)
        ), unp AS (
         SELECT base.player_id,
            base.season,
            unnest(ARRAY['pts_pg'::text, 'ts_pct'::text, 'ws'::text, 'vorp'::text, 'bpm'::text, 'usg_pct'::text, 'per'::text]) AS metric,
            unnest(ARRAY[(base.pts_pg)::double precision, base.ts_pct_w, base.ws, base.vorp, base.bpm, base.usg_pct_w, base.per]) AS value
           FROM base
        )
 SELECT player_id,
    season,
    metric,
    value,
    lag(value) OVER (PARTITION BY player_id, metric ORDER BY season) AS prev_value,
    (value - lag(value) OVER (PARTITION BY player_id, metric ORDER BY season)) AS delta,
        CASE
            WHEN (lag(value) OVER (PARTITION BY player_id, metric ORDER BY season) <> (0)::double precision) THEN ((value - lag(value) OVER (PARTITION BY player_id, metric ORDER BY season)) / lag(value) OVER (PARTITION BY player_id, metric ORDER BY season))
            ELSE NULL::double precision
        END AS pct_change
   FROM unp
  ORDER BY player_id, metric, season;


--
-- Name: all_star_selections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.all_star_selections (
    player text,
    player_id text,
    team text,
    season bigint,
    lg text,
    replaced boolean,
    weight numeric
);


--
-- Name: analysis_flows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.analysis_flows (
    id integer NOT NULL,
    workspace_id integer NOT NULL,
    name text DEFAULT 'flow'::text NOT NULL,
    definition_json jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: analysis_flows_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.analysis_flows_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: analysis_flows_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.analysis_flows_id_seq OWNED BY public.analysis_flows.id;


--
-- Name: backfill_review; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backfill_review (
    id integer NOT NULL,
    season bigint,
    player text,
    season_type character varying,
    reason text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: backfill_review_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.backfill_review_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: backfill_review_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.backfill_review_id_seq OWNED BY public.backfill_review.id;


--
-- Name: bf_stage_20260804; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bf_stage_20260804 (
    sid bigint,
    season integer,
    game_id text,
    period smallint,
    src_ctid text,
    player_slug text,
    team text,
    is_make boolean,
    shot_type text,
    shot_distance smallint,
    season_type text,
    qrem smallint
);


--
-- Name: coaches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.coaches (
    coach_id character varying(20) NOT NULL,
    coach_name character varying(200) NOT NULL,
    born_date date,
    died_date date,
    birth_city character varying(200),
    birth_state_country character varying(200),
    college character varying(200),
    high_school character varying(500),
    source_url character varying(500),
    scraped_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: coach_bio; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.coach_bio AS
 SELECT coach_id,
    coach_name,
    born_date,
    died_date,
    birth_city,
    birth_state_country,
    college,
    high_school,
    source_url,
    scraped_at
   FROM public.coaches;


--
-- Name: coach_crawl_status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.coach_crawl_status (
    coach_id character varying(20) NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying
);


--
-- Name: coach_stats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.coach_stats (
    id integer NOT NULL,
    coach_id character varying(20) NOT NULL,
    season character varying(20),
    age integer,
    team character varying(10),
    league character varying(10),
    reg_g integer,
    reg_w integer,
    reg_l integer,
    reg_wl_pct numeric(5,3),
    reg_w_over_500 numeric(6,1),
    reg_finish character varying(50),
    playoffs_g integer,
    playoffs_w integer,
    playoffs_l integer,
    playoffs_wl_pct numeric(5,3),
    notes text,
    source_url character varying(500),
    scraped_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: coach_stats_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.coach_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: coach_stats_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.coach_stats_id_seq OWNED BY public.coach_stats.id;


--
-- Name: crawl_failures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.crawl_failures (
    id integer NOT NULL,
    game_id character varying(50) NOT NULL,
    task_type character varying(50) DEFAULT 'fill_game_date'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    resolved boolean DEFAULT false
);


--
-- Name: crawl_failures_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.crawl_failures_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crawl_failures_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.crawl_failures_id_seq OWNED BY public.crawl_failures.id;


--
-- Name: dim_draft_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_draft_history (
    season integer,
    league character varying(8),
    round integer,
    pick_overall integer,
    pick_in_round integer,
    team_abbr character varying(8),
    player_id character varying(32),
    player_name text,
    college text,
    seasons_played integer,
    games integer,
    minutes_played integer,
    total_points integer,
    total_rebounds integer,
    total_assists integer,
    fg_pct numeric(5,3),
    fg3_pct numeric(5,3),
    ft_pct numeric(5,3),
    mp_per_game numeric(6,1),
    pts_per_game numeric(6,1),
    trb_per_game numeric(5,1),
    ast_per_game numeric(5,1),
    ws numeric(8,1),
    ws_per_48 numeric(6,2),
    bpm numeric(6,2),
    vorp numeric(8,1),
    source_url text,
    scraped_at timestamp without time zone,
    player_id_orig character varying,
    weight numeric
);


--
-- Name: dim_franchise; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_franchise (
    franchise_id integer NOT NULL,
    franchise_name text NOT NULL,
    current_abbr text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: dim_franchise_franchise_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dim_franchise_franchise_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dim_franchise_franchise_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dim_franchise_franchise_id_seq OWNED BY public.dim_franchise.franchise_id;


--
-- Name: dim_games; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_games (
    game_id text NOT NULL,
    game_date date,
    season integer,
    season_type text,
    home_team_id text,
    home_team_abbr text,
    home_team_name text,
    home_pts integer,
    home_fg_pct real,
    home_fg3_pct real,
    home_ft_pct real,
    home_ast integer,
    home_reb integer,
    home_oreb integer,
    home_dreb integer,
    home_stl integer,
    home_blk integer,
    home_tov integer,
    home_pf integer,
    home_plus_minus integer,
    home_wl text,
    away_team_id text,
    away_team_abbr text,
    away_team_name text,
    away_pts integer,
    away_fg_pct real,
    away_fg3_pct real,
    away_ft_pct real,
    away_ast integer,
    away_reb integer,
    away_oreb integer,
    away_dreb integer,
    away_stl integer,
    away_blk integer,
    away_tov integer,
    away_pf integer,
    away_plus_minus integer,
    away_wl text,
    game_status text,
    min integer,
    video_available integer,
    boxscore_url text,
    pbp_saved boolean,
    pbp_imported boolean,
    location text,
    series_summary text,
    source text,
    home_fgm integer,
    home_fga integer,
    home_tpm integer,
    home_tpa integer,
    home_ftm integer,
    home_fta integer,
    home_q1 integer,
    home_q2 integer,
    home_q3 integer,
    home_q4 integer,
    home_ot integer,
    home_bpts integer,
    home_fbpts integer,
    home_pip integer,
    home_scp integer,
    home_potov integer,
    home_tmreb integer,
    home_tmtov integer,
    away_fgm integer,
    away_fga integer,
    away_tpm integer,
    away_tpa integer,
    away_ftm integer,
    away_fta integer,
    away_q1 integer,
    away_q2 integer,
    away_q3 integer,
    away_q4 integer,
    away_ot integer,
    away_bpts integer,
    away_fbpts integer,
    away_pip integer,
    away_scp integer,
    away_potov integer,
    away_tmreb integer,
    away_tmtov integer,
    attendance integer,
    arena_name character varying(200),
    officials jsonb,
    home_fg3m integer,
    home_fga3 integer,
    away_fg3m integer,
    away_fga3 integer,
    arena_city character varying(100),
    arena_state character varying(100),
    duration character varying(50),
    api_season integer,
    api_status character varying(50),
    saved_at timestamp without time zone,
    imported_at timestamp without time zone,
    br_crawled_id character varying,
    nba_api_id bigint,
    br_no_boxscore boolean DEFAULT false NOT NULL,
    pbp_no_data boolean DEFAULT false NOT NULL
);


--
-- Name: dim_games_brtruth_1961_1977; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_games_brtruth_1961_1977 (
    game_id text,
    season integer,
    season_type text,
    game_date date,
    br_visitor text,
    br_v_pts integer,
    br_home text,
    br_h_pts integer,
    db_home_abbr text,
    db_away_abbr text,
    old_home_pts integer,
    old_away_pts integer,
    label_ok text,
    mirror text
);


--
-- Name: dim_games_homeawayfix_20260923; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_games_homeawayfix_20260923 (
    game_id text,
    season integer,
    game_date date,
    home_team_abbr text,
    away_team_abbr text,
    old_home_pts integer,
    old_away_pts integer,
    old_home_wl text,
    old_away_wl text,
    espn_true_home character varying(3),
    espn_true_away character varying(3),
    espn_true_home_pts smallint,
    espn_true_away_pts smallint,
    evidence text
);


--
-- Name: dim_games_homeawayfix_bak_20260923; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_games_homeawayfix_bak_20260923 (
    game_id text,
    game_date date,
    season integer,
    season_type text,
    home_team_id text,
    home_team_abbr text,
    home_team_name text,
    home_pts integer,
    home_fg_pct real,
    home_fg3_pct real,
    home_ft_pct real,
    home_ast integer,
    home_reb integer,
    home_oreb integer,
    home_dreb integer,
    home_stl integer,
    home_blk integer,
    home_tov integer,
    home_pf integer,
    home_plus_minus integer,
    home_wl text,
    away_team_id text,
    away_team_abbr text,
    away_team_name text,
    away_pts integer,
    away_fg_pct real,
    away_fg3_pct real,
    away_ft_pct real,
    away_ast integer,
    away_reb integer,
    away_oreb integer,
    away_dreb integer,
    away_stl integer,
    away_blk integer,
    away_tov integer,
    away_pf integer,
    away_plus_minus integer,
    away_wl text,
    game_status text,
    min integer,
    video_available integer,
    boxscore_url text,
    pbp_saved boolean,
    pbp_imported boolean,
    location text,
    series_summary text,
    source text,
    home_fgm integer,
    home_fga integer,
    home_tpm integer,
    home_tpa integer,
    home_ftm integer,
    home_fta integer,
    home_q1 integer,
    home_q2 integer,
    home_q3 integer,
    home_q4 integer,
    home_ot integer,
    home_bpts integer,
    home_fbpts integer,
    home_pip integer,
    home_scp integer,
    home_potov integer,
    home_tmreb integer,
    home_tmtov integer,
    away_fgm integer,
    away_fga integer,
    away_tpm integer,
    away_tpa integer,
    away_ftm integer,
    away_fta integer,
    away_q1 integer,
    away_q2 integer,
    away_q3 integer,
    away_q4 integer,
    away_ot integer,
    away_bpts integer,
    away_fbpts integer,
    away_pip integer,
    away_scp integer,
    away_potov integer,
    away_tmreb integer,
    away_tmtov integer,
    attendance integer,
    arena_name character varying(200),
    officials jsonb,
    home_fg3m integer,
    home_fga3 integer,
    away_fg3m integer,
    away_fga3 integer,
    arena_city character varying(100),
    arena_state character varying(100),
    duration character varying(50),
    api_season integer,
    api_status character varying(50),
    saved_at timestamp without time zone,
    imported_at timestamp without time zone,
    br_crawled_id character varying,
    nba_api_id bigint,
    br_no_boxscore boolean,
    pbp_no_data boolean
);


--
-- Name: dim_games_homeawayfix_v2_20260923; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_games_homeawayfix_v2_20260923 (
    game_id text,
    season integer,
    game_date date,
    home_team_abbr text,
    away_team_abbr text,
    old_home_pts integer,
    old_away_pts integer,
    old_home_wl text,
    old_away_wl text,
    gl_true_home_pts numeric,
    gl_true_away_pts numeric,
    evidence text
);


--
-- Name: dim_games_homeawayfix_v2_bak_20260923; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_games_homeawayfix_v2_bak_20260923 (
    game_id text,
    game_date date,
    season integer,
    season_type text,
    home_team_id text,
    home_team_abbr text,
    home_team_name text,
    home_pts integer,
    home_fg_pct real,
    home_fg3_pct real,
    home_ft_pct real,
    home_ast integer,
    home_reb integer,
    home_oreb integer,
    home_dreb integer,
    home_stl integer,
    home_blk integer,
    home_tov integer,
    home_pf integer,
    home_plus_minus integer,
    home_wl text,
    away_team_id text,
    away_team_abbr text,
    away_team_name text,
    away_pts integer,
    away_fg_pct real,
    away_fg3_pct real,
    away_ft_pct real,
    away_ast integer,
    away_reb integer,
    away_oreb integer,
    away_dreb integer,
    away_stl integer,
    away_blk integer,
    away_tov integer,
    away_pf integer,
    away_plus_minus integer,
    away_wl text,
    game_status text,
    min integer,
    video_available integer,
    boxscore_url text,
    pbp_saved boolean,
    pbp_imported boolean,
    location text,
    series_summary text,
    source text,
    home_fgm integer,
    home_fga integer,
    home_tpm integer,
    home_tpa integer,
    home_ftm integer,
    home_fta integer,
    home_q1 integer,
    home_q2 integer,
    home_q3 integer,
    home_q4 integer,
    home_ot integer,
    home_bpts integer,
    home_fbpts integer,
    home_pip integer,
    home_scp integer,
    home_potov integer,
    home_tmreb integer,
    home_tmtov integer,
    away_fgm integer,
    away_fga integer,
    away_tpm integer,
    away_tpa integer,
    away_ftm integer,
    away_fta integer,
    away_q1 integer,
    away_q2 integer,
    away_q3 integer,
    away_q4 integer,
    away_ot integer,
    away_bpts integer,
    away_fbpts integer,
    away_pip integer,
    away_scp integer,
    away_potov integer,
    away_tmreb integer,
    away_tmtov integer,
    attendance integer,
    arena_name character varying(200),
    officials jsonb,
    home_fg3m integer,
    home_fga3 integer,
    away_fg3m integer,
    away_fga3 integer,
    arena_city character varying(100),
    arena_state character varying(100),
    duration character varying(50),
    api_season integer,
    api_status character varying(50),
    saved_at timestamp without time zone,
    imported_at timestamp without time zone,
    br_crawled_id character varying,
    nba_api_id bigint,
    br_no_boxscore boolean,
    pbp_no_data boolean
);


--
-- Name: dim_games_homeawayfix_v3_bak_20260923; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_games_homeawayfix_v3_bak_20260923 (
    game_id text,
    game_date date,
    season integer,
    season_type text,
    home_team_id text,
    home_team_abbr text,
    home_team_name text,
    home_pts integer,
    home_fg_pct real,
    home_fg3_pct real,
    home_ft_pct real,
    home_ast integer,
    home_reb integer,
    home_oreb integer,
    home_dreb integer,
    home_stl integer,
    home_blk integer,
    home_tov integer,
    home_pf integer,
    home_plus_minus integer,
    home_wl text,
    away_team_id text,
    away_team_abbr text,
    away_team_name text,
    away_pts integer,
    away_fg_pct real,
    away_fg3_pct real,
    away_ft_pct real,
    away_ast integer,
    away_reb integer,
    away_oreb integer,
    away_dreb integer,
    away_stl integer,
    away_blk integer,
    away_tov integer,
    away_pf integer,
    away_plus_minus integer,
    away_wl text,
    game_status text,
    min integer,
    video_available integer,
    boxscore_url text,
    pbp_saved boolean,
    pbp_imported boolean,
    location text,
    series_summary text,
    source text,
    home_fgm integer,
    home_fga integer,
    home_tpm integer,
    home_tpa integer,
    home_ftm integer,
    home_fta integer,
    home_q1 integer,
    home_q2 integer,
    home_q3 integer,
    home_q4 integer,
    home_ot integer,
    home_bpts integer,
    home_fbpts integer,
    home_pip integer,
    home_scp integer,
    home_potov integer,
    home_tmreb integer,
    home_tmtov integer,
    away_fgm integer,
    away_fga integer,
    away_tpm integer,
    away_tpa integer,
    away_ftm integer,
    away_fta integer,
    away_q1 integer,
    away_q2 integer,
    away_q3 integer,
    away_q4 integer,
    away_ot integer,
    away_bpts integer,
    away_fbpts integer,
    away_pip integer,
    away_scp integer,
    away_potov integer,
    away_tmreb integer,
    away_tmtov integer,
    attendance integer,
    arena_name character varying(200),
    officials jsonb,
    home_fg3m integer,
    home_fga3 integer,
    away_fg3m integer,
    away_fga3 integer,
    arena_city character varying(100),
    arena_state character varying(100),
    duration character varying(50),
    api_season integer,
    api_status character varying(50),
    saved_at timestamp without time zone,
    imported_at timestamp without time zone,
    br_crawled_id character varying,
    nba_api_id bigint,
    br_no_boxscore boolean,
    pbp_no_data boolean
);


--
-- Name: dim_games_teamnamefix_bak_20260924; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_games_teamnamefix_bak_20260924 (
    game_id text,
    game_date date,
    season integer,
    season_type text,
    home_team_id text,
    home_team_abbr text,
    home_team_name text,
    home_pts integer,
    home_fg_pct real,
    home_fg3_pct real,
    home_ft_pct real,
    home_ast integer,
    home_reb integer,
    home_oreb integer,
    home_dreb integer,
    home_stl integer,
    home_blk integer,
    home_tov integer,
    home_pf integer,
    home_plus_minus integer,
    home_wl text,
    away_team_id text,
    away_team_abbr text,
    away_team_name text,
    away_pts integer,
    away_fg_pct real,
    away_fg3_pct real,
    away_ft_pct real,
    away_ast integer,
    away_reb integer,
    away_oreb integer,
    away_dreb integer,
    away_stl integer,
    away_blk integer,
    away_tov integer,
    away_pf integer,
    away_plus_minus integer,
    away_wl text,
    game_status text,
    min integer,
    video_available integer,
    boxscore_url text,
    pbp_saved boolean,
    pbp_imported boolean,
    location text,
    series_summary text,
    source text,
    home_fgm integer,
    home_fga integer,
    home_tpm integer,
    home_tpa integer,
    home_ftm integer,
    home_fta integer,
    home_q1 integer,
    home_q2 integer,
    home_q3 integer,
    home_q4 integer,
    home_ot integer,
    home_bpts integer,
    home_fbpts integer,
    home_pip integer,
    home_scp integer,
    home_potov integer,
    home_tmreb integer,
    home_tmtov integer,
    away_fgm integer,
    away_fga integer,
    away_tpm integer,
    away_tpa integer,
    away_ftm integer,
    away_fta integer,
    away_q1 integer,
    away_q2 integer,
    away_q3 integer,
    away_q4 integer,
    away_ot integer,
    away_bpts integer,
    away_fbpts integer,
    away_pip integer,
    away_scp integer,
    away_potov integer,
    away_tmreb integer,
    away_tmtov integer,
    attendance integer,
    arena_name character varying(200),
    officials jsonb,
    home_fg3m integer,
    home_fga3 integer,
    away_fg3m integer,
    away_fga3 integer,
    arena_city character varying(100),
    arena_state character varying(100),
    duration character varying(50),
    api_season integer,
    api_status character varying(50),
    saved_at timestamp without time zone,
    imported_at timestamp without time zone,
    br_crawled_id character varying,
    nba_api_id bigint,
    br_no_boxscore boolean,
    pbp_no_data boolean
);


--
-- Name: dim_teams; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_teams (
    id integer NOT NULL,
    team_abbr character varying(10) NOT NULL,
    current_code character varying(10) NOT NULL,
    team_name character varying(50) NOT NULL,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: draft_combine; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.draft_combine (
    id integer NOT NULL,
    season integer NOT NULL,
    nba_player_id integer,
    player_name text NOT NULL,
    "position" character varying(5),
    height_wo_shoes_cm integer,
    height_wo_shoes_display text,
    height_w_shoes_cm integer,
    height_w_shoes_display text,
    weight_lbs numeric,
    wingspan_cm numeric,
    standing_reach_cm numeric,
    body_fat_pct numeric,
    standing_vertical_leap numeric,
    max_vertical_leap numeric,
    lane_agility_time numeric,
    three_quarter_sprint numeric,
    bench_press integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: draft_combine_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.draft_combine_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: draft_combine_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.draft_combine_id_seq OWNED BY public.draft_combine.id;


--
-- Name: draft_pick_corrections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.draft_pick_corrections (
    wrong_id text,
    correct_id text,
    status text,
    page_name text,
    evidence text,
    confidence real,
    verified_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: draft_pick_history; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.draft_pick_history AS
 SELECT season,
    league AS lg,
    round,
    pick_overall AS overall_pick,
    team_abbr AS tm,
    player_id,
    player_name AS player,
    college
   FROM public.dim_draft_history;


--
-- Name: draft_picks; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.draft_picks AS
 SELECT season,
    league,
    round,
    pick_overall,
    pick_in_round,
    team_abbr,
    player_id,
    player_name,
    college,
    seasons_played,
    games,
    minutes_played,
    total_points,
    total_rebounds,
    total_assists,
    fg_pct,
    fg3_pct,
    ft_pct,
    mp_per_game,
    pts_per_game,
    trb_per_game,
    ast_per_game,
    ws,
    ws_per_48,
    bpm,
    vorp,
    source_url,
    scraped_at
   FROM public.dim_draft_history;


--
-- Name: draft_summary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.draft_summary (
    season integer NOT NULL,
    league character varying(8) DEFAULT 'NBA'::character varying NOT NULL,
    draft_date date,
    location text,
    total_picks integer,
    nba_players integer,
    first_pick_name text,
    first_pick_id character varying(32),
    first_pick_ws numeric(6,1),
    most_ws_players text,
    all_stars_count integer,
    all_stars_list text,
    source_url text,
    scraped_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: end_of_season_teams; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.end_of_season_teams (
    season bigint,
    lg text,
    type text,
    number_tm text,
    player text,
    player_id text,
    "position" text,
    age real,
    pts_max real,
    pts_won real,
    share real,
    x1st_tm text,
    x2nd_tm text,
    x3rd_tm text,
    weight numeric
);


--
-- Name: espn_boxscore; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.espn_boxscore (
    id bigint NOT NULL,
    espn_event character varying(20) NOT NULL,
    br_gid character varying(20),
    nba_api_id character varying(20),
    game_date date,
    season smallint,
    season_type character varying(24),
    home_abbr character varying(3),
    away_abbr character varying(3),
    home_pts smallint,
    away_pts smallint,
    home_team_box jsonb,
    away_team_box jsonb,
    player_boxes jsonb,
    shot_coords jsonb,
    raw_json_path text,
    archived_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: espn_boxscore_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.espn_boxscore_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: espn_boxscore_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.espn_boxscore_id_seq OWNED BY public.espn_boxscore.id;


--
-- Name: fact_player_season_stats_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fact_player_season_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fact_player_season_stats_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fact_player_season_stats_id_seq OWNED BY public.fact_player_season_stats.id;


--
-- Name: fact_team_season_stats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fact_team_season_stats (
    season bigint,
    lg text,
    team text,
    abbreviation text,
    playoffs boolean,
    g double precision,
    mp double precision,
    fg double precision,
    fga double precision,
    fg_percent double precision,
    x3p double precision,
    x3pa double precision,
    x3p_percent double precision,
    x2p double precision,
    x2pa double precision,
    x2p_percent double precision,
    ft double precision,
    fta double precision,
    ft_percent double precision,
    orb double precision,
    drb double precision,
    trb double precision,
    ast double precision,
    stl double precision,
    blk double precision,
    tov double precision,
    pf double precision,
    pts double precision,
    opp_fg real,
    opp_fga real,
    opp_fg_percent real,
    opp_x3p real,
    opp_x3pa real,
    opp_x3p_percent real,
    opp_x2p real,
    opp_x2pa real,
    opp_x2p_percent real,
    opp_ft real,
    opp_fta real,
    opp_ft_percent real,
    opp_orb real,
    opp_drb real,
    opp_trb real,
    opp_ast real,
    opp_stl real,
    opp_blk real,
    opp_tov real,
    opp_pf real,
    opp_pts real
);


--
-- Name: fct_pbp_shots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fct_pbp_shots (
    id bigint NOT NULL,
    season integer NOT NULL,
    game_id text NOT NULL,
    period smallint NOT NULL,
    src_ctid text,
    player_slug text,
    team text,
    is_make boolean,
    shot_type text,
    qrem smallint,
    is_eop boolean,
    is_clutch boolean,
    shot_distance smallint,
    season_type text
);


--
-- Name: fct_pbp_shots_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fct_pbp_shots_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fct_pbp_shots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fct_pbp_shots_id_seq OWNED BY public.fct_pbp_shots.id;


--
-- Name: game_id_map; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.game_id_map (
    id bigint NOT NULL,
    br_gid character varying(20) NOT NULL,
    nba_api_id character varying(20),
    espn_event character varying(20),
    season smallint,
    game_date date,
    home_abbr character varying(3),
    away_abbr character varying(3),
    home_pts smallint,
    away_pts smallint,
    pbp_under_api boolean DEFAULT false NOT NULL,
    pbp_under_br boolean DEFAULT false NOT NULL,
    espn_have boolean DEFAULT false NOT NULL,
    matched_at timestamp without time zone DEFAULT now() NOT NULL,
    match_method character varying(24)
);


--
-- Name: game_id_map_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.game_id_map_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: game_id_map_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.game_id_map_id_seq OWNED BY public.game_id_map.id;


--
-- Name: game_id_map_allstar; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.game_id_map_allstar (
    id bigint DEFAULT nextval('public.game_id_map_id_seq'::regclass) CONSTRAINT game_id_map_id_not_null NOT NULL,
    br_gid character varying(20) CONSTRAINT game_id_map_br_gid_not_null NOT NULL,
    nba_api_id character varying(20),
    espn_event character varying(20),
    season smallint,
    game_date date,
    home_abbr character varying(3),
    away_abbr character varying(3),
    home_pts smallint,
    away_pts smallint,
    pbp_under_api boolean DEFAULT false CONSTRAINT game_id_map_pbp_under_api_not_null NOT NULL,
    pbp_under_br boolean DEFAULT false CONSTRAINT game_id_map_pbp_under_br_not_null NOT NULL,
    espn_have boolean DEFAULT false CONSTRAINT game_id_map_espn_have_not_null NOT NULL,
    matched_at timestamp without time zone DEFAULT now() CONSTRAINT game_id_map_matched_at_not_null NOT NULL,
    match_method character varying(24),
    extracted_at timestamp with time zone DEFAULT now(),
    extract_reason text DEFAULT 'All-Star 不属于球队/个人历史数据，单独建表'::text
);


--
-- Name: game_id_mapping; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.game_id_mapping AS
 SELECT row_number() OVER () AS id,
    br_crawled_id AS crawled_id,
    nba_api_id AS nba_id,
    season,
    home_pts AS home_score,
    away_pts AS visitor_score,
    saved_at AS created_at,
    game_date
   FROM public.dim_games
  WHERE (br_crawled_id IS NOT NULL);


--
-- Name: game_metadata; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.game_metadata AS
 SELECT game_id,
    season AS season_end,
    away_team_name AS visitor_team,
    home_team_name AS home_team,
    away_pts AS visitor_score,
    home_pts AS home_score,
    game_date,
    boxscore_url,
    pbp_saved,
    pbp_imported,
    saved_at,
    imported_at,
    NULL::timestamp without time zone AS created_at,
    location,
    series_summary,
    game_id AS nba_gameid,
    arena_name,
    arena_city,
    arena_state,
    attendance,
    officials,
    duration,
    away_q1,
    away_q2,
    away_q3,
    away_q4,
    away_ot,
    home_q1,
    home_q2,
    home_q3,
    home_q4,
    home_ot,
    api_season,
    api_status
   FROM public.dim_games g;


--
-- Name: games; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.games AS
 SELECT game_id,
    game_date,
    season,
    season_type,
    home_team_id,
    home_team_abbr,
    home_team_name,
    home_pts,
    home_fg_pct,
    home_fg3_pct,
    home_ft_pct,
    home_ast,
    home_reb,
    home_oreb,
    home_dreb,
    home_stl,
    home_blk,
    home_tov,
    home_pf,
    home_plus_minus,
    home_wl,
    away_team_id,
    away_team_abbr,
    away_team_name,
    away_pts,
    away_fg_pct,
    away_fg3_pct,
    away_ft_pct,
    away_ast,
    away_reb,
    away_oreb,
    away_dreb,
    away_stl,
    away_blk,
    away_tov,
    away_pf,
    away_plus_minus,
    away_wl,
    game_status,
    min,
    video_available,
    boxscore_url,
    pbp_saved,
    pbp_imported,
    location,
    series_summary,
    source,
    home_fgm,
    home_fga,
    home_tpm,
    home_tpa,
    home_ftm,
    home_fta,
    home_q1,
    home_q2,
    home_q3,
    home_q4,
    home_ot,
    home_bpts,
    home_fbpts,
    home_pip,
    home_scp,
    home_potov,
    home_tmreb,
    home_tmtov,
    away_fgm,
    away_fga,
    away_tpm,
    away_tpa,
    away_ftm,
    away_fta,
    away_q1,
    away_q2,
    away_q3,
    away_q4,
    away_ot,
    away_bpts,
    away_fbpts,
    away_pip,
    away_scp,
    away_potov,
    away_tmreb,
    away_tmtov,
    attendance,
    arena_name,
    officials,
    home_fg3m,
    home_fga3,
    away_fg3m,
    away_fga3,
    arena_city,
    arena_state,
    duration,
    api_season,
    api_status,
    saved_at,
    imported_at,
    br_crawled_id,
    nba_api_id
   FROM public.dim_games;


--
-- Name: good_name_map; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.good_name_map (
    nn text,
    team character varying(10),
    sy integer,
    br_player_id character varying(32)
);


--
-- Name: homeaway_fix_map; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.homeaway_fix_map (
    old_game_id text,
    new_game_id text,
    season integer,
    action text
);


--
-- Name: homeaway_fix_map2; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.homeaway_fix_map2 (
    old_game_id text,
    new_game_id text,
    season integer,
    action text
);


--
-- Name: injuries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.injuries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: injuries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.injuries_id_seq OWNED BY public.injuries.id;


--
-- Name: league_averages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.league_averages (
    season integer,
    lg text,
    team text,
    abbreviation text,
    playoffs text,
    g real,
    mp real,
    fg real,
    fga real,
    fg_percent real,
    x3p real,
    x3pa real,
    x3p_percent real,
    x2p real,
    x2pa real,
    x2p_percent real,
    ft real,
    fta real,
    ft_percent real,
    orb real,
    drb real,
    trb real,
    ast real,
    stl real,
    blk real,
    tov real,
    pf real,
    pts real,
    opp_fg real,
    opp_fga real,
    opp_fg_percent real,
    opp_x3p real,
    opp_x3pa real,
    opp_x3p_percent real,
    opp_x2p real,
    opp_x2pa real,
    opp_x2p_percent real,
    opp_ft real,
    opp_fta real,
    opp_ft_percent real,
    opp_orb real,
    opp_drb real,
    opp_trb real,
    opp_ast real,
    opp_stl real,
    opp_blk real,
    opp_tov real,
    opp_pf real,
    opp_pts real,
    metric_type text
);


--
-- Name: league_salary_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.league_salary_rules_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: league_salary_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.league_salary_rules_id_seq OWNED BY public.league_salary_rules.id;


--
-- Name: meta_data_verification; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.meta_data_verification (
    id integer NOT NULL,
    dataset text NOT NULL,
    category text,
    status text NOT NULL,
    coverage text,
    method text,
    verified_at timestamp without time zone DEFAULT now(),
    note text
);


--
-- Name: meta_data_verification_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.meta_data_verification_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: meta_data_verification_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.meta_data_verification_id_seq OWNED BY public.meta_data_verification.id;


--
-- Name: pbp_g5_raw; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.pbp_g5_raw AS
 SELECT NULL::integer AS id,
    NULL::text AS gameid,
    NULL::integer AS row_num,
    NULL::text AS "time",
    NULL::text AS away_action,
    NULL::text AS score,
    NULL::text AS home_action
  WHERE false;


--
-- Name: pbp_parse_issues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pbp_parse_issues (
    id bigint NOT NULL,
    gameid text,
    br_gid text,
    eventnum integer,
    issue_type text,
    raw_text text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: pbp_parse_issues_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pbp_parse_issues_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pbp_parse_issues_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pbp_parse_issues_id_seq OWNED BY public.pbp_parse_issues.id;


--
-- Name: pbp_semantic; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pbp_semantic (
    id bigint NOT NULL,
    gameid text,
    eventnum integer,
    actor text,
    actor_team text,
    action text,
    action_detail text,
    outcome text,
    points integer,
    raw_description text,
    parsed_at timestamp with time zone DEFAULT now()
);


--
-- Name: pbp_semantic_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pbp_semantic_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pbp_semantic_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pbp_semantic_id_seq OWNED BY public.pbp_semantic.id;


--
-- Name: play_by_play_api; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.play_by_play_api AS
 SELECT lpad((gameid)::text, 10, '0'::text) AS game_id,
    eventnum,
    period,
    pctimestring,
    eventmsgtype,
    eventmsgactiontype,
    homedescription,
    visitordescription,
    neutraldescription,
    player1_id,
    player1_name,
    player1_team_id,
    player1_team_abbreviation,
    player2_id,
    player2_name,
    player2_team_id,
    player2_team_abbreviation,
    player3_id,
    player3_name,
    player3_team_id,
    player3_team_abbreviation,
    NULL::text AS wctimestring,
    NULL::text AS score,
    NULL::text AS scoremargin,
    NULL::integer AS person1type,
    NULL::text AS player1_team_city,
    NULL::text AS player1_team_nickname,
    NULL::integer AS person2type,
    NULL::text AS player2_team_city,
    NULL::text AS player2_team_nickname,
    NULL::integer AS person3type,
    NULL::text AS player3_team_city,
    NULL::text AS player3_team_nickname,
    NULL::integer AS video_available_flag,
    gameid AS gameid_short
   FROM public.play_by_play
  WHERE ((source)::text = 'nba_api'::text);


--
-- Name: play_by_play_new_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.play_by_play_new_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: play_by_play_new_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.play_by_play_new_id_seq OWNED BY public.play_by_play.id;


--
-- Name: play_by_play_p_1997; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_1997 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_1998; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_1998 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_1999; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_1999 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2000; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2000 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2001; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2001 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2002; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2002 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2003; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2003 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2004; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2004 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2005; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2005 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2006; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2006 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2007; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2007 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2008; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2008 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2009; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2009 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2010; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2010 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2011; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2011 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2012; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2012 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2013; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2013 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2014; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2014 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2015; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2015 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2016; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2016 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2017; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2017 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2018; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2018 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2019; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2019 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2020; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2020 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2021; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2021 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2022; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2022 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2023; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2023 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2024; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2024 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2025; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2025 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2026; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2026 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_2027; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_2027 (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: play_by_play_p_default; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_p_default (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) CONSTRAINT play_by_play_new_id_not_null NOT NULL,
    gameid character varying CONSTRAINT play_by_play_new_gameid_not_null NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying,
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying,
    playerid character varying,
    player character varying,
    event_type character varying,
    subtype character varying,
    result character varying,
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying,
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying,
    scorevisitor character varying,
    scoremargin character varying,
    pctimestring character varying,
    player1_id character varying,
    player1_name character varying,
    player1_team_id character varying,
    player1_team_abbreviation character varying,
    player2_id character varying,
    player2_name character varying,
    player2_team_id character varying,
    player2_team_abbreviation character varying,
    player3_id character varying,
    player3_name character varying,
    player3_team_id character varying,
    player3_team_abbreviation character varying,
    source character varying DEFAULT 'br_crawler'::character varying,
    br_player_id character varying,
    action_verb character varying
);


--
-- Name: player_adjusted_shooting; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_adjusted_shooting (
    player_id text NOT NULL,
    season_type text NOT NULL,
    season_end integer NOT NULL,
    season_text character varying(9),
    age integer,
    team_abbr character varying(64),
    lg character varying(4),
    pos character varying(8),
    games integer,
    games_started integer,
    mp integer,
    fg_pct numeric(5,3),
    fg2_pct numeric(5,3),
    fg3_pct numeric(5,3),
    efg_pct numeric(5,3),
    ft_pct numeric(5,3),
    ts_pct numeric(5,3),
    fta_per_fga_pct numeric(5,3),
    fg3a_per_fga_pct numeric(5,3),
    adj_fg_pct numeric(6,2),
    adj_fg2_pct numeric(6,2),
    adj_fg3_pct numeric(6,2),
    adj_efg_pct numeric(6,2),
    adj_ft_pct numeric(6,2),
    adj_ts_pct numeric(6,2),
    adj_fta_per_fga_pct numeric(6,2),
    adj_fg3a_per_fga_pct numeric(6,2),
    fg_pts_added numeric(7,2),
    ts_pts_added numeric(7,2),
    awards text
);


--
-- Name: player_advanced; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.player_advanced AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    mp,
    per,
    ts_percent,
    x3p_ar,
    f_tr,
    orb_percent,
    drb_percent,
    trb_percent,
    ast_percent,
    stl_percent,
    blk_percent,
    tov_percent,
    usg_percent,
    ows,
    dws,
    ws,
    ws_48,
    obpm,
    dbpm,
    bpm,
    vorp,
    season_type
   FROM public.fact_player_season_stats
  WHERE (per IS NOT NULL);


--
-- Name: player_all_star_games; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_all_star_games (
    player_id text NOT NULL,
    season_end integer NOT NULL,
    season_text character varying(9) NOT NULL,
    age integer,
    team_id character varying(4),
    lg_id character varying(4),
    pos character varying(8),
    g integer,
    gs integer,
    mp character varying(12),
    fg integer,
    fga integer,
    fg_pct numeric(5,3),
    fg3 integer,
    fg3a integer,
    fg3_pct numeric(5,3),
    ft integer,
    fta integer,
    ft_pct numeric(5,3),
    orb integer,
    drb integer,
    trb integer,
    ast integer,
    stl integer,
    blk integer,
    tov integer,
    pf integer,
    pts integer
);


--
-- Name: player_award_shares; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_award_shares (
    season bigint,
    award text,
    player text,
    player_id text,
    age bigint,
    first double precision,
    pts_won double precision,
    pts_max double precision,
    share double precision,
    winner boolean,
    weight numeric
);


--
-- Name: player_bio; Type: VIEW; Schema: public; Owner: -
--

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
    nickname,
    headshot_path,
    headshot_url,
    headshot_status,
    headshot_scraped_at,
    aba_debut,
    died,
    hof_inducted_year,
    hof_as,
    is_hall_of_famer,
    career_length_years,
    relatives,
    jersey_numbers,
    career_honors_text,
    bio_ext_scraped_at
   FROM public.dim_players;


--
-- Name: player_career_honors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_career_honors (
    id bigint NOT NULL,
    player_id text NOT NULL,
    honor_raw text NOT NULL,
    honor_type text NOT NULL,
    honor_count integer,
    honor_year integer,
    honor_detail text,
    source_url text,
    scraped_at timestamp without time zone DEFAULT now()
);


--
-- Name: player_career_honors_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.player_career_honors_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: player_career_honors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.player_career_honors_id_seq OWNED BY public.player_career_honors.id;


--
-- Name: player_career_totals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_career_totals (
    id integer NOT NULL,
    player_name text NOT NULL,
    games integer,
    pts_total integer,
    trb_total integer,
    ast_total integer,
    stl_total integer,
    blk_total integer,
    tov_total integer,
    pf_total integer,
    fg_total integer,
    fga_total integer,
    fg3_total integer,
    fga3_total integer,
    ft_total integer,
    fta_total integer,
    orb_total integer,
    drb_total integer,
    pts_per_game numeric(6,2),
    trb_per_game numeric(6,2),
    ast_per_game numeric(6,2),
    stl_per_game numeric(6,2),
    blk_per_game numeric(6,2),
    fg_pct numeric(5,3),
    fg3_pct numeric(5,3),
    ft_pct numeric(5,3),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: player_career_totals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.player_career_totals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: player_career_totals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.player_career_totals_id_seq OWNED BY public.player_career_totals.id;


--
-- Name: player_contracts_league; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_contracts_league (
    player_id character varying(32) NOT NULL,
    player_name text NOT NULL,
    team_abbr character varying(8) NOT NULL,
    season character varying(8) NOT NULL,
    salary_2025_26 bigint,
    salary_2026_27 bigint,
    salary_2027_28 bigint,
    salary_2028_29 bigint,
    salary_2029_30 bigint,
    salary_2030_31 bigint,
    opt_2025_26 character varying(20),
    opt_2026_27 character varying(20),
    opt_2027_28 character varying(20),
    opt_2028_29 character varying(20),
    opt_2029_30 character varying(20),
    opt_2030_31 character varying(20),
    guaranteed bigint,
    source_url text,
    scraped_at timestamp without time zone DEFAULT now() NOT NULL,
    weight numeric
);


--
-- Name: player_directory; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.player_directory AS
 SELECT player_id,
    player_name,
    year_from,
    year_to,
    "position",
    height_display,
    weight_lbs,
    (birth_date)::text AS birth_date_text,
    birth_date,
    college AS colleges,
    source_url,
    scraped_at
   FROM public.dim_players
  WHERE (year_from IS NOT NULL);


--
-- Name: player_dpm; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_dpm (
    nba_id bigint NOT NULL,
    br_player_id text,
    player_name text,
    team_name text,
    tm_id bigint,
    "position" text,
    season integer,
    career_game_num integer,
    dpm numeric(7,3),
    o_dpm numeric(7,3),
    d_dpm numeric(7,3),
    box_dpm numeric(7,3),
    on_off_dpm numeric(7,3),
    x_minutes numeric(7,3),
    x_pace numeric(7,3),
    x_pts_100 numeric(7,3),
    x_ast_100 numeric(7,3),
    x_fg_pct numeric(7,3),
    x_fg3_pct numeric(7,3),
    x_ft_pct numeric(7,3),
    sal_market_fixed numeric(14,2),
    actual_salary numeric(14,2),
    surplus_value numeric(14,2),
    dpm_rank integer,
    snapshot_date date NOT NULL,
    raw_json jsonb
);


--
-- Name: player_dpm_calc; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_dpm_calc (
    br_player_id text NOT NULL,
    nba_id bigint,
    player_name text,
    season integer NOT NULL,
    dpm numeric,
    o_dpm numeric,
    d_dpm numeric,
    box_dpm numeric,
    on_off_dpm numeric,
    mp numeric,
    w_onoff numeric,
    source text DEFAULT 'formula'::text,
    computed_at timestamp without time zone DEFAULT now()
);


--
-- Name: player_dpm_calc_bak_20260829; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_dpm_calc_bak_20260829 (
    br_player_id text,
    nba_id bigint,
    player_name text,
    season integer,
    dpm numeric,
    o_dpm numeric,
    d_dpm numeric,
    box_dpm numeric,
    on_off_dpm numeric,
    mp numeric,
    w_onoff numeric,
    source text,
    computed_at timestamp without time zone
);


--
-- Name: player_dpm_calc_bak_20260829_precal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_dpm_calc_bak_20260829_precal (
    br_player_id text,
    nba_id bigint,
    player_name text,
    season integer,
    dpm numeric,
    o_dpm numeric,
    d_dpm numeric,
    box_dpm numeric,
    on_off_dpm numeric,
    mp numeric,
    w_onoff numeric,
    source text,
    computed_at timestamp without time zone
);


--
-- Name: player_game_details; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.player_game_details AS
 SELECT game_id_full AS game_id,
    nba_player_id,
    plus_minus,
    fbpts,
    fbptsa,
    fbptsm,
    pip,
    pipa,
    pipm,
    blka,
    tech_fouls,
    court_status,
    seconds_played,
    pts,
    fgm,
    fga,
    tpm,
    tpa,
    ftm,
    fta,
    oreb,
    dreb,
    reb,
    ast,
    stl,
    blk,
    tov,
    pf,
    team_id,
    team_abbreviation,
    player_id,
    player_name,
    start_position,
    minutes,
    jersey_num,
    "position",
    player_status
   FROM public.player_gamelog
  WHERE (game_id_full IS NOT NULL);


--
-- Name: player_game_highs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_game_highs (
    player_id text NOT NULL,
    season_type text NOT NULL,
    season_end integer NOT NULL,
    season_text character varying(9),
    age integer,
    team character varying(4),
    league character varying(4),
    time_on_court character varying(12),
    fg integer,
    fga integer,
    fg3 integer,
    fg3a integer,
    fg2 integer,
    fg2a integer,
    ft integer,
    fta integer,
    orb integer,
    drb integer,
    trb integer,
    ast integer,
    stl integer,
    blk integer,
    tov integer,
    pf integer,
    pts integer,
    game_score numeric(5,1)
);


--
-- Name: player_gamelog_bailey_fix_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_bailey_fix_bak (
    id bigint,
    gameid character varying(10),
    player character varying(50),
    team character varying(10),
    season smallint,
    fg smallint,
    fga smallint,
    fg3 smallint,
    fga3 smallint,
    ft smallint,
    fta smallint,
    orb smallint,
    drb smallint,
    trb smallint,
    ast smallint,
    stl smallint,
    blk smallint,
    tov smallint,
    pf smallint,
    pts smallint,
    plus_minus smallint,
    fg_pct numeric(5,1),
    ft_pct numeric(5,1),
    fg3_pct numeric(5,1),
    created_at timestamp without time zone,
    nba_player_id bigint,
    fbpts integer,
    fbptsa integer,
    fbptsm integer,
    pip integer,
    pipa integer,
    pipm integer,
    blka integer,
    tech_fouls integer,
    court_status character varying(10),
    seconds_played integer,
    fgm integer,
    tpm integer,
    tpa integer,
    ftm integer,
    oreb integer,
    dreb integer,
    reb integer,
    team_id bigint,
    team_abbreviation character varying(10),
    player_id character varying(32),
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32),
    weight numeric,
    banned boolean,
    game_type text
);


--
-- Name: player_gamelog_banned_ids_20260817; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_banned_ids_20260817 (
    id bigint,
    game_id_full character varying(20),
    player_name character varying(200),
    team character varying(10),
    season smallint
);


--
-- Name: player_gamelog_br_bugfix_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_br_bugfix_bak (
    id bigint,
    gameid character varying(10),
    player character varying(50),
    team character varying(10),
    season smallint,
    fg smallint,
    fga smallint,
    fg3 smallint,
    fga3 smallint,
    ft smallint,
    fta smallint,
    orb smallint,
    drb smallint,
    trb smallint,
    ast smallint,
    stl smallint,
    blk smallint,
    tov smallint,
    pf smallint,
    pts smallint,
    plus_minus smallint,
    fg_pct numeric(5,1),
    ft_pct numeric(5,1),
    fg3_pct numeric(5,1),
    created_at timestamp without time zone,
    nba_player_id bigint,
    fbpts integer,
    fbptsa integer,
    fbptsm integer,
    pip integer,
    pipa integer,
    pipm integer,
    blka integer,
    tech_fouls integer,
    court_status character varying(10),
    seconds_played integer,
    fgm integer,
    tpm integer,
    tpa integer,
    ftm integer,
    oreb integer,
    dreb integer,
    reb integer,
    team_id bigint,
    team_abbreviation character varying(10),
    player_id character varying(32),
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32),
    weight numeric,
    banned boolean,
    game_type text
);


--
-- Name: player_gamelog_br_sync_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_br_sync_bak (
    id bigint,
    gameid character varying(10),
    player character varying(50),
    team character varying(10),
    season smallint,
    fg smallint,
    fga smallint,
    fg3 smallint,
    fga3 smallint,
    ft smallint,
    fta smallint,
    orb smallint,
    drb smallint,
    trb smallint,
    ast smallint,
    stl smallint,
    blk smallint,
    tov smallint,
    pf smallint,
    pts smallint,
    plus_minus smallint,
    fg_pct numeric(5,1),
    ft_pct numeric(5,1),
    fg3_pct numeric(5,1),
    created_at timestamp without time zone,
    nba_player_id bigint,
    fbpts integer,
    fbptsa integer,
    fbptsm integer,
    pip integer,
    pipa integer,
    pipm integer,
    blka integer,
    tech_fouls integer,
    court_status character varying(10),
    seconds_played integer,
    fgm integer,
    tpm integer,
    tpa integer,
    ftm integer,
    oreb integer,
    dreb integer,
    reb integer,
    team_id bigint,
    team_abbreviation character varying(10),
    player_id character varying(32),
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32),
    weight numeric,
    banned boolean,
    game_type text
);


--
-- Name: player_gamelog_collision_fix_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_collision_fix_bak (
    id bigint,
    gameid character varying(10),
    player character varying(50),
    team character varying(10),
    season smallint,
    fg smallint,
    fga smallint,
    fg3 smallint,
    fga3 smallint,
    ft smallint,
    fta smallint,
    orb smallint,
    drb smallint,
    trb smallint,
    ast smallint,
    stl smallint,
    blk smallint,
    tov smallint,
    pf smallint,
    pts smallint,
    plus_minus smallint,
    fg_pct numeric(5,1),
    ft_pct numeric(5,1),
    fg3_pct numeric(5,1),
    created_at timestamp without time zone,
    nba_player_id bigint,
    fbpts integer,
    fbptsa integer,
    fbptsm integer,
    pip integer,
    pipa integer,
    pipm integer,
    blka integer,
    tech_fouls integer,
    court_status character varying(10),
    seconds_played integer,
    fgm integer,
    tpm integer,
    tpa integer,
    ftm integer,
    oreb integer,
    dreb integer,
    reb integer,
    team_id bigint,
    team_abbreviation character varying(10),
    player_id character varying(32),
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32),
    weight numeric,
    banned boolean,
    game_type text
);


--
-- Name: player_gamelog_dup_20260807; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_dup_20260807 (
    id bigint,
    gameid character varying(10),
    player character varying(50),
    team character varying(10),
    season smallint,
    fg smallint,
    fga smallint,
    fg3 smallint,
    fga3 smallint,
    ft smallint,
    fta smallint,
    orb smallint,
    drb smallint,
    trb smallint,
    ast smallint,
    stl smallint,
    blk smallint,
    tov smallint,
    pf smallint,
    pts smallint,
    plus_minus smallint,
    fg_pct numeric(5,1),
    ft_pct numeric(5,1),
    fg3_pct numeric(5,1),
    created_at timestamp without time zone,
    nba_player_id bigint,
    fbpts integer,
    fbptsa integer,
    fbptsm integer,
    pip integer,
    pipa integer,
    pipm integer,
    blka integer,
    tech_fouls integer,
    court_status character varying(10),
    seconds_played integer,
    fgm integer,
    tpm integer,
    tpa integer,
    ftm integer,
    oreb integer,
    dreb integer,
    reb integer,
    team_id bigint,
    team_abbreviation character varying(10),
    player_id character varying(32),
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32),
    weight numeric
);


--
-- Name: player_gamelog_era_fix_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_era_fix_bak (
    id bigint,
    gameid character varying(10),
    player character varying(50),
    team character varying(10),
    season smallint,
    fg smallint,
    fga smallint,
    fg3 smallint,
    fga3 smallint,
    ft smallint,
    fta smallint,
    orb smallint,
    drb smallint,
    trb smallint,
    ast smallint,
    stl smallint,
    blk smallint,
    tov smallint,
    pf smallint,
    pts smallint,
    plus_minus smallint,
    fg_pct numeric(5,1),
    ft_pct numeric(5,1),
    fg3_pct numeric(5,1),
    created_at timestamp without time zone,
    nba_player_id bigint,
    fbpts integer,
    fbptsa integer,
    fbptsm integer,
    pip integer,
    pipa integer,
    pipm integer,
    blka integer,
    tech_fouls integer,
    court_status character varying(10),
    seconds_played integer,
    fgm integer,
    tpm integer,
    tpa integer,
    ftm integer,
    oreb integer,
    dreb integer,
    reb integer,
    team_id bigint,
    team_abbreviation character varying(10),
    player_id character varying(32),
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32),
    weight numeric,
    banned boolean,
    game_type text
);


--
-- Name: player_gamelog_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.player_gamelog_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: player_gamelog_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.player_gamelog_id_seq OWNED BY public.player_gamelog.id;


--
-- Name: player_gamelog_jones_fix_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_jones_fix_bak (
    id bigint DEFAULT nextval('public.player_gamelog_id_seq'::regclass) CONSTRAINT player_gamelog_id_not_null NOT NULL,
    gameid character varying(10) CONSTRAINT player_gamelog_gameid_not_null NOT NULL,
    player character varying(50) CONSTRAINT player_gamelog_player_not_null NOT NULL,
    team character varying(10),
    season smallint,
    fg smallint DEFAULT 0,
    fga smallint DEFAULT 0,
    fg3 smallint DEFAULT 0,
    fga3 smallint DEFAULT 0,
    ft smallint DEFAULT 0,
    fta smallint DEFAULT 0,
    orb smallint DEFAULT 0,
    drb smallint DEFAULT 0,
    trb smallint DEFAULT 0,
    ast smallint DEFAULT 0,
    stl smallint DEFAULT 0,
    blk smallint DEFAULT 0,
    tov smallint DEFAULT 0,
    pf smallint DEFAULT 0,
    pts smallint DEFAULT 0,
    plus_minus smallint DEFAULT 0,
    fg_pct numeric(5,1) DEFAULT 0,
    ft_pct numeric(5,1) DEFAULT 0,
    fg3_pct numeric(5,1) DEFAULT 0,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    nba_player_id bigint,
    fbpts integer,
    fbptsa integer,
    fbptsm integer,
    pip integer,
    pipa integer,
    pipm integer,
    blka integer,
    tech_fouls integer,
    court_status character varying(10),
    seconds_played integer,
    fgm integer,
    tpm integer,
    tpa integer,
    ftm integer,
    oreb integer,
    dreb integer,
    reb integer,
    team_id bigint,
    team_abbreviation character varying(10),
    player_id character varying(32),
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32),
    weight numeric,
    banned boolean DEFAULT false CONSTRAINT player_gamelog_banned_not_null NOT NULL,
    game_type text
);


--
-- Name: player_gamelog_nameless_20260807; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_nameless_20260807 (
    id bigint,
    gameid character varying(10),
    player character varying(50),
    team character varying(10),
    season smallint,
    fg smallint,
    fga smallint,
    fg3 smallint,
    fga3 smallint,
    ft smallint,
    fta smallint,
    orb smallint,
    drb smallint,
    trb smallint,
    ast smallint,
    stl smallint,
    blk smallint,
    tov smallint,
    pf smallint,
    pts smallint,
    plus_minus smallint,
    fg_pct numeric(5,1),
    ft_pct numeric(5,1),
    fg3_pct numeric(5,1),
    created_at timestamp without time zone,
    nba_player_id bigint,
    fbpts integer,
    fbptsa integer,
    fbptsm integer,
    pip integer,
    pipa integer,
    pipm integer,
    blka integer,
    tech_fouls integer,
    court_status character varying(10),
    seconds_played integer,
    fgm integer,
    tpm integer,
    tpa integer,
    ftm integer,
    oreb integer,
    dreb integer,
    reb integer,
    team_id bigint,
    team_abbreviation character varying(10),
    player_id character varying(32),
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32),
    weight numeric
);


--
-- Name: player_gamelog_orphan_brnull_20260807; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_orphan_brnull_20260807 (
    id bigint,
    gameid character varying(10),
    player character varying(50),
    team character varying(10),
    season smallint,
    fg smallint,
    fga smallint,
    fg3 smallint,
    fga3 smallint,
    ft smallint,
    fta smallint,
    orb smallint,
    drb smallint,
    trb smallint,
    ast smallint,
    stl smallint,
    blk smallint,
    tov smallint,
    pf smallint,
    pts smallint,
    plus_minus smallint,
    fg_pct numeric(5,1),
    ft_pct numeric(5,1),
    fg3_pct numeric(5,1),
    created_at timestamp without time zone,
    nba_player_id bigint,
    fbpts integer,
    fbptsa integer,
    fbptsm integer,
    pip integer,
    pipa integer,
    pipm integer,
    blka integer,
    tech_fouls integer,
    court_status character varying(10),
    seconds_played integer,
    fgm integer,
    tpm integer,
    tpa integer,
    ftm integer,
    oreb integer,
    dreb integer,
    reb integer,
    team_id bigint,
    team_abbreviation character varying(10),
    player_id bigint,
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32),
    weight numeric
);


--
-- Name: player_gamelog_quarantine_20260806; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_quarantine_20260806 (
    id bigint,
    gameid character varying(10),
    player character varying(50),
    team character varying(10),
    season smallint,
    fg smallint,
    fga smallint,
    fg3 smallint,
    fga3 smallint,
    ft smallint,
    fta smallint,
    orb smallint,
    drb smallint,
    trb smallint,
    ast smallint,
    stl smallint,
    blk smallint,
    tov smallint,
    pf smallint,
    pts smallint,
    plus_minus smallint,
    fg_pct numeric(5,1),
    ft_pct numeric(5,1),
    fg3_pct numeric(5,1),
    created_at timestamp without time zone,
    nba_player_id bigint,
    fbpts integer,
    fbptsa integer,
    fbptsm integer,
    pip integer,
    pipa integer,
    pipm integer,
    blka integer,
    tech_fouls integer,
    court_status character varying(10),
    seconds_played integer,
    fgm integer,
    tpm integer,
    tpa integer,
    ftm integer,
    oreb integer,
    dreb integer,
    reb integer,
    team_id bigint,
    team_abbreviation character varying(10),
    player_id bigint,
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32),
    weight numeric
);


--
-- Name: player_gamelog_rollback_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_rollback_bak (
    id bigint,
    gameid character varying(10),
    player character varying(50),
    team character varying(10),
    season smallint,
    fg smallint,
    fga smallint,
    fg3 smallint,
    fga3 smallint,
    ft smallint,
    fta smallint,
    orb smallint,
    drb smallint,
    trb smallint,
    ast smallint,
    stl smallint,
    blk smallint,
    tov smallint,
    pf smallint,
    pts smallint,
    plus_minus smallint,
    fg_pct numeric(5,1),
    ft_pct numeric(5,1),
    fg3_pct numeric(5,1),
    created_at timestamp without time zone,
    nba_player_id bigint,
    fbpts integer,
    fbptsa integer,
    fbptsm integer,
    pip integer,
    pipa integer,
    pipm integer,
    blka integer,
    tech_fouls integer,
    court_status character varying(10),
    seconds_played integer,
    fgm integer,
    tpm integer,
    tpa integer,
    ftm integer,
    oreb integer,
    dreb integer,
    reb integer,
    team_id bigint,
    team_abbreviation character varying(10),
    player_id character varying(32),
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32),
    weight numeric,
    banned boolean,
    game_type text
);


--
-- Name: player_gamelog_teamown_fix_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_teamown_fix_bak (
    id bigint DEFAULT nextval('public.player_gamelog_id_seq'::regclass) CONSTRAINT player_gamelog_id_not_null NOT NULL,
    gameid character varying(10) CONSTRAINT player_gamelog_gameid_not_null NOT NULL,
    player character varying(50) CONSTRAINT player_gamelog_player_not_null NOT NULL,
    team character varying(10),
    season smallint,
    fg smallint DEFAULT 0,
    fga smallint DEFAULT 0,
    fg3 smallint DEFAULT 0,
    fga3 smallint DEFAULT 0,
    ft smallint DEFAULT 0,
    fta smallint DEFAULT 0,
    orb smallint DEFAULT 0,
    drb smallint DEFAULT 0,
    trb smallint DEFAULT 0,
    ast smallint DEFAULT 0,
    stl smallint DEFAULT 0,
    blk smallint DEFAULT 0,
    tov smallint DEFAULT 0,
    pf smallint DEFAULT 0,
    pts smallint DEFAULT 0,
    plus_minus smallint DEFAULT 0,
    fg_pct numeric(5,1) DEFAULT 0,
    ft_pct numeric(5,1) DEFAULT 0,
    fg3_pct numeric(5,1) DEFAULT 0,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    nba_player_id bigint,
    fbpts integer,
    fbptsa integer,
    fbptsm integer,
    pip integer,
    pipa integer,
    pipm integer,
    blka integer,
    tech_fouls integer,
    court_status character varying(10),
    seconds_played integer,
    fgm integer,
    tpm integer,
    tpa integer,
    ftm integer,
    oreb integer,
    dreb integer,
    reb integer,
    team_id bigint,
    team_abbreviation character varying(10),
    player_id character varying(32),
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32),
    weight numeric,
    banned boolean DEFAULT false CONSTRAINT player_gamelog_banned_not_null NOT NULL,
    game_type text
);


--
-- Name: player_id_bridge_1to1; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_id_bridge_1to1 (
    br_player_id text NOT NULL,
    canonical_name text NOT NULL
);


--
-- Name: player_lebron; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_lebron (
    nba_id text NOT NULL,
    player_name text,
    season integer NOT NULL,
    through_date date,
    lebron numeric,
    olebron numeric,
    dlebron numeric,
    boxlebron numeric,
    lebron_war numeric,
    total_luck numeric,
    mins numeric,
    off_poss numeric,
    def_poss numeric,
    cum_off_poss numeric,
    cum_def_poss numeric,
    off_points_added numeric,
    def_points_saved numeric,
    br_player_id character varying,
    snapshot_date date
);


--
-- Name: player_lineups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_lineups (
    id bigint NOT NULL,
    player_id text NOT NULL,
    season integer NOT NULL,
    season_type character varying(20) DEFAULT 'Regular'::character varying NOT NULL,
    lineup_key text NOT NULL,
    br_player_id1 character varying,
    br_player_id2 character varying,
    br_player_id3 character varying,
    br_player_id4 character varying,
    br_player_id5 character varying,
    player_name1 text,
    player_name2 text,
    player_name3 text,
    player_name4 text,
    player_name5 text,
    minutes integer,
    source text DEFAULT 'basketball-reference'::text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    ranker integer,
    team_id text,
    diff_fg double precision,
    diff_fga double precision,
    diff_fg_pct double precision,
    diff_fg3 double precision,
    diff_fg3a double precision,
    diff_fg3_pct double precision,
    diff_efg_pct double precision,
    diff_ft double precision,
    diff_fta double precision,
    diff_ft_pct double precision,
    diff_pts double precision,
    diff_orb double precision,
    diff_orb_pct double precision,
    diff_drb double precision,
    diff_drb_pct double precision,
    diff_trb double precision,
    diff_trb_pct double precision,
    diff_ast double precision,
    diff_stl double precision,
    diff_blk double precision,
    diff_tov double precision,
    diff_pf double precision,
    lineup_size smallint DEFAULT 5 NOT NULL
);


--
-- Name: player_lineups_404; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_lineups_404 (
    slug text NOT NULL,
    year integer NOT NULL,
    first_seen timestamp with time zone DEFAULT now() NOT NULL,
    note text
);


--
-- Name: player_lineups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.player_lineups_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: player_lineups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.player_lineups_id_seq OWNED BY public.player_lineups.id;


--
-- Name: player_metrics_daily; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_metrics_daily (
    snapshot_date date NOT NULL,
    metric text NOT NULL,
    player_key text NOT NULL,
    source text,
    nba_id bigint,
    player_name text,
    team_abbr text,
    season_label text,
    val numeric,
    val_o numeric,
    val_d numeric,
    extra jsonb,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT player_metrics_daily_metric_chk CHECK ((metric = ANY (ARRAY['dpm'::text, 'rapm'::text, 'lebron'::text, 'epm'::text])))
);


--
-- Name: player_name_unified; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_name_unified (
    id integer NOT NULL,
    abbreviation character varying(100),
    full_name character varying(200),
    last_name character varying(100),
    career_name character varying(200),
    draft_name character varying(200),
    match_score double precision,
    source character varying(20),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: player_name_map; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.player_name_map AS
 SELECT abbreviation,
    last_name
   FROM public.player_name_unified
  WHERE (last_name IS NOT NULL);


--
-- Name: player_name_unified_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.player_name_unified_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: player_name_unified_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.player_name_unified_id_seq OWNED BY public.player_name_unified.id;


--
-- Name: player_onoff; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_onoff (
    player_id text NOT NULL,
    season integer NOT NULL,
    season_type text NOT NULL,
    split text NOT NULL,
    team_id text,
    mp numeric,
    min_pct numeric,
    efg_pct numeric,
    orb_pct numeric,
    drb_pct numeric,
    trb_pct numeric,
    ast_pct numeric,
    stl_pct numeric,
    blk_pct numeric,
    tov_pct numeric,
    off_rtg numeric,
    opp_efg_pct numeric,
    opp_orb_pct numeric,
    opp_drb_pct numeric,
    opp_trb_pct numeric,
    opp_ast_pct numeric,
    opp_stl_pct numeric,
    opp_blk_pct numeric,
    opp_tov_pct numeric,
    opp_off_rtg numeric,
    diff_efg_pct numeric,
    diff_orb_pct numeric,
    diff_drb_pct numeric,
    diff_trb_pct numeric,
    diff_ast_pct numeric,
    diff_stl_pct numeric,
    diff_blk_pct numeric,
    diff_tov_pct numeric,
    diff_off_rtg numeric,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: player_page_overview; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_page_overview (
    player_id character varying(16) NOT NULL,
    full_name text,
    instagram text,
    nickname_display text,
    position_text text,
    shoots text,
    height_display text,
    weight_display text,
    team_text text,
    born_text text,
    relatives_text text,
    high_school text,
    recruiting_rank text,
    draft_text text,
    nba_debut text,
    experience_text text,
    overview_raw text,
    source_url text,
    scraped_at timestamp with time zone DEFAULT now()
);


--
-- Name: v_player_per_100_poss; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_player_per_100_poss AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    mp,
    fg_per_100_poss,
    fga_per_100_poss,
    fg_percent,
    x3p_per_100_poss,
    x3pa_per_100_poss,
    x3p_percent,
    x2p_per_100_poss,
    x2pa_per_100_poss,
    x2p_percent,
    e_fg_percent,
    ft_per_100_poss,
    fta_per_100_poss,
    ft_percent,
    orb_per_100_poss,
    drb_per_100_poss,
    trb_per_100_poss,
    ast_per_100_poss,
    stl_per_100_poss,
    blk_per_100_poss,
    tov_per_100_poss,
    pf_per_100_poss,
    pts_per_100_poss,
    o_rtg,
    d_rtg,
    season_type
   FROM public.fact_player_season_stats
  WHERE ((o_rtg IS NOT NULL) OR (fg_per_100_poss IS NOT NULL));


--
-- Name: player_per_100_poss; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.player_per_100_poss AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    mp,
    fg_per_100_poss,
    fga_per_100_poss,
    fg_percent,
    x3p_per_100_poss,
    x3pa_per_100_poss,
    x3p_percent,
    x2p_per_100_poss,
    x2pa_per_100_poss,
    x2p_percent,
    e_fg_percent,
    ft_per_100_poss,
    fta_per_100_poss,
    ft_percent,
    orb_per_100_poss,
    drb_per_100_poss,
    trb_per_100_poss,
    ast_per_100_poss,
    stl_per_100_poss,
    blk_per_100_poss,
    tov_per_100_poss,
    pf_per_100_poss,
    pts_per_100_poss,
    o_rtg,
    d_rtg,
    season_type
   FROM public.v_player_per_100_poss;


--
-- Name: v_player_per_36_min; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_player_per_36_min AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    mp,
    round((((fg)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS fg_per_36_min,
    round((((fga)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS fga_per_36_min,
    fg_percent,
    round((((x3p)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS x3p_per_36_min,
    round((((x3pa)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS x3pa_per_36_min,
    x3p_percent,
    round((((x2p)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS x2p_per_36_min,
    round((((x2pa)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS x2pa_per_36_min,
    x2p_percent,
    e_fg_percent,
    round((((ft)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS ft_per_36_min,
    round((((fta)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS fta_per_36_min,
    ft_percent,
    round((((orb)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS orb_per_36_min,
    round((((drb)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS drb_per_36_min,
    round((((trb)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS trb_per_36_min,
    round((((ast)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS ast_per_36_min,
    round((((stl)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS stl_per_36_min,
    round((((blk)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS blk_per_36_min,
    round((((tov)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS tov_per_36_min,
    round((((pf)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS pf_per_36_min,
    round((((pts)::numeric * (36)::numeric) / NULLIF((mp)::numeric, (0)::numeric)), 1) AS pts_per_36_min,
    season_type
   FROM public.fact_player_season_stats
  WHERE (mp > (0)::double precision);


--
-- Name: player_per_36_minutes; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.player_per_36_minutes AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    mp,
    fg_per_36_min,
    fga_per_36_min,
    fg_percent,
    x3p_per_36_min,
    x3pa_per_36_min,
    x3p_percent,
    x2p_per_36_min,
    x2pa_per_36_min,
    x2p_percent,
    e_fg_percent,
    ft_per_36_min,
    fta_per_36_min,
    ft_percent,
    orb_per_36_min,
    drb_per_36_min,
    trb_per_36_min,
    ast_per_36_min,
    stl_per_36_min,
    blk_per_36_min,
    tov_per_36_min,
    pf_per_36_min,
    pts_per_36_min,
    season_type
   FROM public.v_player_per_36_min;


--
-- Name: v_player_per_game; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_player_per_game AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    round(((mp)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS mp_per_game,
    round(((fg)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS fg_per_game,
    round(((fga)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS fga_per_game,
    fg_percent,
    round(((x3p)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS x3p_per_game,
    round(((x3pa)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS x3pa_per_game,
    x3p_percent,
    round(((x2p)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS x2p_per_game,
    round(((x2pa)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS x2pa_per_game,
    x2p_percent,
    e_fg_percent,
    round(((ft)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS ft_per_game,
    round(((fta)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS fta_per_game,
    ft_percent,
    round(((orb)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS orb_per_game,
    round(((drb)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS drb_per_game,
    round(((trb)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS trb_per_game,
    round(((ast)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS ast_per_game,
    round(((stl)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS stl_per_game,
    round(((blk)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS blk_per_game,
    round(((tov)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS tov_per_game,
    round(((pf)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS pf_per_game,
    round(((pts)::numeric / NULLIF((g)::numeric, (0)::numeric)), 1) AS pts_per_game,
    season_type
   FROM public.fact_player_season_stats
  WHERE (g > 0);


--
-- Name: player_per_game; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.player_per_game AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    mp_per_game,
    fg_per_game,
    fga_per_game,
    fg_percent,
    x3p_per_game,
    x3pa_per_game,
    x3p_percent,
    x2p_per_game,
    x2pa_per_game,
    x2p_percent,
    e_fg_percent,
    ft_per_game,
    fta_per_game,
    ft_percent,
    orb_per_game,
    drb_per_game,
    trb_per_game,
    ast_per_game,
    stl_per_game,
    blk_per_game,
    tov_per_game,
    pf_per_game,
    pts_per_game,
    season_type
   FROM public.v_player_per_game;


--
-- Name: player_playin_plus_minus; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_playin_plus_minus (
    game_id_full character varying(20) NOT NULL,
    br_game_id character varying(12),
    season smallint NOT NULL,
    game_date date,
    player_name text NOT NULL,
    br_player_id text,
    team_abbr text,
    is_home boolean,
    q1 smallint,
    q2 smallint,
    q3 smallint,
    q4 smallint,
    ot1 smallint,
    ot2 smallint,
    ot3 smallint,
    ot4 smallint,
    plus_minus_total smallint NOT NULL,
    off_court_value smallint,
    net_value smallint,
    source text DEFAULT 'BR'::text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: player_playoffs_series; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_playoffs_series (
    player_id text NOT NULL,
    season_end integer NOT NULL,
    season_text character varying(9) NOT NULL,
    age integer,
    team_abbr character varying(4),
    lg character varying(4),
    ps_round character varying(8) NOT NULL,
    opp_abbr character varying(4) NOT NULL,
    series_result character varying(16),
    games integer,
    mp_per_g numeric(5,1),
    pts_per_g numeric(5,1),
    trb_per_g numeric(5,1),
    ast_per_g numeric(5,1),
    stl_per_g numeric(5,1),
    blk_per_g numeric(5,1),
    fg integer,
    fga integer,
    fg_pct numeric(5,3),
    fg3 integer,
    fg3a integer,
    fg3_pct numeric(5,3),
    fg2 integer,
    fg2a integer,
    fg2_pct numeric(5,3),
    efg_pct numeric(5,3),
    ft integer,
    fta integer,
    ft_pct numeric(5,3),
    orb integer,
    drb integer,
    trb integer,
    ast integer,
    stl integer,
    blk integer,
    tov integer,
    pf integer,
    pts integer,
    awards text
);


--
-- Name: player_playoffs_series_bak_20260816; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_playoffs_series_bak_20260816 (
    player_id text,
    season_end integer,
    season_text character varying(9),
    age integer,
    team_abbr character varying(4),
    lg character varying(4),
    ps_round character varying(8),
    opp_abbr character varying(4),
    series_result character varying(16),
    games integer,
    mp_per_g numeric(5,1),
    pts_per_g numeric(5,1),
    trb_per_g numeric(5,1),
    ast_per_g numeric(5,1),
    stl_per_g numeric(5,1),
    blk_per_g numeric(5,1),
    fg integer,
    fga integer,
    fg_pct numeric(5,3),
    fg3 integer,
    fg3a integer,
    fg3_pct numeric(5,3),
    fg2 integer,
    fg2a integer,
    fg2_pct numeric(5,3),
    efg_pct numeric(5,3),
    ft integer,
    fta integer,
    ft_pct numeric(5,3),
    orb integer,
    drb integer,
    trb integer,
    ast integer,
    stl integer,
    blk integer,
    tov integer,
    pf integer,
    pts integer,
    awards text
);


--
-- Name: player_playoffs_series_bak_20260911; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_playoffs_series_bak_20260911 (
    player_id text,
    season_end integer,
    season_text character varying(9),
    age integer,
    team_abbr character varying(4),
    lg character varying(4),
    ps_round character varying(8),
    opp_abbr character varying(4),
    series_result character varying(16),
    games integer,
    mp_per_g numeric(5,1),
    pts_per_g numeric(5,1),
    trb_per_g numeric(5,1),
    ast_per_g numeric(5,1),
    stl_per_g numeric(5,1),
    blk_per_g numeric(5,1),
    fg integer,
    fga integer,
    fg_pct numeric(5,3),
    fg3 integer,
    fg3a integer,
    fg3_pct numeric(5,3),
    fg2 integer,
    fg2a integer,
    fg2_pct numeric(5,3),
    efg_pct numeric(5,3),
    ft integer,
    fta integer,
    ft_pct numeric(5,3),
    orb integer,
    drb integer,
    trb integer,
    ast integer,
    stl integer,
    blk integer,
    tov integer,
    pf integer,
    pts integer,
    awards text
);


--
-- Name: player_rapm; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_rapm (
    nba_id bigint NOT NULL,
    player_name text,
    team_abbr text,
    "position" text,
    snapshot_date date NOT NULL,
    rapm_total numeric(7,3),
    rapm_rank integer,
    rapm_pop integer,
    ots numeric(7,3),
    otov numeric(7,3),
    osc numeric(7,3),
    dts numeric(7,3),
    dtov numeric(7,3),
    dsc numeric(7,3),
    rapm_sum numeric(7,3),
    on_off_net numeric(7,3),
    on_court_net numeric(7,3),
    off_rtg numeric(7,3),
    def_rtg numeric(7,3),
    br_player_id text,
    has_bundle boolean
);


--
-- Name: player_rapm_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_rapm_history (
    nba_id bigint NOT NULL,
    season integer NOT NULL,
    is_playoff boolean DEFAULT false NOT NULL,
    player_name text,
    team_abbr text,
    "position" text,
    ovr_rapm numeric,
    orapm numeric,
    drapm numeric,
    ovr_rapm_rank integer,
    rapm_rank integer,
    def_rapm_rank integer,
    off_poss numeric,
    def_poss numeric,
    possessions numeric,
    orapm_decomp_tov numeric,
    orapm_decomp_sc numeric,
    orapm_decomp_shot numeric,
    orapm_decomp_ft numeric,
    orapm_decomp_scoring numeric,
    drapm_decomp_tov numeric,
    drapm_decomp_sc numeric,
    drapm_decomp_shot numeric,
    drapm_decomp_ft numeric,
    drapm_decomp_scoring numeric,
    nrapm_decomp_tov numeric,
    nrapm_decomp_sc numeric,
    nrapm_decomp_shot numeric,
    nrapm_decomp_ft numeric,
    nrapm_decomp_scoring numeric,
    as_of_date text,
    raw jsonb
);


--
-- Name: player_salaries_historical_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.player_salaries_historical_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: player_salaries_historical_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.player_salaries_historical_id_seq OWNED BY public.player_salaries_historical.id;


--
-- Name: player_season_splits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_season_splits (
    id integer NOT NULL,
    season integer NOT NULL,
    player_name text NOT NULL,
    team_abbr text,
    split_type text NOT NULL,
    games integer,
    pts numeric(6,2),
    reb numeric(6,2),
    ast numeric(6,2),
    fg_pct numeric(5,3),
    fg3_pct numeric(5,3),
    ft_pct numeric(5,3),
    plus_minus numeric(7,2),
    created_at timestamp without time zone DEFAULT now(),
    split_category text DEFAULT 'location'::text,
    mp numeric(6,1),
    fg integer,
    fga integer,
    fg3 integer,
    fga3 integer,
    ft integer,
    fta integer,
    orb integer,
    drb integer,
    stl integer,
    blk integer,
    tov integer,
    pf integer,
    player_id character varying(20),
    weight numeric
);


--
-- Name: player_season_splits_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.player_season_splits_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: player_season_splits_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.player_season_splits_id_seq OWNED BY public.player_season_splits.id;


--
-- Name: player_shot_chart; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_shot_chart (
    player_id text NOT NULL,
    season bigint NOT NULL,
    game_date date,
    game_id text,
    season_type text,
    opponent_abbr text,
    is_home boolean,
    period smallint,
    time_remaining text,
    made boolean,
    shot_value smallint,
    dist_ft smallint,
    x_px numeric(7,2),
    y_px numeric(7,2),
    x_norm numeric(8,4),
    y_norm numeric(8,4),
    src text DEFAULT 'basketball-reference'::text,
    created_at timestamp with time zone DEFAULT now(),
    bf20260804 boolean
);


--
-- Name: player_similarity_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_similarity_scores (
    player_id text NOT NULL,
    scope text NOT NULL,
    comparable_name text NOT NULL,
    sim_score numeric(6,2),
    year_scores jsonb
);


--
-- Name: player_totals; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.player_totals AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    mp,
    fg,
    fga,
    fg_percent,
    x3p,
    x3pa,
    x3p_percent,
    x2p,
    x2pa,
    x2p_percent,
    e_fg_percent,
    ft,
    fta,
    ft_percent,
    orb,
    drb,
    trb,
    ast,
    stl,
    blk,
    tov,
    pf,
    pts,
    trp_dbl,
    season_type
   FROM public.fact_player_season_stats;


--
-- Name: player_weight_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_weight_history (
    player_id text NOT NULL,
    player_name text,
    weight_lbs integer,
    weight_kg integer,
    height text,
    born text,
    scraped_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "position" text,
    shoots text
);


--
-- Name: playin_game_dates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.playin_game_dates (
    season integer,
    game_id_full text NOT NULL,
    br_game_id text,
    nba_api_id bigint,
    game_date date,
    home_team_abbr text,
    away_team_abbr text,
    player_count integer
);


--
-- Name: playoff_player_advanced; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.playoff_player_advanced AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    mp,
    per,
    ts_percent,
    x3p_ar,
    f_tr,
    orb_percent,
    drb_percent,
    trb_percent,
    ast_percent,
    stl_percent,
    blk_percent,
    tov_percent,
    usg_percent,
    ows,
    dws,
    ws,
    ws_48,
    obpm,
    dbpm,
    bpm,
    vorp,
    season_type
   FROM public.player_advanced
  WHERE ((season_type)::text = 'Playoffs'::text);


--
-- Name: playoff_player_per_100; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.playoff_player_per_100 AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    mp,
    fg_per_100_poss,
    fga_per_100_poss,
    fg_percent,
    x3p_per_100_poss,
    x3pa_per_100_poss,
    x3p_percent,
    x2p_per_100_poss,
    x2pa_per_100_poss,
    x2p_percent,
    e_fg_percent,
    ft_per_100_poss,
    fta_per_100_poss,
    ft_percent,
    orb_per_100_poss,
    drb_per_100_poss,
    trb_per_100_poss,
    ast_per_100_poss,
    stl_per_100_poss,
    blk_per_100_poss,
    tov_per_100_poss,
    pf_per_100_poss,
    pts_per_100_poss,
    o_rtg,
    d_rtg,
    season_type
   FROM public.player_per_100_poss
  WHERE ((season_type)::text = 'Playoffs'::text);


--
-- Name: playoff_player_per_36; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.playoff_player_per_36 AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    mp,
    fg_per_36_min,
    fga_per_36_min,
    fg_percent,
    x3p_per_36_min,
    x3pa_per_36_min,
    x3p_percent,
    x2p_per_36_min,
    x2pa_per_36_min,
    x2p_percent,
    e_fg_percent,
    ft_per_36_min,
    fta_per_36_min,
    ft_percent,
    orb_per_36_min,
    drb_per_36_min,
    trb_per_36_min,
    ast_per_36_min,
    stl_per_36_min,
    blk_per_36_min,
    tov_per_36_min,
    pf_per_36_min,
    pts_per_36_min,
    season_type
   FROM public.player_per_36_minutes
  WHERE ((season_type)::text = 'Playoffs'::text);


--
-- Name: playoff_player_per_game; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.playoff_player_per_game AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    mp_per_game,
    fg_per_game,
    fga_per_game,
    fg_percent,
    x3p_per_game,
    x3pa_per_game,
    x3p_percent,
    x2p_per_game,
    x2pa_per_game,
    x2p_percent,
    e_fg_percent,
    ft_per_game,
    fta_per_game,
    ft_percent,
    orb_per_game,
    drb_per_game,
    trb_per_game,
    ast_per_game,
    stl_per_game,
    blk_per_game,
    tov_per_game,
    pf_per_game,
    pts_per_game,
    season_type
   FROM public.player_per_game
  WHERE ((season_type)::text = 'Playoffs'::text);


--
-- Name: playoff_player_shooting; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.playoff_player_shooting AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    mp,
    fg_percent,
    avg_dist_fga,
    percent_fga_from_x2p_range,
    percent_fga_from_x0_3_range,
    percent_fga_from_x3_10_range,
    percent_fga_from_x10_16_range,
    percent_fga_from_x16_3p_range,
    percent_fga_from_x3p_range,
    fg_percent_from_x2p_range,
    fg_percent_from_x0_3_range,
    fg_percent_from_x3_10_range,
    fg_percent_from_x10_16_range,
    fg_percent_from_x16_3p_range,
    fg_percent_from_x3p_range,
    percent_assisted_x2p_fg,
    percent_assisted_x3p_fg,
    percent_dunks_of_fga,
    num_of_dunks,
    percent_corner_3s_of_3pa,
    corner_3_point_percent,
    num_heaves_attempted,
    num_heaves_made,
    season_type
   FROM public.player_shooting
  WHERE ((season_type)::text = 'Playoffs'::text);


--
-- Name: playoff_player_totals; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.playoff_player_totals AS
 SELECT season,
    lg,
    player,
    player_id,
    age,
    team,
    pos,
    g,
    gs,
    mp,
    fg,
    fga,
    fg_percent,
    x3p,
    x3pa,
    x3p_percent,
    x2p,
    x2pa,
    x2p_percent,
    e_fg_percent,
    ft,
    fta,
    ft_percent,
    orb,
    drb,
    trb,
    ast,
    stl,
    blk,
    tov,
    pf,
    pts,
    trp_dbl,
    season_type
   FROM public.player_totals
  WHERE ((season_type)::text = 'Playoffs'::text);


--
-- Name: starting_lineups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.starting_lineups (
    id integer NOT NULL,
    season integer NOT NULL,
    team_abbr text NOT NULL,
    game_date date,
    lineup_type text DEFAULT 'starting'::text,
    player1 text,
    player2 text,
    player3 text,
    player4 text,
    player5 text,
    minutes real,
    source text DEFAULT 'basketball-reference'::text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: starting_lineups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.starting_lineups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: starting_lineups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.starting_lineups_id_seq OWNED BY public.starting_lineups.id;


--
-- Name: team_coaches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_coaches (
    team_abbr text NOT NULL,
    season integer NOT NULL,
    coach_name text NOT NULL,
    role text NOT NULL,
    coach_slug text,
    source text DEFAULT 'br_crawler'::text,
    created_at timestamp without time zone DEFAULT now(),
    franchise_id integer
);


--
-- Name: team_depth_chart; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_depth_chart (
    id integer NOT NULL,
    season integer NOT NULL,
    team_abbr text NOT NULL,
    player_name text NOT NULL,
    start_count integer,
    last_start date,
    depth_rank integer,
    created_at timestamp without time zone DEFAULT now(),
    "position" text,
    player_id bigint
);


--
-- Name: team_depth_chart_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.team_depth_chart_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: team_depth_chart_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.team_depth_chart_id_seq OWNED BY public.team_depth_chart.id;


--
-- Name: team_executives; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_executives (
    id bigint NOT NULL,
    team_abbr character varying(3) NOT NULL,
    rk integer NOT NULL,
    executive text NOT NULL,
    start text NOT NULL,
    "end" text NOT NULL,
    notes text,
    scraped_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: team_executives_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.team_executives_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: team_executives_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.team_executives_id_seq OWNED BY public.team_executives.id;


--
-- Name: team_franchise_all_star; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_franchise_all_star (
    team_abbr text NOT NULL,
    franchise_id integer,
    season text NOT NULL,
    player_name text NOT NULL,
    br_slug text,
    source text DEFAULT 'br_crawler'::text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: team_franchise_coaches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_franchise_coaches (
    team_abbr text NOT NULL,
    franchise_id integer,
    coach_name text NOT NULL,
    years text NOT NULL,
    reg_w integer,
    reg_l integer,
    reg_wl_pct numeric(5,3),
    po_w integer,
    po_l integer,
    po_wl_pct numeric(5,3),
    total_w integer,
    total_l integer,
    total_wl_pct numeric(5,3),
    source text DEFAULT 'basketball-reference'::text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: team_franchise_head2head; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_franchise_head2head (
    team_abbr text NOT NULL,
    franchise_id integer,
    table_seq smallint DEFAULT 0 NOT NULL,
    row_idx integer NOT NULL,
    col_idx integer NOT NULL,
    col_header text,
    val text,
    source text DEFAULT 'br_crawler'::text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: team_franchise_hof; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_franchise_hof (
    team_abbr text NOT NULL,
    franchise_id integer,
    season text NOT NULL,
    player_name text NOT NULL,
    br_slug text,
    source text DEFAULT 'br_crawler'::text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: team_franchise_index; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_franchise_index (
    team_abbr text NOT NULL,
    franchise_id integer,
    season integer NOT NULL,
    lg text,
    team_name text,
    w integer,
    l integer,
    wl_pct numeric(5,3),
    finish text,
    srs numeric(6,2),
    playoffs text,
    source text DEFAULT 'basketball-reference'::text,
    created_at timestamp with time zone DEFAULT now(),
    coaches text
);


--
-- Name: team_franchise_numbers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_franchise_numbers (
    team_abbr text NOT NULL,
    franchise_id integer,
    section text NOT NULL,
    number text NOT NULL,
    player_name text NOT NULL,
    br_slug text,
    years text,
    source text DEFAULT 'br_crawler'::text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: team_franchise_players; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_franchise_players (
    team_abbr text NOT NULL,
    franchise_id integer,
    table_seq smallint DEFAULT 0 NOT NULL,
    row_idx integer NOT NULL,
    col_idx integer NOT NULL,
    col_header text,
    val text,
    source text DEFAULT 'br_crawler'::text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: team_franchise_playoffs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_franchise_playoffs (
    team_abbr text NOT NULL,
    franchise_id integer,
    season integer NOT NULL,
    opponent text NOT NULL,
    result text,
    source text DEFAULT 'basketball-reference'::text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: team_franchise_stats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_franchise_stats (
    team_abbr text NOT NULL,
    franchise_id integer,
    table_id text NOT NULL,
    table_seq smallint DEFAULT 0 NOT NULL,
    row_label text DEFAULT ''::text NOT NULL,
    data_stat text NOT NULL,
    val text,
    source text DEFAULT 'br_crawler'::text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: team_game_splits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_game_splits (
    id integer NOT NULL,
    season integer NOT NULL,
    team_abbr text NOT NULL,
    split_type text NOT NULL,
    games integer,
    pts numeric(6,2),
    fg_pct numeric(5,3),
    fg3_pct numeric(5,3),
    ft_pct numeric(5,3),
    reb integer,
    ast integer,
    stl integer,
    blk integer,
    tov integer,
    pf integer,
    plus_minus numeric(7,2),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: team_game_splits_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.team_game_splits_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: team_game_splits_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.team_game_splits_id_seq OWNED BY public.team_game_splits.id;


--
-- Name: team_hof; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_hof (
    id bigint NOT NULL,
    team_abbr character varying(3) NOT NULL,
    season character varying(7) NOT NULL,
    player_name text NOT NULL,
    br_slug text,
    scraped_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: team_hof_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.team_hof_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: team_hof_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.team_hof_id_seq OWNED BY public.team_hof.id;


--
-- Name: team_leaderboards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_leaderboards (
    team_abbr text NOT NULL,
    season integer NOT NULL,
    player_slug text NOT NULL,
    player_name text,
    leaderboard text NOT NULL,
    rank integer,
    source text DEFAULT 'br_crawler'::text,
    created_at timestamp without time zone DEFAULT now(),
    franchise_id integer
);


--
-- Name: team_lineups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_lineups (
    id bigint NOT NULL,
    team_abbr text NOT NULL,
    season integer NOT NULL,
    season_type character varying(20) DEFAULT 'Regular'::character varying NOT NULL,
    lineup_key text NOT NULL,
    br_player_id1 character varying,
    br_player_id2 character varying,
    br_player_id3 character varying,
    br_player_id4 character varying,
    br_player_id5 character varying,
    player_id1 bigint,
    player_id2 bigint,
    player_id3 bigint,
    player_id4 bigint,
    player_id5 bigint,
    player_name1 text,
    player_name2 text,
    player_name3 text,
    player_name4 text,
    player_name5 text,
    source text DEFAULT 'basketball-reference'::text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    mp text,
    diff_pts double precision,
    diff_fg double precision,
    diff_fga double precision,
    diff_fg_pct double precision,
    diff_fg3 double precision,
    diff_fg3a double precision,
    diff_fg3_pct double precision,
    diff_efg_pct double precision,
    diff_ft double precision,
    diff_fta double precision,
    diff_ft_pct double precision,
    diff_orb double precision,
    diff_orb_pct double precision,
    diff_drb double precision,
    diff_drb_pct double precision,
    diff_trb double precision,
    diff_trb_pct double precision,
    diff_ast double precision,
    diff_stl double precision,
    diff_blk double precision,
    diff_tov double precision,
    diff_pf double precision,
    franchise_id integer,
    group_size smallint
);


--
-- Name: team_lineups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.team_lineups_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: team_lineups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.team_lineups_id_seq OWNED BY public.team_lineups.id;


--
-- Name: team_logos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_logos (
    team_abbr text NOT NULL,
    season integer NOT NULL,
    logo_path text NOT NULL,
    logo_url text,
    franchise_id integer,
    fetched_at timestamp with time zone DEFAULT now()
);


--
-- Name: team_mapping; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.team_mapping AS
 SELECT id,
    team_abbr AS team_code,
    current_code,
    team_name,
    is_active,
    created_at
   FROM public.dim_teams;


--
-- Name: team_mapping_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.team_mapping_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: team_mapping_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.team_mapping_id_seq OWNED BY public.dim_teams.id;


--
-- Name: team_on_off; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_on_off (
    id bigint NOT NULL,
    team_abbr text NOT NULL,
    season integer NOT NULL,
    season_type character varying(20) DEFAULT 'Regular'::character varying NOT NULL,
    br_player_id character varying,
    player_id bigint,
    player_name text NOT NULL,
    on_mp integer,
    on_off_rtg double precision,
    on_pace double precision,
    on_efg_pct double precision,
    on_tov_pct double precision,
    on_orb_pct double precision,
    on_drb_pct double precision,
    on_trb_pct double precision,
    on_stl_pct double precision,
    on_blk_pct double precision,
    on_ast_pct double precision,
    off_mp integer,
    off_off_rtg double precision,
    off_pace double precision,
    off_efg_pct double precision,
    off_tov_pct double precision,
    off_orb_pct double precision,
    off_drb_pct double precision,
    off_trb_pct double precision,
    off_stl_pct double precision,
    off_blk_pct double precision,
    off_ast_pct double precision,
    diff_mp integer,
    diff_off_rtg double precision,
    diff_pace double precision,
    diff_efg_pct double precision,
    diff_tov_pct double precision,
    diff_orb_pct double precision,
    diff_drb_pct double precision,
    diff_trb_pct double precision,
    diff_stl_pct double precision,
    diff_blk_pct double precision,
    diff_ast_pct double precision,
    source text DEFAULT 'basketball-reference'::text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: team_on_off_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.team_on_off_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: team_on_off_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.team_on_off_id_seq OWNED BY public.team_on_off.id;


--
-- Name: team_page_raw; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_page_raw (
    team_abbr text NOT NULL,
    season integer NOT NULL,
    season_type text NOT NULL,
    table_id text NOT NULL,
    row_label text DEFAULT ''::text NOT NULL,
    data_stat text NOT NULL,
    val text,
    source text DEFAULT 'br_crawler'::text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: team_payroll; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_payroll (
    team_abbr character varying(8) NOT NULL,
    team_name character varying(64),
    season character varying(8) NOT NULL,
    salary_cap bigint,
    largest_guarantee bigint,
    largest_guarantee_player text,
    source_url text,
    scraped_at timestamp without time zone DEFAULT now() NOT NULL,
    total_2025_26 bigint,
    total_2026_27 bigint,
    total_2027_28 bigint,
    total_2028_29 bigint,
    total_2029_30 bigint,
    total_2030_31 bigint,
    total_guaranteed bigint,
    player_count integer
);


--
-- Name: team_pbp_raw; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_pbp_raw (
    team_abbr text NOT NULL,
    season integer NOT NULL,
    season_type text NOT NULL,
    table_id text NOT NULL,
    row_label text DEFAULT ''::text NOT NULL,
    data_stat text NOT NULL,
    val text,
    source text DEFAULT 'br_crawler'::text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: team_per_36; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_per_36 (
    team_abbr text NOT NULL,
    season integer NOT NULL,
    season_type text DEFAULT 'Regular'::text NOT NULL,
    player_slug text NOT NULL,
    player_name text,
    pos text,
    g integer,
    gs integer,
    mp integer,
    fg double precision,
    fga double precision,
    fg_pct double precision,
    x3p double precision,
    x3pa double precision,
    x3p_pct double precision,
    x2p double precision,
    x2pa double precision,
    x2p_pct double precision,
    efg_pct double precision,
    ft double precision,
    fta double precision,
    ft_pct double precision,
    orb double precision,
    drb double precision,
    trb double precision,
    ast double precision,
    stl double precision,
    blk double precision,
    tov double precision,
    pf double precision,
    pts double precision,
    awards text,
    source text DEFAULT 'br_crawler'::text,
    created_at timestamp without time zone DEFAULT now(),
    franchise_id integer
);


--
-- Name: team_referees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_referees (
    id bigint NOT NULL,
    team_abbr text NOT NULL,
    season integer NOT NULL,
    referee_slug text NOT NULL,
    referee_name text NOT NULL,
    rank smallint,
    g smallint,
    wins smallint,
    losses smallint,
    win_pct double precision,
    pace double precision,
    team_pts double precision,
    team_fta double precision,
    team_pf double precision,
    team_sfoul double precision,
    team_ofoul double precision,
    opp_pts double precision,
    opp_fta double precision,
    opp_pf double precision,
    opp_sfoul double precision,
    opp_ofoul double precision,
    diff_pts double precision,
    diff_fta double precision,
    diff_pf double precision,
    diff_sfoul double precision,
    diff_ofoul double precision,
    source text DEFAULT 'basketball-reference'::text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    franchise_id integer
);


--
-- Name: team_referees_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.team_referees_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: team_referees_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.team_referees_id_seq OWNED BY public.team_referees.id;


--
-- Name: team_roster; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_roster (
    team_abbr text NOT NULL,
    season integer NOT NULL,
    player_slug text NOT NULL,
    player_name text,
    jersey text,
    pos text,
    height text,
    weight text,
    birth_date text,
    experience text,
    college text,
    source text DEFAULT 'br_crawler'::text,
    created_at timestamp without time zone DEFAULT now(),
    franchise_id integer
);


--
-- Name: team_stats_per_100_poss; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_stats_per_100_poss (
    season bigint,
    lg text,
    team text,
    abbreviation text,
    playoffs boolean,
    g bigint,
    mp bigint,
    fg_per_100_poss double precision,
    fga_per_100_poss double precision,
    fg_percent double precision,
    x3p_per_100_poss double precision,
    x3pa_per_100_poss double precision,
    x3p_percent double precision,
    x2p_per_100_poss double precision,
    x2pa_per_100_poss double precision,
    x2p_percent double precision,
    ft_per_100_poss double precision,
    fta_per_100_poss double precision,
    ft_percent double precision,
    orb_per_100_poss double precision,
    drb_per_100_poss double precision,
    trb_per_100_poss double precision,
    ast_per_100_poss double precision,
    stl_per_100_poss double precision,
    blk_per_100_poss double precision,
    tov_per_100_poss double precision,
    pf_per_100_poss double precision,
    pts_per_100_poss double precision,
    opp_fg_per_100_poss real,
    opp_fga_per_100_poss real,
    opp_fg_percent real,
    opp_x3p_per_100_poss real,
    opp_x3pa_per_100_poss real,
    opp_x3p_percent real,
    opp_x2p_per_100_poss real,
    opp_x2pa_per_100_poss real,
    opp_x2p_percent real,
    opp_ft_per_100_poss real,
    opp_fta_per_100_poss real,
    opp_ft_percent real,
    opp_orb_per_100_poss real,
    opp_drb_per_100_poss real,
    opp_trb_per_100_poss real,
    opp_ast_per_100_poss real,
    opp_stl_per_100_poss real,
    opp_blk_per_100_poss real,
    opp_tov_per_100_poss real,
    opp_pf_per_100_poss real,
    opp_pts_per_100_poss real
);


--
-- Name: team_stats_per_game; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_stats_per_game (
    season bigint,
    lg text,
    team text,
    abbreviation text,
    playoffs boolean,
    g double precision,
    mp_per_game double precision,
    fg_per_game double precision,
    fga_per_game double precision,
    fg_percent double precision,
    x3p_per_game double precision,
    x3pa_per_game double precision,
    x3p_percent double precision,
    x2p_per_game double precision,
    x2pa_per_game double precision,
    x2p_percent double precision,
    ft_per_game double precision,
    fta_per_game double precision,
    ft_percent double precision,
    orb_per_game double precision,
    drb_per_game double precision,
    trb_per_game double precision,
    ast_per_game double precision,
    stl_per_game double precision,
    blk_per_game double precision,
    tov_per_game double precision,
    pf_per_game double precision,
    pts_per_game double precision,
    opp_fg_per_game real,
    opp_fga_per_game real,
    opp_fg_percent real,
    opp_x3p_per_game real,
    opp_x3pa_per_game real,
    opp_x3p_percent real,
    opp_x2p_per_game real,
    opp_x2pa_per_game real,
    opp_x2p_percent real,
    opp_ft_per_game real,
    opp_fta_per_game real,
    opp_ft_percent real,
    opp_orb_per_game real,
    opp_drb_per_game real,
    opp_trb_per_game real,
    opp_ast_per_game real,
    opp_stl_per_game real,
    opp_blk_per_game real,
    opp_tov_per_game real,
    opp_pf_per_game real,
    opp_pts_per_game real
);


--
-- Name: team_summaries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_summaries (
    season bigint,
    lg text,
    team text,
    abbreviation text,
    playoffs boolean,
    age double precision,
    w double precision,
    l double precision,
    pw double precision,
    pl double precision,
    mov double precision,
    sos double precision,
    srs double precision,
    o_rtg double precision,
    d_rtg double precision,
    n_rtg double precision,
    pace double precision,
    f_tr double precision,
    x3p_ar double precision,
    ts_percent double precision,
    e_fg_percent double precision,
    tov_percent double precision,
    orb_percent double precision,
    ft_fga double precision,
    opp_e_fg_percent double precision,
    opp_tov_percent double precision,
    drb_percent double precision,
    opp_ft_fga double precision,
    arena text,
    attend double precision,
    attend_g double precision,
    franchise_id integer
);


--
-- Name: team_totals; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.team_totals AS
 SELECT season,
    lg,
    team,
    abbreviation,
    playoffs,
    g,
    mp,
    fg,
    fga,
    fg_percent,
    x3p,
    x3pa,
    x3p_percent,
    x2p,
    x2pa,
    x2p_percent,
    ft,
    fta,
    ft_percent,
    orb,
    drb,
    trb,
    ast,
    stl,
    blk,
    tov,
    pf,
    pts,
    opp_fg,
    opp_fga,
    opp_fg_percent,
    opp_x3p,
    opp_x3pa,
    opp_x3p_percent,
    opp_x2p,
    opp_x2pa,
    opp_x2p_percent,
    opp_ft,
    opp_fta,
    opp_ft_percent,
    opp_orb,
    opp_drb,
    opp_trb,
    opp_ast,
    opp_stl,
    opp_blk,
    opp_tov,
    opp_pf,
    opp_pts
   FROM public.fact_team_season_stats;


--
-- Name: trade_semantics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_semantics (
    id integer NOT NULL,
    source_ref text NOT NULL,
    counterparties jsonb,
    players_out jsonb,
    players_in jsonb,
    picks jsonb,
    cash numeric,
    notes text,
    model text,
    parsed_at timestamp without time zone DEFAULT now()
);


--
-- Name: trade_semantics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.trade_semantics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: trade_semantics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.trade_semantics_id_seq OWNED BY public.trade_semantics.id;


--
-- Name: transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transactions (
    id integer NOT NULL,
    transaction_date date NOT NULL,
    team_abbr text,
    transaction_type text,
    description text NOT NULL,
    source text DEFAULT 'basketball-reference'::text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    crawl_date date DEFAULT CURRENT_DATE
);


--
-- Name: transactions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: transactions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.transactions_id_seq OWNED BY public.transactions.id;


--
-- Name: v_pbp_br_resolved; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_pbp_br_resolved AS
 SELECT pbp.id,
    pbp.gameid,
    pbp.season,
    pbp.eventnum,
    pbp.period,
    pbp.clock,
    pbp.clock_seconds,
    pbp.h_pts,
    pbp.a_pts,
    pbp.team,
    pbp.playerid,
    pbp.player,
    pbp.event_type,
    pbp.subtype,
    pbp.result,
    pbp.x,
    pbp.y,
    pbp.dist,
    pbp.description,
    pbp.current_team,
    pbp.eventmsgtype,
    pbp.eventmsgactiontype,
    pbp.homedescription,
    pbp.visitordescription,
    pbp.neutraldescription,
    pbp.scorehome,
    pbp.scorevisitor,
    pbp.scoremargin,
    pbp.pctimestring,
    pbp.player1_id,
    pbp.player1_name,
    pbp.player1_team_id,
    pbp.player1_team_abbreviation,
    pbp.player2_id,
    pbp.player2_name,
    pbp.player2_team_id,
    pbp.player2_team_abbreviation,
    pbp.player3_id,
    pbp.player3_name,
    pbp.player3_team_id,
    pbp.player3_team_abbreviation,
    pbp.source,
    pbp.br_player_id,
    pbp.action_verb,
    COALESCE(m.br_gid, pbp.gameid) AS gameid_resolved,
    m.nba_api_id AS gameid_api,
    m.espn_event
   FROM (public.play_by_play pbp
     LEFT JOIN public.game_id_map m ON (((pbp.gameid)::text = (m.nba_api_id)::text)));


--
-- Name: v_player_clutch_by_distance; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_player_clutch_by_distance AS
 SELECT season,
    team,
    player_slug,
        CASE
            WHEN (shot_distance IS NULL) THEN 'Unknown'::text
            WHEN (shot_distance <= 3) THEN '0-3 Rim'::text
            WHEN (shot_distance <= 10) THEN '4-10 ShortMid'::text
            WHEN (shot_distance <= 16) THEN '11-16 Mid'::text
            WHEN (shot_distance <= 23) THEN '17-23 LongTwo'::text
            WHEN (shot_distance <= 26) THEN '24-26 Three'::text
            ELSE '27+ DeepThree'::text
        END AS dist_bucket,
    count(*) FILTER (WHERE (shot_type = ANY (ARRAY['2pt'::text, '3pt'::text]))) AS fga,
    count(*) FILTER (WHERE ((shot_type = ANY (ARRAY['2pt'::text, '3pt'::text])) AND is_make)) AS fgm,
    round(((100.0 * (count(*) FILTER (WHERE ((shot_type = ANY (ARRAY['2pt'::text, '3pt'::text])) AND is_make)))::numeric) / (NULLIF(count(*) FILTER (WHERE (shot_type = ANY (ARRAY['2pt'::text, '3pt'::text]))), 0))::numeric), 1) AS fg_pct
   FROM public.fct_pbp_shots
  WHERE is_clutch
  GROUP BY season, team, player_slug,
        CASE
            WHEN (shot_distance IS NULL) THEN 'Unknown'::text
            WHEN (shot_distance <= 3) THEN '0-3 Rim'::text
            WHEN (shot_distance <= 10) THEN '4-10 ShortMid'::text
            WHEN (shot_distance <= 16) THEN '11-16 Mid'::text
            WHEN (shot_distance <= 23) THEN '17-23 LongTwo'::text
            WHEN (shot_distance <= 26) THEN '24-26 Three'::text
            ELSE '27+ DeepThree'::text
        END;


--
-- Name: v_player_env_metrics; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_player_env_metrics AS
 WITH team_agg AS (
         SELECT fact_player_season_stats.season,
            fact_player_season_stats.team,
            fact_player_season_stats.season_type,
            sum(COALESCE(fact_player_season_stats.x3p, (0)::double precision)) AS team_3pm,
            sum(COALESCE(fact_player_season_stats.x3pa, (0)::double precision)) AS team_3pa,
            sum(COALESCE(fact_player_season_stats.mp, (0)::double precision)) AS team_mp,
            sum((COALESCE(fact_player_season_stats.usg_percent, (0)::double precision) * COALESCE(fact_player_season_stats.mp, (0)::double precision))) AS team_usg_weighted
           FROM public.fact_player_season_stats
          WHERE ((fact_player_season_stats.team <> ALL (ARRAY['2TM'::text, '3TM'::text, '4TM'::text, '5TM'::text, 'TOT'::text])) AND ((COALESCE(fact_player_season_stats.season_type, 'Regular'::character varying))::text = 'Regular'::text))
          GROUP BY fact_player_season_stats.season, fact_player_season_stats.team, fact_player_season_stats.season_type
        )
 SELECT p.season,
    p.player_id,
    p.player,
    p.team,
    p.pos,
    p.g,
    p.mp,
        CASE
            WHEN ((t.team_3pa - COALESCE(p.x3pa, (0)::double precision)) > (0)::double precision) THEN round(((((((t.team_3pm - COALESCE(p.x3p, (0)::double precision)))::numeric)::double precision / (t.team_3pa - COALESCE(p.x3pa, (0)::double precision))) * (100)::double precision))::numeric, 1)
            ELSE NULL::numeric
        END AS space_rating,
        CASE
            WHEN (t.team_3pa > (0)::double precision) THEN round(((((((t.team_3pa - COALESCE(p.x3pa, (0)::double precision)))::numeric)::double precision / t.team_3pa) * (100)::double precision))::numeric, 1)
            ELSE NULL::numeric
        END AS teammate_3pa_share,
        CASE
            WHEN (p.usg_percent IS NOT NULL) THEN round(((((100)::double precision - p.usg_percent) / (4.0)::double precision))::numeric, 1)
            ELSE NULL::numeric
        END AS teammate_avg_usage,
    p.usg_percent AS player_usage,
        CASE
            WHEN (p.usg_percent IS NOT NULL) THEN round(((p.usg_percent - (((100)::double precision - p.usg_percent) / (4.0)::double precision)))::numeric, 1)
            ELSE NULL::numeric
        END AS usage_differential
   FROM (public.fact_player_season_stats p
     JOIN team_agg t ON (((p.season = t.season) AND (p.team = t.team) AND ((COALESCE(p.season_type, 'Regular'::character varying))::text = (t.season_type)::text))))
  WHERE ((p.team <> ALL (ARRAY['2TM'::text, '3TM'::text, '4TM'::text, '5TM'::text, 'TOT'::text])) AND ((COALESCE(p.season_type, 'Regular'::character varying))::text = 'Regular'::text) AND (p.mp > (0)::double precision));


--
-- Name: v_player_onoff_rating; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_player_onoff_rating AS
 WITH game_pm AS (
         SELECT g.season,
            g.player,
            g.team,
            g.plus_minus,
                CASE
                    WHEN ((g.team)::text = d.home_team_abbr) THEN (d.home_pts - d.away_pts)
                    WHEN ((g.team)::text = d.away_team_abbr) THEN (d.away_pts - d.home_pts)
                    ELSE NULL::integer
                END AS team_game_pm
           FROM (public.player_gamelog g
             JOIN public.dim_games d ON ((((g.gameid)::text = d.game_id) OR (lpad((g.gameid)::text, 10, '0'::text) = d.game_id))))
          WHERE ((g.plus_minus IS NOT NULL) AND (g.season IS NOT NULL) AND (g.team IS NOT NULL) AND ((g.team)::text <> ''::text) AND (g.player IS NOT NULL) AND ((g.player)::text <> ''::text))
        ), season_agg AS (
         SELECT game_pm.season,
            game_pm.player,
            game_pm.team,
            count(*) AS games_played,
            sum(game_pm.plus_minus) AS total_oncourt_pm,
            sum(game_pm.team_game_pm) AS total_team_pm,
            sum((game_pm.team_game_pm - game_pm.plus_minus)) AS total_offcourt_pm
           FROM game_pm
          WHERE (game_pm.team_game_pm IS NOT NULL)
          GROUP BY game_pm.season, game_pm.player, game_pm.team
        )
 SELECT s.season,
    s.player,
    s.team,
    s.games_played,
    round((((((s.total_oncourt_pm)::numeric)::double precision / NULLIF(f.mp, (0)::double precision)) * (48)::double precision))::numeric, 1) AS on_court_net_48,
    round((((((s.total_offcourt_pm)::numeric)::double precision / NULLIF((((48 * f.g))::double precision - f.mp), (0)::double precision)) * (48)::double precision))::numeric, 1) AS off_court_net_48,
    round(((((((s.total_oncourt_pm)::numeric)::double precision / NULLIF(f.mp, (0)::double precision)) * (48)::double precision) - ((((s.total_offcourt_pm)::numeric)::double precision / NULLIF((((48 * f.g))::double precision - f.mp), (0)::double precision)) * (48)::double precision)))::numeric, 1) AS on_off_rating,
    f.mp AS total_minutes,
        CASE
            WHEN (f.mp >= (1000)::double precision) THEN 'High'::text
            WHEN (f.mp >= (500)::double precision) THEN 'Medium'::text
            ELSE 'Low'::text
        END AS sample_reliability
   FROM (season_agg s
     JOIN public.fact_player_season_stats f ON (((s.season = f.season) AND ((s.player)::text = f.player) AND ((s.team)::text = f.team))))
  WHERE (((COALESCE(f.season_type, 'Regular'::character varying))::text = 'Regular'::text) AND (f.team <> ALL (ARRAY['2TM'::text, '3TM'::text, '4TM'::text, '5TM'::text, 'TOT'::text])) AND (f.mp > (0)::double precision) AND (f.g > 0));


--
-- Name: v_player_role_tags; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_player_role_tags AS
 SELECT season,
    player_id,
    player,
    team,
    pos,
    g,
    mp,
    usg_percent,
    ast_percent,
    x3p_ar,
    x3pa,
    x3p_percent,
    orb_percent,
    trb_percent,
    stl_percent,
    blk_percent,
    f_tr,
        CASE
            WHEN ((usg_percent >= (24)::double precision) AND (ast_percent >= (32)::double precision) AND (pos ~~ '%PG%'::text)) THEN 'Floor General'::text
            WHEN ((usg_percent >= (20)::double precision) AND (ast_percent >= (25)::double precision) AND ((pos ~~ '%SF%'::text) OR (pos ~~ '%PF%'::text))) THEN 'Point Forward'::text
            WHEN ((x3pa >= (100)::double precision) AND (x3p_percent >= (0.35)::double precision) AND ((pos ~~ '%C%'::text) OR (pos ~~ '%PF%'::text))) THEN 'Stretch Big'::text
            WHEN ((x3pa >= (150)::double precision) AND (stl_percent >= (2.0)::double precision) AND ((pos ~~ '%SG%'::text) OR (pos ~~ '%SF%'::text))) THEN '3&D Wing'::text
            WHEN ((orb_percent >= (10)::double precision) AND (x3pa < (50)::double precision) AND (pos ~~ '%C%'::text) AND (ast_percent < (15)::double precision)) THEN 'Rim Runner'::text
            WHEN ((trb_percent >= (15)::double precision) AND (ast_percent < (12)::double precision) AND ((pos ~~ '%PF%'::text) OR (pos ~~ '%C%'::text))) THEN 'Glass Cleaner'::text
            WHEN ((f_tr >= (0.30)::double precision) AND (x3p_ar < (0.20)::double precision) AND ((pos ~~ '%SG%'::text) OR (pos ~~ '%SF%'::text))) THEN 'Slashing Wing'::text
            WHEN ((x3p_ar >= (0.50)::double precision) AND (usg_percent < (18)::double precision) AND (x3pa >= (100)::double precision)) THEN 'Spot Up Shooter'::text
            WHEN ((usg_percent >= (18)::double precision) AND (ast_percent >= (20)::double precision) AND (pos ~~ '%SG%'::text)) THEN 'Secondary Ball Handler'::text
            WHEN ((blk_percent >= (4.0)::double precision) AND (trb_percent >= (12)::double precision) AND (pos ~~ '%C%'::text)) THEN 'Defensive Anchor'::text
            ELSE 'Role Player'::text
        END AS tactical_role,
        CASE
            WHEN ((usg_percent >= (24)::double precision) AND (ast_percent >= (32)::double precision) AND (pos ~~ '%PG%'::text)) THEN '核心控卫: 高持球高组织'::text
            WHEN ((usg_percent >= (20)::double precision) AND (ast_percent >= (25)::double precision) AND ((pos ~~ '%SF%'::text) OR (pos ~~ '%PF%'::text))) THEN '组织前锋: 锋线策应核心'::text
            WHEN ((x3pa >= (100)::double precision) AND (x3p_percent >= (0.35)::double precision) AND ((pos ~~ '%C%'::text) OR (pos ~~ '%PF%'::text))) THEN '空间型内线: 拉开空间'::text
            WHEN ((x3pa >= (150)::double precision) AND (stl_percent >= (2.0)::double precision) AND ((pos ~~ '%SG%'::text) OR (pos ~~ '%SF%'::text))) THEN '3D侧翼: 三分+防守'::text
            WHEN ((orb_percent >= (10)::double precision) AND (x3pa < (50)::double precision) AND (pos ~~ '%C%'::text) AND (ast_percent < (15)::double precision)) THEN '吃饼中锋: 篮下终结'::text
            WHEN ((trb_percent >= (15)::double precision) AND (ast_percent < (12)::double precision) AND ((pos ~~ '%PF%'::text) OR (pos ~~ '%C%'::text))) THEN '篮板型内线: 护框拼抢'::text
            WHEN ((f_tr >= (0.30)::double precision) AND (x3p_ar < (0.20)::double precision) AND ((pos ~~ '%SG%'::text) OR (pos ~~ '%SF%'::text))) THEN '突破型侧翼: 杀伤制造'::text
            WHEN ((x3p_ar >= (0.50)::double precision) AND (usg_percent < (18)::double precision) AND (x3pa >= (100)::double precision)) THEN '定点射手: 空间拉开'::text
            WHEN ((usg_percent >= (18)::double precision) AND (ast_percent >= (20)::double precision) AND (pos ~~ '%SG%'::text)) THEN '副控卫: 第二持球点'::text
            WHEN ((blk_percent >= (4.0)::double precision) AND (trb_percent >= (12)::double precision) AND (pos ~~ '%C%'::text)) THEN '防守核心: 护框大闸'::text
            ELSE '角色球员: 战术补充'::text
        END AS role_description
   FROM public.fact_player_season_stats
  WHERE (((COALESCE(season_type, 'Regular'::character varying))::text = 'Regular'::text) AND (mp > (0)::double precision) AND (team <> ALL (ARRAY['2TM'::text, '3TM'::text, '4TM'::text, '5TM'::text, 'TOT'::text])));


--
-- Name: v_player_tactical_profile; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_player_tactical_profile AS
 SELECT p.season,
    p.player_id,
    p.player,
    p.team,
    p.pos,
    p.age,
    p.g,
    p.mp,
    p.pts,
    p.ast,
    p.trb,
    e.space_rating,
    e.teammate_avg_usage,
    e.usage_differential,
    r.tactical_role,
    r.role_description,
    o.on_court_net_48,
    o.off_court_net_48,
    o.on_off_rating,
    o.sample_reliability,
    p.per,
    p.usg_percent,
    p.ts_percent,
    p.bpm,
    p.vorp,
    p.o_rtg,
    p.d_rtg
   FROM (((public.fact_player_season_stats p
     LEFT JOIN public.v_player_env_metrics e ON (((p.season = e.season) AND (p.player_id = e.player_id) AND (p.team = e.team))))
     LEFT JOIN public.v_player_role_tags r ON (((p.season = r.season) AND (p.player_id = r.player_id) AND (p.team = r.team))))
     LEFT JOIN public.v_player_onoff_rating o ON (((p.season = o.season) AND (p.player = (o.player)::text) AND (p.team = (o.team)::text))))
  WHERE (((COALESCE(p.season_type, 'Regular'::character varying))::text = 'Regular'::text) AND (p.team <> ALL (ARRAY['2TM'::text, '3TM'::text, '4TM'::text, '5TM'::text, 'TOT'::text])) AND (p.mp > (0)::double precision));


--
-- Name: v_player_growth_tracking; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_player_growth_tracking AS
 WITH base AS (
         SELECT v_player_tactical_profile.season,
            v_player_tactical_profile.player_id,
            v_player_tactical_profile.player,
            v_player_tactical_profile.team,
            v_player_tactical_profile.pos,
            v_player_tactical_profile.age,
            v_player_tactical_profile.mp,
            v_player_tactical_profile.pts,
            v_player_tactical_profile.ast,
            v_player_tactical_profile.trb,
            v_player_tactical_profile.per,
            v_player_tactical_profile.usg_percent,
            v_player_tactical_profile.ts_percent,
            v_player_tactical_profile.bpm,
            v_player_tactical_profile.vorp,
            v_player_tactical_profile.on_off_rating,
            v_player_tactical_profile.space_rating,
            v_player_tactical_profile.tactical_role,
            v_player_tactical_profile.on_court_net_48,
            lag(v_player_tactical_profile.age) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_age,
            lag(v_player_tactical_profile.pts) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_pts,
            lag(v_player_tactical_profile.ast) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_ast,
            lag(v_player_tactical_profile.trb) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_trb,
            lag(v_player_tactical_profile.per) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_per,
            lag(v_player_tactical_profile.usg_percent) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_usg,
            lag(v_player_tactical_profile.ts_percent) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_ts,
            lag(v_player_tactical_profile.bpm) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_bpm,
            lag(v_player_tactical_profile.vorp) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_vorp,
            lag(v_player_tactical_profile.on_off_rating) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_onoff,
            lag(v_player_tactical_profile.space_rating) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_space,
            lag(v_player_tactical_profile.tactical_role) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_role,
            lag(v_player_tactical_profile.mp) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_mp,
            lag(v_player_tactical_profile.team) OVER (PARTITION BY v_player_tactical_profile.player_id ORDER BY v_player_tactical_profile.season) AS prev_team
           FROM public.v_player_tactical_profile
        ), deltas AS (
         SELECT base.season,
            base.player_id,
            base.player,
            base.team,
            base.pos,
            base.age,
            base.mp,
            base.tactical_role,
            base.prev_role,
            base.prev_team,
            (COALESCE(base.per, (0)::double precision) - COALESCE(base.prev_per, (0)::double precision)) AS per_delta,
            (COALESCE(base.bpm, (0)::double precision) - COALESCE(base.prev_bpm, (0)::double precision)) AS bpm_delta,
            (COALESCE(base.vorp, (0)::double precision) - COALESCE(base.prev_vorp, (0)::double precision)) AS vorp_delta,
            (COALESCE(base.usg_percent, (0)::double precision) - COALESCE(base.prev_usg, (0)::double precision)) AS usg_delta,
            round((((COALESCE(base.ts_percent, (0)::double precision) - COALESCE(base.prev_ts, (0)::double precision)) * (100)::double precision))::numeric, 1) AS ts_delta,
            (COALESCE(base.pts, (0)::bigint) - COALESCE(base.prev_pts, (0)::bigint)) AS pts_delta,
            (COALESCE(base.ast, (0)::bigint) - COALESCE(base.prev_ast, (0)::bigint)) AS ast_delta,
            (COALESCE(base.trb, (0)::double precision) - COALESCE(base.prev_trb, (0)::double precision)) AS trb_delta,
            (COALESCE(base.on_off_rating, (0)::numeric) - COALESCE(base.prev_onoff, (0)::numeric)) AS onoff_delta,
            (COALESCE(base.space_rating, (0)::numeric) - COALESCE(base.prev_space, (0)::numeric)) AS space_delta,
            (COALESCE(base.mp, (0)::double precision) - COALESCE(base.prev_mp, (0)::double precision)) AS mp_delta,
                CASE
                    WHEN ((base.prev_per IS NOT NULL) AND (base.prev_per <> (0)::double precision)) THEN round(((((base.per - base.prev_per) / abs(base.prev_per)) * (100)::double precision))::numeric, 1)
                    ELSE NULL::numeric
                END AS per_pct_change,
                CASE
                    WHEN ((base.prev_bpm IS NOT NULL) AND (base.prev_bpm <> (0)::double precision)) THEN round(((((base.bpm - base.prev_bpm) / abs(base.prev_bpm)) * (100)::double precision))::numeric, 1)
                    ELSE NULL::numeric
                END AS bpm_pct_change,
                CASE
                    WHEN ((base.prev_usg IS NOT NULL) AND (base.prev_usg <> (0)::double precision)) THEN round(((((base.usg_percent - base.prev_usg) / abs(base.prev_usg)) * (100)::double precision))::numeric, 1)
                    ELSE NULL::numeric
                END AS usg_pct_change,
                CASE
                    WHEN ((base.prev_pts IS NOT NULL) AND (base.prev_pts <> 0)) THEN round(((((base.pts - base.prev_pts) / abs(base.prev_pts)) * 100))::numeric, 1)
                    ELSE NULL::numeric
                END AS pts_pct_change,
                CASE
                    WHEN ((base.prev_vorp IS NOT NULL) AND (base.prev_vorp <> (0)::double precision)) THEN round(((((base.vorp - base.prev_vorp) / abs(base.prev_vorp)) * (100)::double precision))::numeric, 1)
                    ELSE NULL::numeric
                END AS vorp_pct_change,
                CASE
                    WHEN ((base.prev_space IS NOT NULL) AND (base.prev_space <> (0)::numeric)) THEN round((((base.space_rating - base.prev_space) / abs(base.prev_space)) * (100)::numeric), 1)
                    ELSE NULL::numeric
                END AS space_pct_change,
                CASE
                    WHEN ((base.prev_onoff IS NOT NULL) AND (base.prev_onoff <> (0)::numeric)) THEN round((((base.on_off_rating - base.prev_onoff) / abs(base.prev_onoff)) * (100)::numeric), 1)
                    ELSE NULL::numeric
                END AS onoff_pct_change,
            base.per,
            base.prev_per,
            base.bpm,
            base.prev_bpm,
            base.vorp,
            base.prev_vorp,
            base.usg_percent,
            base.prev_usg,
            base.ts_percent,
            base.prev_ts,
            base.pts,
            base.prev_pts,
            base.ast,
            base.prev_ast,
            base.trb,
            base.prev_trb,
            base.on_off_rating,
            base.prev_onoff,
            base.space_rating,
            base.prev_space
           FROM base
        )
 SELECT season,
    player_id,
    player,
    team,
    pos,
    age,
    mp,
    tactical_role,
    prev_role,
    prev_team,
    per_delta,
    bpm_delta,
    vorp_delta,
    usg_delta,
    ts_delta,
    pts_delta,
    ast_delta,
    trb_delta,
    onoff_delta,
    space_delta,
    mp_delta,
    per_pct_change,
    bpm_pct_change,
    usg_pct_change,
    pts_pct_change,
    vorp_pct_change,
    space_pct_change,
    onoff_pct_change,
    per,
    prev_per,
    bpm,
    prev_bpm,
    vorp,
    prev_vorp,
    usg_percent,
    prev_usg,
    ts_percent,
    prev_ts,
    pts,
    prev_pts,
    ast,
    prev_ast,
    trb,
    prev_trb,
    on_off_rating,
    prev_onoff,
    space_rating,
    prev_space,
        CASE
            WHEN ((abs(COALESCE(per_pct_change, (0)::numeric)) > (15)::numeric) OR (abs(COALESCE(bpm_pct_change, (0)::numeric)) > (15)::numeric) OR (abs(COALESCE(usg_pct_change, (0)::numeric)) > (15)::numeric) OR (abs(COALESCE(pts_pct_change, (0)::numeric)) > (15)::numeric) OR (abs(COALESCE(vorp_pct_change, (0)::numeric)) > (15)::numeric) OR (abs(COALESCE(space_pct_change, (0)::numeric)) > (15)::numeric) OR (abs(COALESCE(onoff_pct_change, (0)::numeric)) > (15)::numeric)) THEN true
            ELSE false
        END AS is_evolution_node,
        CASE
            WHEN ((COALESCE(per_pct_change, (0)::numeric) > (15)::numeric) OR (COALESCE(bpm_pct_change, (0)::numeric) > (15)::numeric) OR (COALESCE(vorp_pct_change, (0)::numeric) > (15)::numeric) OR (COALESCE(pts_pct_change, (0)::numeric) > (15)::numeric)) THEN 'Breakout'::text
            WHEN ((COALESCE(per_pct_change, (0)::numeric) < ('-15'::integer)::numeric) OR (COALESCE(bpm_pct_change, (0)::numeric) < ('-15'::integer)::numeric) OR (COALESCE(vorp_pct_change, (0)::numeric) < ('-15'::integer)::numeric) OR (COALESCE(pts_pct_change, (0)::numeric) < ('-15'::integer)::numeric)) THEN 'Decline'::text
            WHEN (COALESCE(usg_pct_change, (0)::numeric) > (15)::numeric) THEN 'Role Expansion'::text
            WHEN (COALESCE(usg_pct_change, (0)::numeric) < ('-15'::integer)::numeric) THEN 'Role Reduction'::text
            WHEN ((tactical_role <> prev_role) AND (prev_role IS NOT NULL)) THEN 'Role Change'::text
            ELSE 'Stable'::text
        END AS evolution_type,
        CASE
            WHEN ((tactical_role <> prev_role) AND (prev_role IS NOT NULL)) THEN ((('角色转变: '::text || COALESCE(prev_role, '?'::text)) || ' → '::text) || COALESCE(tactical_role, '?'::text))
            WHEN (COALESCE(per_pct_change, (0)::numeric) > (15)::numeric) THEN (('显著进步: PER +'::text || (COALESCE(per_pct_change, (0)::numeric))::text) || '%'::text)
            WHEN (COALESCE(per_pct_change, (0)::numeric) < ('-15'::integer)::numeric) THEN (('明显退步: PER '::text || (COALESCE(per_pct_change, (0)::numeric))::text) || '%'::text)
            WHEN (COALESCE(usg_pct_change, (0)::numeric) > (15)::numeric) THEN (('球权增加: USG +'::text || (COALESCE(usg_pct_change, (0)::numeric))::text) || '%'::text)
            WHEN (COALESCE(space_pct_change, (0)::numeric) > (15)::numeric) THEN (('空间改善: 队友3P% +'::text || (COALESCE(space_pct_change, (0)::numeric))::text) || '%'::text)
            ELSE '赛季过渡'::text
        END AS evolution_description
   FROM deltas;


--
-- Name: v_player_shot_stats; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_player_shot_stats AS
 SELECT season,
    team,
    player_slug,
    count(*) FILTER (WHERE (shot_type = ANY (ARRAY['2pt'::text, '3pt'::text]))) AS fga,
    count(*) FILTER (WHERE ((shot_type = ANY (ARRAY['2pt'::text, '3pt'::text])) AND is_make)) AS fgm,
    count(*) FILTER (WHERE (shot_type = '3pt'::text)) AS fga_3,
    count(*) FILTER (WHERE ((shot_type = '3pt'::text) AND is_make)) AS fgm_3,
    count(*) FILTER (WHERE (shot_type = 'ft'::text)) AS fta,
    count(*) FILTER (WHERE ((shot_type = 'ft'::text) AND is_make)) AS ftm,
    count(*) FILTER (WHERE (is_eop AND (shot_type = ANY (ARRAY['2pt'::text, '3pt'::text])))) AS eop_fga,
    count(*) FILTER (WHERE (is_eop AND (shot_type = ANY (ARRAY['2pt'::text, '3pt'::text])) AND is_make)) AS eop_fgm,
    count(*) FILTER (WHERE (is_clutch AND (shot_type = ANY (ARRAY['2pt'::text, '3pt'::text])))) AS clutch_fga,
    count(*) FILTER (WHERE (is_clutch AND (shot_type = ANY (ARRAY['2pt'::text, '3pt'::text])) AND is_make)) AS clutch_fgm
   FROM public.fct_pbp_shots
  GROUP BY season, team, player_slug;


--
-- Name: v_team_clutch_shooting; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_team_clutch_shooting AS
 WITH clutch_fg AS (
         SELECT fct_pbp_shots.season,
            fct_pbp_shots.game_id,
            fct_pbp_shots.team,
            fct_pbp_shots.is_make
           FROM public.fct_pbp_shots
          WHERE (fct_pbp_shots.is_clutch AND (fct_pbp_shots.shot_type = ANY (ARRAY['2pt'::text, '3pt'::text])))
        ), team_games AS (
         SELECT DISTINCT fct_pbp_shots.season,
            fct_pbp_shots.game_id,
            fct_pbp_shots.team AS tteam
           FROM public.fct_pbp_shots
          WHERE (fct_pbp_shots.shot_type = ANY (ARRAY['2pt'::text, '3pt'::text]))
        )
 SELECT tg.season,
    tg.tteam AS team,
    count(*) FILTER (WHERE (c.team = tg.tteam)) AS clutch_fga,
    count(*) FILTER (WHERE ((c.team = tg.tteam) AND c.is_make)) AS clutch_fgm,
    round(((100.0 * (count(*) FILTER (WHERE ((c.team = tg.tteam) AND c.is_make)))::numeric) / (NULLIF(count(*) FILTER (WHERE (c.team = tg.tteam)), 0))::numeric), 1) AS clutch_fg_pct,
    count(*) FILTER (WHERE (c.team <> tg.tteam)) AS opp_clutch_fga,
    count(*) FILTER (WHERE ((c.team <> tg.tteam) AND c.is_make)) AS opp_clutch_fgm,
    round(((100.0 * (count(*) FILTER (WHERE ((c.team <> tg.tteam) AND c.is_make)))::numeric) / (NULLIF(count(*) FILTER (WHERE (c.team <> tg.tteam)), 0))::numeric), 1) AS opp_clutch_fg_pct
   FROM (team_games tg
     JOIN clutch_fg c ON (((c.game_id = tg.game_id) AND (c.season = tg.season))))
  GROUP BY tg.season, tg.tteam;


--
-- Name: v_team_fga_share; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_team_fga_share AS
 WITH team_tot AS (
         SELECT v_player_shot_stats.season,
            v_player_shot_stats.team,
            sum(v_player_shot_stats.fga) AS tfga,
            sum(v_player_shot_stats.fgm) AS tfgm
           FROM public.v_player_shot_stats
          GROUP BY v_player_shot_stats.season, v_player_shot_stats.team
        )
 SELECT s.season,
    s.team,
    s.player_slug,
    s.fga,
    s.fgm,
    row_number() OVER (PARTITION BY s.season, s.team ORDER BY s.fga DESC) AS rnk,
    round(((100.0 * (s.fga)::numeric) / NULLIF(t.tfga, (0)::numeric)), 1) AS fga_share_pct,
    round(((100.0 * (s.fgm)::numeric) / NULLIF(t.tfgm, (0)::numeric)), 1) AS fgm_share_pct
   FROM (public.v_player_shot_stats s
     JOIN team_tot t ON (((t.season = s.season) AND (t.team = s.team))));


--
-- Name: v_unified_games; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_unified_games AS
 SELECT game_id,
    game_date,
    season,
    season_type,
    home_team_abbr,
    away_team_abbr,
    home_pts,
    away_pts,
    nba_api_id,
    br_crawled_id,
    'games_table'::text AS source
   FROM public.dim_games;


--
-- Name: workspace_charts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_charts (
    id integer NOT NULL,
    workspace_id integer NOT NULL,
    name text DEFAULT 'chart'::text NOT NULL,
    chart_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: workspace_charts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.workspace_charts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: workspace_charts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.workspace_charts_id_seq OWNED BY public.workspace_charts.id;


--
-- Name: workspace_datasets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_datasets (
    id integer NOT NULL,
    workspace_id integer NOT NULL,
    dataset_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: workspace_datasets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.workspace_datasets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: workspace_datasets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.workspace_datasets_id_seq OWNED BY public.workspace_datasets.id;


--
-- Name: workspace_formulas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_formulas (
    id integer NOT NULL,
    workspace_id integer NOT NULL,
    formula_id integer NOT NULL
);


--
-- Name: workspace_formulas_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.workspace_formulas_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: workspace_formulas_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.workspace_formulas_id_seq OWNED BY public.workspace_formulas.id;


--
-- Name: workspaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspaces (
    id integer NOT NULL,
    owner_id integer DEFAULT 1 NOT NULL,
    name text NOT NULL,
    description text,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: workspaces_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.workspaces_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: workspaces_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.workspaces_id_seq OWNED BY public.workspaces.id;


--
-- Name: play_by_play_p_1997; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_1997 FOR VALUES FROM (1997) TO (1998);


--
-- Name: play_by_play_p_1998; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_1998 FOR VALUES FROM (1998) TO (1999);


--
-- Name: play_by_play_p_1999; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_1999 FOR VALUES FROM (1999) TO (2000);


--
-- Name: play_by_play_p_2000; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2000 FOR VALUES FROM (2000) TO (2001);


--
-- Name: play_by_play_p_2001; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2001 FOR VALUES FROM (2001) TO (2002);


--
-- Name: play_by_play_p_2002; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2002 FOR VALUES FROM (2002) TO (2003);


--
-- Name: play_by_play_p_2003; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2003 FOR VALUES FROM (2003) TO (2004);


--
-- Name: play_by_play_p_2004; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2004 FOR VALUES FROM (2004) TO (2005);


--
-- Name: play_by_play_p_2005; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2005 FOR VALUES FROM (2005) TO (2006);


--
-- Name: play_by_play_p_2006; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2006 FOR VALUES FROM (2006) TO (2007);


--
-- Name: play_by_play_p_2007; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2007 FOR VALUES FROM (2007) TO (2008);


--
-- Name: play_by_play_p_2008; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2008 FOR VALUES FROM (2008) TO (2009);


--
-- Name: play_by_play_p_2009; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2009 FOR VALUES FROM (2009) TO (2010);


--
-- Name: play_by_play_p_2010; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2010 FOR VALUES FROM (2010) TO (2011);


--
-- Name: play_by_play_p_2011; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2011 FOR VALUES FROM (2011) TO (2012);


--
-- Name: play_by_play_p_2012; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2012 FOR VALUES FROM (2012) TO (2013);


--
-- Name: play_by_play_p_2013; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2013 FOR VALUES FROM (2013) TO (2014);


--
-- Name: play_by_play_p_2014; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2014 FOR VALUES FROM (2014) TO (2015);


--
-- Name: play_by_play_p_2015; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2015 FOR VALUES FROM (2015) TO (2016);


--
-- Name: play_by_play_p_2016; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2016 FOR VALUES FROM (2016) TO (2017);


--
-- Name: play_by_play_p_2017; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2017 FOR VALUES FROM (2017) TO (2018);


--
-- Name: play_by_play_p_2018; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2018 FOR VALUES FROM (2018) TO (2019);


--
-- Name: play_by_play_p_2019; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2019 FOR VALUES FROM (2019) TO (2020);


--
-- Name: play_by_play_p_2020; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2020 FOR VALUES FROM (2020) TO (2021);


--
-- Name: play_by_play_p_2021; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2021 FOR VALUES FROM (2021) TO (2022);


--
-- Name: play_by_play_p_2022; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2022 FOR VALUES FROM (2022) TO (2023);


--
-- Name: play_by_play_p_2023; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2023 FOR VALUES FROM (2023) TO (2024);


--
-- Name: play_by_play_p_2024; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2024 FOR VALUES FROM (2024) TO (2025);


--
-- Name: play_by_play_p_2025; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2025 FOR VALUES FROM (2025) TO (2026);


--
-- Name: play_by_play_p_2026; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2026 FOR VALUES FROM (2026) TO (2027);


--
-- Name: play_by_play_p_2027; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_2027 FOR VALUES FROM (2027) TO (2028);


--
-- Name: play_by_play_p_default; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ATTACH PARTITION public.play_by_play_p_default DEFAULT;


--
-- Name: external_player_status id; Type: DEFAULT; Schema: analytics; Owner: -
--

ALTER TABLE ONLY analytics.external_player_status ALTER COLUMN id SET DEFAULT nextval('analytics.external_player_status_id_seq'::regclass);


--
-- Name: analysis_flows id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analysis_flows ALTER COLUMN id SET DEFAULT nextval('public.analysis_flows_id_seq'::regclass);


--
-- Name: backfill_review id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backfill_review ALTER COLUMN id SET DEFAULT nextval('public.backfill_review_id_seq'::regclass);


--
-- Name: coach_stats id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coach_stats ALTER COLUMN id SET DEFAULT nextval('public.coach_stats_id_seq'::regclass);


--
-- Name: crawl_failures id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crawl_failures ALTER COLUMN id SET DEFAULT nextval('public.crawl_failures_id_seq'::regclass);


--
-- Name: dim_franchise franchise_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dim_franchise ALTER COLUMN franchise_id SET DEFAULT nextval('public.dim_franchise_franchise_id_seq'::regclass);


--
-- Name: dim_teams id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dim_teams ALTER COLUMN id SET DEFAULT nextval('public.team_mapping_id_seq'::regclass);


--
-- Name: draft_combine id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft_combine ALTER COLUMN id SET DEFAULT nextval('public.draft_combine_id_seq'::regclass);


--
-- Name: espn_boxscore id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.espn_boxscore ALTER COLUMN id SET DEFAULT nextval('public.espn_boxscore_id_seq'::regclass);


--
-- Name: fact_player_season_stats id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_player_season_stats ALTER COLUMN id SET DEFAULT nextval('public.fact_player_season_stats_id_seq'::regclass);


--
-- Name: fct_pbp_shots id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fct_pbp_shots ALTER COLUMN id SET DEFAULT nextval('public.fct_pbp_shots_id_seq'::regclass);


--
-- Name: game_id_map id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.game_id_map ALTER COLUMN id SET DEFAULT nextval('public.game_id_map_id_seq'::regclass);


--
-- Name: injuries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.injuries ALTER COLUMN id SET DEFAULT nextval('public.injuries_id_seq'::regclass);


--
-- Name: league_salary_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.league_salary_rules ALTER COLUMN id SET DEFAULT nextval('public.league_salary_rules_id_seq'::regclass);


--
-- Name: meta_data_verification id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meta_data_verification ALTER COLUMN id SET DEFAULT nextval('public.meta_data_verification_id_seq'::regclass);


--
-- Name: pbp_parse_issues id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pbp_parse_issues ALTER COLUMN id SET DEFAULT nextval('public.pbp_parse_issues_id_seq'::regclass);


--
-- Name: pbp_semantic id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pbp_semantic ALTER COLUMN id SET DEFAULT nextval('public.pbp_semantic_id_seq'::regclass);


--
-- Name: play_by_play id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ALTER COLUMN id SET DEFAULT nextval('public.play_by_play_new_id_seq'::regclass);


--
-- Name: player_career_honors id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_career_honors ALTER COLUMN id SET DEFAULT nextval('public.player_career_honors_id_seq'::regclass);


--
-- Name: player_career_totals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_career_totals ALTER COLUMN id SET DEFAULT nextval('public.player_career_totals_id_seq'::regclass);


--
-- Name: player_gamelog id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_gamelog ALTER COLUMN id SET DEFAULT nextval('public.player_gamelog_id_seq'::regclass);


--
-- Name: player_lineups id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_lineups ALTER COLUMN id SET DEFAULT nextval('public.player_lineups_id_seq'::regclass);


--
-- Name: player_name_unified id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_name_unified ALTER COLUMN id SET DEFAULT nextval('public.player_name_unified_id_seq'::regclass);


--
-- Name: player_salaries_historical id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_salaries_historical ALTER COLUMN id SET DEFAULT nextval('public.player_salaries_historical_id_seq'::regclass);


--
-- Name: player_season_splits id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_season_splits ALTER COLUMN id SET DEFAULT nextval('public.player_season_splits_id_seq'::regclass);


--
-- Name: starting_lineups id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.starting_lineups ALTER COLUMN id SET DEFAULT nextval('public.starting_lineups_id_seq'::regclass);


--
-- Name: team_depth_chart id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_depth_chart ALTER COLUMN id SET DEFAULT nextval('public.team_depth_chart_id_seq'::regclass);


--
-- Name: team_executives id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_executives ALTER COLUMN id SET DEFAULT nextval('public.team_executives_id_seq'::regclass);


--
-- Name: team_game_splits id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_game_splits ALTER COLUMN id SET DEFAULT nextval('public.team_game_splits_id_seq'::regclass);


--
-- Name: team_hof id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_hof ALTER COLUMN id SET DEFAULT nextval('public.team_hof_id_seq'::regclass);


--
-- Name: team_lineups id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_lineups ALTER COLUMN id SET DEFAULT nextval('public.team_lineups_id_seq'::regclass);


--
-- Name: team_on_off id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_on_off ALTER COLUMN id SET DEFAULT nextval('public.team_on_off_id_seq'::regclass);


--
-- Name: team_referees id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_referees ALTER COLUMN id SET DEFAULT nextval('public.team_referees_id_seq'::regclass);


--
-- Name: trade_semantics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_semantics ALTER COLUMN id SET DEFAULT nextval('public.trade_semantics_id_seq'::regclass);


--
-- Name: transactions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions ALTER COLUMN id SET DEFAULT nextval('public.transactions_id_seq'::regclass);


--
-- Name: workspace_charts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_charts ALTER COLUMN id SET DEFAULT nextval('public.workspace_charts_id_seq'::regclass);


--
-- Name: workspace_datasets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_datasets ALTER COLUMN id SET DEFAULT nextval('public.workspace_datasets_id_seq'::regclass);


--
-- Name: workspace_formulas id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_formulas ALTER COLUMN id SET DEFAULT nextval('public.workspace_formulas_id_seq'::regclass);


--
-- Name: workspaces id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces ALTER COLUMN id SET DEFAULT nextval('public.workspaces_id_seq'::regclass);


--
-- Name: external_player_status external_player_status_br_player_id_season_event_type_key; Type: CONSTRAINT; Schema: analytics; Owner: -
--

ALTER TABLE ONLY analytics.external_player_status
    ADD CONSTRAINT external_player_status_br_player_id_season_event_type_key UNIQUE (br_player_id, season, event_type);


--
-- Name: external_player_status external_player_status_pkey; Type: CONSTRAINT; Schema: analytics; Owner: -
--

ALTER TABLE ONLY analytics.external_player_status
    ADD CONSTRAINT external_player_status_pkey PRIMARY KEY (id);


--
-- Name: analysis_flows analysis_flows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analysis_flows
    ADD CONSTRAINT analysis_flows_pkey PRIMARY KEY (id);


--
-- Name: backfill_review backfill_review_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backfill_review
    ADD CONSTRAINT backfill_review_pkey PRIMARY KEY (id);


--
-- Name: coach_crawl_status coach_crawl_status_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coach_crawl_status
    ADD CONSTRAINT coach_crawl_status_pkey PRIMARY KEY (coach_id);


--
-- Name: coach_stats coach_stats_coach_id_season_team_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coach_stats
    ADD CONSTRAINT coach_stats_coach_id_season_team_key UNIQUE (coach_id, season, team);


--
-- Name: coach_stats coach_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coach_stats
    ADD CONSTRAINT coach_stats_pkey PRIMARY KEY (id);


--
-- Name: coaches coaches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coaches
    ADD CONSTRAINT coaches_pkey PRIMARY KEY (coach_id);


--
-- Name: crawl_failures crawl_failures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crawl_failures
    ADD CONSTRAINT crawl_failures_pkey PRIMARY KEY (id);


--
-- Name: dim_franchise dim_franchise_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dim_franchise
    ADD CONSTRAINT dim_franchise_pkey PRIMARY KEY (franchise_id);


--
-- Name: dim_players dim_players_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dim_players
    ADD CONSTRAINT dim_players_pkey PRIMARY KEY (player_id);


--
-- Name: draft_combine draft_combine_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft_combine
    ADD CONSTRAINT draft_combine_pkey PRIMARY KEY (id);


--
-- Name: draft_combine draft_combine_season_player_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft_combine
    ADD CONSTRAINT draft_combine_season_player_name_key UNIQUE (season, player_name);


--
-- Name: draft_summary draft_summary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft_summary
    ADD CONSTRAINT draft_summary_pkey PRIMARY KEY (season);


--
-- Name: espn_boxscore espn_boxscore_espn_event_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.espn_boxscore
    ADD CONSTRAINT espn_boxscore_espn_event_key UNIQUE (espn_event);


--
-- Name: espn_boxscore espn_boxscore_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.espn_boxscore
    ADD CONSTRAINT espn_boxscore_pkey PRIMARY KEY (id);


--
-- Name: fact_player_season_stats fact_player_season_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_player_season_stats
    ADD CONSTRAINT fact_player_season_stats_pkey PRIMARY KEY (id);


--
-- Name: fct_pbp_shots fct_pbp_shots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fct_pbp_shots
    ADD CONSTRAINT fct_pbp_shots_pkey PRIMARY KEY (id);


--
-- Name: game_id_map_allstar game_id_map_allstar_br_gid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.game_id_map_allstar
    ADD CONSTRAINT game_id_map_allstar_br_gid_key UNIQUE (br_gid);


--
-- Name: game_id_map_allstar game_id_map_allstar_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.game_id_map_allstar
    ADD CONSTRAINT game_id_map_allstar_pkey PRIMARY KEY (id);


--
-- Name: game_id_map game_id_map_br_gid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.game_id_map
    ADD CONSTRAINT game_id_map_br_gid_key UNIQUE (br_gid);


--
-- Name: game_id_map game_id_map_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.game_id_map
    ADD CONSTRAINT game_id_map_pkey PRIMARY KEY (id);


--
-- Name: dim_games games_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dim_games
    ADD CONSTRAINT games_pkey PRIMARY KEY (game_id);


--
-- Name: injuries injuries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.injuries
    ADD CONSTRAINT injuries_pkey PRIMARY KEY (id);


--
-- Name: injuries injuries_report_date_player_name_team_abbr_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.injuries
    ADD CONSTRAINT injuries_report_date_player_name_team_abbr_key UNIQUE (report_date, player_name, team_abbr);


--
-- Name: league_salary_rules league_salary_rules_league_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.league_salary_rules
    ADD CONSTRAINT league_salary_rules_league_season_key UNIQUE (league, season);


--
-- Name: league_salary_rules league_salary_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.league_salary_rules
    ADD CONSTRAINT league_salary_rules_pkey PRIMARY KEY (id);


--
-- Name: meta_data_verification meta_data_verification_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meta_data_verification
    ADD CONSTRAINT meta_data_verification_pkey PRIMARY KEY (id);


--
-- Name: pbp_parse_issues pbp_parse_issues_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pbp_parse_issues
    ADD CONSTRAINT pbp_parse_issues_pkey PRIMARY KEY (id);


--
-- Name: pbp_semantic pbp_semantic_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pbp_semantic
    ADD CONSTRAINT pbp_semantic_pkey PRIMARY KEY (id);


--
-- Name: play_by_play play_by_play_uq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play
    ADD CONSTRAINT play_by_play_uq UNIQUE (id, season);


--
-- Name: play_by_play_p_1997 play_by_play_p_1997_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_1997
    ADD CONSTRAINT play_by_play_p_1997_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_1998 play_by_play_p_1998_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_1998
    ADD CONSTRAINT play_by_play_p_1998_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_1999 play_by_play_p_1999_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_1999
    ADD CONSTRAINT play_by_play_p_1999_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2000 play_by_play_p_2000_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2000
    ADD CONSTRAINT play_by_play_p_2000_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2001 play_by_play_p_2001_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2001
    ADD CONSTRAINT play_by_play_p_2001_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2002 play_by_play_p_2002_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2002
    ADD CONSTRAINT play_by_play_p_2002_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2003 play_by_play_p_2003_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2003
    ADD CONSTRAINT play_by_play_p_2003_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2004 play_by_play_p_2004_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2004
    ADD CONSTRAINT play_by_play_p_2004_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2005 play_by_play_p_2005_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2005
    ADD CONSTRAINT play_by_play_p_2005_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2006 play_by_play_p_2006_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2006
    ADD CONSTRAINT play_by_play_p_2006_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2007 play_by_play_p_2007_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2007
    ADD CONSTRAINT play_by_play_p_2007_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2008 play_by_play_p_2008_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2008
    ADD CONSTRAINT play_by_play_p_2008_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2009 play_by_play_p_2009_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2009
    ADD CONSTRAINT play_by_play_p_2009_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2010 play_by_play_p_2010_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2010
    ADD CONSTRAINT play_by_play_p_2010_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2011 play_by_play_p_2011_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2011
    ADD CONSTRAINT play_by_play_p_2011_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2012 play_by_play_p_2012_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2012
    ADD CONSTRAINT play_by_play_p_2012_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2013 play_by_play_p_2013_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2013
    ADD CONSTRAINT play_by_play_p_2013_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2014 play_by_play_p_2014_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2014
    ADD CONSTRAINT play_by_play_p_2014_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2015 play_by_play_p_2015_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2015
    ADD CONSTRAINT play_by_play_p_2015_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2016 play_by_play_p_2016_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2016
    ADD CONSTRAINT play_by_play_p_2016_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2017 play_by_play_p_2017_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2017
    ADD CONSTRAINT play_by_play_p_2017_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2018 play_by_play_p_2018_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2018
    ADD CONSTRAINT play_by_play_p_2018_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2019 play_by_play_p_2019_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2019
    ADD CONSTRAINT play_by_play_p_2019_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2020 play_by_play_p_2020_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2020
    ADD CONSTRAINT play_by_play_p_2020_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2021 play_by_play_p_2021_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2021
    ADD CONSTRAINT play_by_play_p_2021_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2022 play_by_play_p_2022_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2022
    ADD CONSTRAINT play_by_play_p_2022_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2023 play_by_play_p_2023_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2023
    ADD CONSTRAINT play_by_play_p_2023_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2024 play_by_play_p_2024_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2024
    ADD CONSTRAINT play_by_play_p_2024_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2025 play_by_play_p_2025_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2025
    ADD CONSTRAINT play_by_play_p_2025_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2026 play_by_play_p_2026_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2026
    ADD CONSTRAINT play_by_play_p_2026_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_2027 play_by_play_p_2027_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_2027
    ADD CONSTRAINT play_by_play_p_2027_id_season_key UNIQUE (id, season);


--
-- Name: play_by_play_p_default play_by_play_p_default_id_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_p_default
    ADD CONSTRAINT play_by_play_p_default_id_season_key UNIQUE (id, season);


--
-- Name: player_adjusted_shooting player_adjusted_shooting_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_adjusted_shooting
    ADD CONSTRAINT player_adjusted_shooting_pkey PRIMARY KEY (player_id, season_type, season_end);


--
-- Name: player_all_star_games player_all_star_games_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_all_star_games
    ADD CONSTRAINT player_all_star_games_pkey PRIMARY KEY (player_id, season_text);


--
-- Name: player_career_honors player_career_honors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_career_honors
    ADD CONSTRAINT player_career_honors_pkey PRIMARY KEY (id);


--
-- Name: player_career_totals player_career_totals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_career_totals
    ADD CONSTRAINT player_career_totals_pkey PRIMARY KEY (id);


--
-- Name: player_career_totals player_career_totals_player_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_career_totals
    ADD CONSTRAINT player_career_totals_player_name_key UNIQUE (player_name);


--
-- Name: player_contracts_league player_contracts_league_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_contracts_league
    ADD CONSTRAINT player_contracts_league_pkey PRIMARY KEY (player_id, team_abbr, season);


--
-- Name: player_contracts player_contracts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_contracts
    ADD CONSTRAINT player_contracts_pkey PRIMARY KEY (team_abbr, season, player_id);


--
-- Name: player_dpm_calc player_dpm_calc_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_dpm_calc
    ADD CONSTRAINT player_dpm_calc_pkey PRIMARY KEY (br_player_id, season);


--
-- Name: player_dpm player_dpm_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_dpm
    ADD CONSTRAINT player_dpm_pkey PRIMARY KEY (nba_id, snapshot_date);


--
-- Name: player_epm_actual player_epm_actual_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_epm_actual
    ADD CONSTRAINT player_epm_actual_pkey PRIMARY KEY (nba_player_id, season, seasontype);


--
-- Name: player_epm player_epm_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_epm
    ADD CONSTRAINT player_epm_pkey PRIMARY KEY (nba_player_id, season, source);


--
-- Name: player_game_highs player_game_highs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_game_highs
    ADD CONSTRAINT player_game_highs_pkey PRIMARY KEY (player_id, season_type, season_end);


--
-- Name: player_gamelog_jones_fix_bak player_gamelog_jones_fix_bak_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_gamelog_jones_fix_bak
    ADD CONSTRAINT player_gamelog_jones_fix_bak_pkey PRIMARY KEY (id);


--
-- Name: player_gamelog player_gamelog_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_gamelog
    ADD CONSTRAINT player_gamelog_pkey PRIMARY KEY (id);


--
-- Name: player_gamelog_teamown_fix_bak player_gamelog_teamown_fix_bak_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_gamelog_teamown_fix_bak
    ADD CONSTRAINT player_gamelog_teamown_fix_bak_pkey PRIMARY KEY (id);


--
-- Name: player_id_bridge_1to1 player_id_bridge_1to1_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_id_bridge_1to1
    ADD CONSTRAINT player_id_bridge_1to1_pkey PRIMARY KEY (br_player_id);


--
-- Name: player_id_bridge player_id_bridge_player_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_id_bridge
    ADD CONSTRAINT player_id_bridge_player_name_key UNIQUE (player_name);


--
-- Name: player_lebron player_lebron_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_lebron
    ADD CONSTRAINT player_lebron_pkey PRIMARY KEY (nba_id, season);


--
-- Name: player_lineups_404 player_lineups_404_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_lineups_404
    ADD CONSTRAINT player_lineups_404_pkey PRIMARY KEY (slug, year);


--
-- Name: player_lineups player_lineups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_lineups
    ADD CONSTRAINT player_lineups_pkey PRIMARY KEY (id);


--
-- Name: player_lineups player_lineups_uq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_lineups
    ADD CONSTRAINT player_lineups_uq UNIQUE (player_id, season, season_type, lineup_size, lineup_key);


--
-- Name: player_metrics_daily player_metrics_daily_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_metrics_daily
    ADD CONSTRAINT player_metrics_daily_pkey PRIMARY KEY (snapshot_date, metric, player_key);


--
-- Name: player_name_unified player_name_unified_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_name_unified
    ADD CONSTRAINT player_name_unified_pkey PRIMARY KEY (id);


--
-- Name: player_page_overview player_page_overview_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_page_overview
    ADD CONSTRAINT player_page_overview_pkey PRIMARY KEY (player_id);


--
-- Name: player_playin_plus_minus player_playin_plus_minus_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_playin_plus_minus
    ADD CONSTRAINT player_playin_plus_minus_pkey PRIMARY KEY (game_id_full, player_name);


--
-- Name: player_playoffs_series player_playoffs_series_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_playoffs_series
    ADD CONSTRAINT player_playoffs_series_pkey PRIMARY KEY (player_id, season_text, ps_round, opp_abbr);


--
-- Name: player_rapm_history player_rapm_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_rapm_history
    ADD CONSTRAINT player_rapm_history_pkey PRIMARY KEY (nba_id, season, is_playoff);


--
-- Name: player_rapm player_rapm_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_rapm
    ADD CONSTRAINT player_rapm_pkey PRIMARY KEY (nba_id, snapshot_date);


--
-- Name: player_salaries_historical player_salaries_historical_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_salaries_historical
    ADD CONSTRAINT player_salaries_historical_pkey PRIMARY KEY (id);


--
-- Name: player_season_splits player_season_splits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_season_splits
    ADD CONSTRAINT player_season_splits_pkey PRIMARY KEY (id);


--
-- Name: player_season_splits player_season_splits_season_player_name_team_abbr_split_typ_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_season_splits
    ADD CONSTRAINT player_season_splits_season_player_name_team_abbr_split_typ_key UNIQUE (season, player_name, team_abbr, split_type);


--
-- Name: player_similarity_scores player_similarity_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_similarity_scores
    ADD CONSTRAINT player_similarity_scores_pkey PRIMARY KEY (player_id, scope, comparable_name);


--
-- Name: player_weight_history player_weight_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_weight_history
    ADD CONSTRAINT player_weight_history_pkey PRIMARY KEY (player_id);


--
-- Name: playin_game_dates playin_game_dates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.playin_game_dates
    ADD CONSTRAINT playin_game_dates_pkey PRIMARY KEY (game_id_full);


--
-- Name: starting_lineups starting_lineups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.starting_lineups
    ADD CONSTRAINT starting_lineups_pkey PRIMARY KEY (id);


--
-- Name: starting_lineups starting_lineups_season_team_abbr_game_date_lineup_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.starting_lineups
    ADD CONSTRAINT starting_lineups_season_team_abbr_game_date_lineup_type_key UNIQUE (season, team_abbr, game_date, lineup_type);


--
-- Name: team_coaches team_coaches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_coaches
    ADD CONSTRAINT team_coaches_pkey PRIMARY KEY (team_abbr, season, coach_name, role);


--
-- Name: team_depth_chart team_depth_chart_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_depth_chart
    ADD CONSTRAINT team_depth_chart_pkey PRIMARY KEY (id);


--
-- Name: team_depth_chart team_depth_chart_season_team_abbr_position_depth_rank_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_depth_chart
    ADD CONSTRAINT team_depth_chart_season_team_abbr_position_depth_rank_key UNIQUE (season, team_abbr, "position", depth_rank);


--
-- Name: team_executives team_executives_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_executives
    ADD CONSTRAINT team_executives_pkey PRIMARY KEY (id);


--
-- Name: team_executives team_executives_team_abbr_rk_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_executives
    ADD CONSTRAINT team_executives_team_abbr_rk_key UNIQUE (team_abbr, rk);


--
-- Name: team_franchise_all_star team_franchise_all_star_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_franchise_all_star
    ADD CONSTRAINT team_franchise_all_star_pkey PRIMARY KEY (team_abbr, season, player_name);


--
-- Name: team_franchise_coaches team_franchise_coaches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_franchise_coaches
    ADD CONSTRAINT team_franchise_coaches_pkey PRIMARY KEY (team_abbr, coach_name, years);


--
-- Name: team_franchise_head2head team_franchise_head2head_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_franchise_head2head
    ADD CONSTRAINT team_franchise_head2head_pkey PRIMARY KEY (team_abbr, table_seq, row_idx, col_idx);


--
-- Name: team_franchise_hof team_franchise_hof_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_franchise_hof
    ADD CONSTRAINT team_franchise_hof_pkey PRIMARY KEY (team_abbr, season, player_name);


--
-- Name: team_franchise_index team_franchise_index_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_franchise_index
    ADD CONSTRAINT team_franchise_index_pkey PRIMARY KEY (team_abbr, season);


--
-- Name: team_franchise_numbers team_franchise_numbers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_franchise_numbers
    ADD CONSTRAINT team_franchise_numbers_pkey PRIMARY KEY (team_abbr, section, number, player_name);


--
-- Name: team_franchise_players team_franchise_players_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_franchise_players
    ADD CONSTRAINT team_franchise_players_pkey PRIMARY KEY (team_abbr, table_seq, row_idx, col_idx);


--
-- Name: team_franchise_playoffs team_franchise_playoffs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_franchise_playoffs
    ADD CONSTRAINT team_franchise_playoffs_pkey PRIMARY KEY (team_abbr, season, opponent);


--
-- Name: team_franchise_stats team_franchise_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_franchise_stats
    ADD CONSTRAINT team_franchise_stats_pkey PRIMARY KEY (team_abbr, table_id, table_seq, row_label, data_stat);


--
-- Name: team_game_splits team_game_splits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_game_splits
    ADD CONSTRAINT team_game_splits_pkey PRIMARY KEY (id);


--
-- Name: team_game_splits team_game_splits_season_team_abbr_split_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_game_splits
    ADD CONSTRAINT team_game_splits_season_team_abbr_split_type_key UNIQUE (season, team_abbr, split_type);


--
-- Name: team_hof team_hof_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_hof
    ADD CONSTRAINT team_hof_pkey PRIMARY KEY (id);


--
-- Name: team_hof team_hof_team_abbr_season_player_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_hof
    ADD CONSTRAINT team_hof_team_abbr_season_player_name_key UNIQUE (team_abbr, season, player_name);


--
-- Name: team_leaderboards team_leaderboards_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_leaderboards
    ADD CONSTRAINT team_leaderboards_pkey PRIMARY KEY (team_abbr, season, player_slug, leaderboard);


--
-- Name: team_lineups team_lineups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_lineups
    ADD CONSTRAINT team_lineups_pkey PRIMARY KEY (id);


--
-- Name: team_lineups team_lineups_team_abbr_season_season_type_lineup_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_lineups
    ADD CONSTRAINT team_lineups_team_abbr_season_season_type_lineup_key_key UNIQUE (team_abbr, season, season_type, lineup_key);


--
-- Name: team_logos team_logos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_logos
    ADD CONSTRAINT team_logos_pkey PRIMARY KEY (team_abbr, season);


--
-- Name: dim_teams team_mapping_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dim_teams
    ADD CONSTRAINT team_mapping_pkey PRIMARY KEY (id);


--
-- Name: team_on_off team_on_off_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_on_off
    ADD CONSTRAINT team_on_off_pkey PRIMARY KEY (id);


--
-- Name: team_on_off team_on_off_team_abbr_season_season_type_player_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_on_off
    ADD CONSTRAINT team_on_off_team_abbr_season_season_type_player_name_key UNIQUE (team_abbr, season, season_type, player_name);


--
-- Name: team_page_raw team_page_raw_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_page_raw
    ADD CONSTRAINT team_page_raw_pkey PRIMARY KEY (team_abbr, season, season_type, table_id, row_label, data_stat);


--
-- Name: team_payroll team_payroll_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_payroll
    ADD CONSTRAINT team_payroll_pkey PRIMARY KEY (team_abbr, season);


--
-- Name: team_pbp_raw team_pbp_raw_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_pbp_raw
    ADD CONSTRAINT team_pbp_raw_pkey PRIMARY KEY (team_abbr, season, season_type, table_id, row_label, data_stat);


--
-- Name: team_per_36 team_per_36_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_per_36
    ADD CONSTRAINT team_per_36_pkey PRIMARY KEY (team_abbr, season, season_type, player_slug);


--
-- Name: team_referees team_referees_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_referees
    ADD CONSTRAINT team_referees_pkey PRIMARY KEY (id);


--
-- Name: team_referees team_referees_team_abbr_season_referee_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_referees
    ADD CONSTRAINT team_referees_team_abbr_season_referee_slug_key UNIQUE (team_abbr, season, referee_slug);


--
-- Name: team_roster team_roster_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_roster
    ADD CONSTRAINT team_roster_pkey PRIMARY KEY (team_abbr, season, player_slug);


--
-- Name: trade_semantics trade_semantics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_semantics
    ADD CONSTRAINT trade_semantics_pkey PRIMARY KEY (id);


--
-- Name: trade_semantics trade_semantics_source_ref_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_semantics
    ADD CONSTRAINT trade_semantics_source_ref_key UNIQUE (source_ref);


--
-- Name: transactions transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_pkey PRIMARY KEY (id);


--
-- Name: transactions transactions_transaction_date_team_abbr_description_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_transaction_date_team_abbr_description_key UNIQUE (transaction_date, team_abbr, description);


--
-- Name: fct_pbp_shots uq_fct_shot; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fct_pbp_shots
    ADD CONSTRAINT uq_fct_shot UNIQUE (game_id, src_ctid);


--
-- Name: player_onoff uq_player_onoff; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_onoff
    ADD CONSTRAINT uq_player_onoff UNIQUE (player_id, season, season_type, split);


--
-- Name: player_shot_chart uq_player_shot_chart; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_shot_chart
    ADD CONSTRAINT uq_player_shot_chart UNIQUE (player_id, game_date, opponent_abbr, period, time_remaining, x_px, y_px);


--
-- Name: player_salaries_historical uq_salaries_player_season; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_salaries_historical
    ADD CONSTRAINT uq_salaries_player_season UNIQUE (player_name, season);


--
-- Name: workspace_charts workspace_charts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_charts
    ADD CONSTRAINT workspace_charts_pkey PRIMARY KEY (id);


--
-- Name: workspace_datasets workspace_datasets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_datasets
    ADD CONSTRAINT workspace_datasets_pkey PRIMARY KEY (id);


--
-- Name: workspace_datasets workspace_datasets_workspace_id_dataset_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_datasets
    ADD CONSTRAINT workspace_datasets_workspace_id_dataset_id_key UNIQUE (workspace_id, dataset_id);


--
-- Name: workspace_formulas workspace_formulas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_formulas
    ADD CONSTRAINT workspace_formulas_pkey PRIMARY KEY (id);


--
-- Name: workspace_formulas workspace_formulas_workspace_id_formula_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_formulas
    ADD CONSTRAINT workspace_formulas_workspace_id_formula_id_key UNIQUE (workspace_id, formula_id);


--
-- Name: workspaces workspaces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_pkey PRIMARY KEY (id);


--
-- Name: bf_stage_20260804_sid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX bf_stage_20260804_sid_idx ON public.bf_stage_20260804 USING btree (sid);


--
-- Name: game_id_map_allstar_espn_event_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX game_id_map_allstar_espn_event_idx ON public.game_id_map_allstar USING btree (espn_event);


--
-- Name: game_id_map_allstar_game_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX game_id_map_allstar_game_date_idx ON public.game_id_map_allstar USING btree (game_date);


--
-- Name: game_id_map_allstar_nba_api_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX game_id_map_allstar_nba_api_id_idx ON public.game_id_map_allstar USING btree (nba_api_id);


--
-- Name: good_name_map_nn_team_sy_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX good_name_map_nn_team_sy_idx ON public.good_name_map USING btree (nn, team, sy);


--
-- Name: idx_bridge_br_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bridge_br_id ON public.player_id_bridge USING btree (br_player_id);


--
-- Name: idx_bridge_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bridge_name ON public.player_id_bridge USING btree (player_name);


--
-- Name: idx_bridge_nba_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bridge_nba_id ON public.player_id_bridge USING btree (nba_player_id);


--
-- Name: idx_dim_draft_pick; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_draft_pick ON public.dim_draft_history USING btree (pick_overall);


--
-- Name: idx_dim_draft_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_draft_player ON public.dim_draft_history USING btree (player_id);


--
-- Name: idx_dim_draft_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_draft_season ON public.dim_draft_history USING btree (season);


--
-- Name: idx_dim_draft_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_draft_team ON public.dim_draft_history USING btree (team_abbr);


--
-- Name: idx_dim_games_away_abbr; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_games_away_abbr ON public.dim_games USING btree (away_team_abbr);


--
-- Name: idx_dim_games_br_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_games_br_id ON public.dim_games USING btree (br_crawled_id) WHERE (br_crawled_id IS NOT NULL);


--
-- Name: idx_dim_games_brnobox; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_games_brnobox ON public.dim_games USING btree (br_no_boxscore) WHERE br_no_boxscore;


--
-- Name: idx_dim_games_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_games_date ON public.dim_games USING btree (game_date);


--
-- Name: idx_dim_games_home_abbr; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_games_home_abbr ON public.dim_games USING btree (home_team_abbr);


--
-- Name: idx_dim_games_nba_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_games_nba_id ON public.dim_games USING btree (nba_api_id) WHERE (nba_api_id IS NOT NULL);


--
-- Name: idx_dim_games_pbpnodata; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_games_pbpnodata ON public.dim_games USING btree (pbp_no_data) WHERE pbp_no_data;


--
-- Name: idx_dim_games_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_games_season ON public.dim_games USING btree (season);


--
-- Name: idx_dim_games_season_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_games_season_type ON public.dim_games USING btree (season_type);


--
-- Name: idx_dim_players_college; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_players_college ON public.dim_players USING btree (college);


--
-- Name: idx_dim_players_headshot_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_players_headshot_status ON public.dim_players USING btree (headshot_status);


--
-- Name: idx_dim_players_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_players_name ON public.dim_players USING btree (player_name);


--
-- Name: idx_dim_players_nickname; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_players_nickname ON public.dim_players USING btree (nickname) WHERE (nickname IS NOT NULL);


--
-- Name: idx_dim_teams_abbr; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_teams_abbr ON public.dim_teams USING btree (team_abbr);


--
-- Name: idx_dim_teams_current; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_teams_current ON public.dim_teams USING btree (current_code);


--
-- Name: idx_dp_bio_ext_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dp_bio_ext_ts ON public.dim_players USING btree (bio_ext_scraped_at);


--
-- Name: idx_dp_hof; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dp_hof ON public.dim_players USING btree (is_hall_of_famer) WHERE (is_hall_of_famer = true);


--
-- Name: idx_eb_brgid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_eb_brgid ON public.espn_boxscore USING btree (br_gid);


--
-- Name: idx_eb_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_eb_date ON public.espn_boxscore USING btree (game_date);


--
-- Name: idx_epm_actual_br_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_epm_actual_br_id ON public.player_epm_actual USING btree (br_player_id);


--
-- Name: idx_epm_actual_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_epm_actual_season ON public.player_epm_actual USING btree (season);


--
-- Name: idx_epm_actual_tot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_epm_actual_tot ON public.player_epm_actual USING btree (season, epm_tot DESC);


--
-- Name: idx_epm_br_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_epm_br_id ON public.player_epm USING btree (br_player_id);


--
-- Name: idx_epm_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_epm_season ON public.player_epm USING btree (season);


--
-- Name: idx_epm_tot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_epm_tot ON public.player_epm USING btree (season, epm_tot DESC);


--
-- Name: idx_fact_pid_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fact_pid_season ON public.fact_player_season_stats USING btree (player_id, season, season_type);


--
-- Name: idx_fact_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fact_season ON public.fact_player_season_stats USING btree (season);


--
-- Name: idx_fps_clutch_dist; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fps_clutch_dist ON public.fct_pbp_shots USING btree (season, is_clutch, shot_distance);


--
-- Name: idx_fps_season_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fps_season_game ON public.fct_pbp_shots USING btree (season, game_id);


--
-- Name: idx_fps_season_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fps_season_player ON public.fct_pbp_shots USING btree (season, player_slug);


--
-- Name: idx_fps_season_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fps_season_team ON public.fct_pbp_shots USING btree (season, team);


--
-- Name: idx_fpss_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fpss_player ON public.fact_player_season_stats USING btree (player_id);


--
-- Name: idx_fpss_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fpss_season ON public.fact_player_season_stats USING btree (season);


--
-- Name: idx_fpss_season_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fpss_season_type ON public.fact_player_season_stats USING btree (season_type);


--
-- Name: idx_fpss_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fpss_team ON public.fact_player_season_stats USING btree (team);


--
-- Name: idx_ftss_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ftss_season ON public.fact_team_season_stats USING btree (season);


--
-- Name: idx_ftss_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ftss_team ON public.fact_team_season_stats USING btree (team);


--
-- Name: idx_gamelog_br_pid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gamelog_br_pid ON public.player_gamelog USING btree (br_player_id);


--
-- Name: idx_gamelog_pid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gamelog_pid ON public.player_gamelog USING btree (player_id);


--
-- Name: idx_games_game_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_games_game_id ON public.dim_games USING btree (game_id);


--
-- Name: idx_gim_api; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gim_api ON public.game_id_map USING btree (nba_api_id);


--
-- Name: idx_gim_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gim_date ON public.game_id_map USING btree (game_date);


--
-- Name: idx_gim_espn; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gim_espn ON public.game_id_map USING btree (espn_event);


--
-- Name: idx_la_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_la_lookup ON public.league_averages USING btree (lg, season, metric_type, team);


--
-- Name: idx_league_salary_rules_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_league_salary_rules_season ON public.league_salary_rules USING btree (league, season);


--
-- Name: idx_pbp_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pbp_event ON ONLY public.play_by_play USING btree (event_type);


--
-- Name: idx_pbp_game_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pbp_game_player ON ONLY public.play_by_play USING btree (gameid, player);


--
-- Name: idx_pbp_gameid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pbp_gameid ON ONLY public.play_by_play USING btree (gameid);


--
-- Name: idx_pbp_issues_gameid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pbp_issues_gameid ON public.pbp_parse_issues USING btree (gameid);


--
-- Name: idx_pbp_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pbp_player ON ONLY public.play_by_play USING btree (player);


--
-- Name: idx_pbp_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pbp_season ON ONLY public.play_by_play USING btree (season);


--
-- Name: idx_pbp_semantic_gameid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pbp_semantic_gameid ON public.pbp_semantic USING btree (gameid);


--
-- Name: idx_pch_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pch_player ON public.player_career_honors USING btree (player_id);


--
-- Name: idx_pch_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pch_type ON public.player_career_honors USING btree (honor_type);


--
-- Name: idx_pg_game_id_full; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pg_game_id_full ON public.player_gamelog USING btree (game_id_full);


--
-- Name: idx_pg_game_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pg_game_player ON public.player_gamelog USING btree (gameid, player);


--
-- Name: idx_pg_gameid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pg_gameid ON public.player_gamelog USING btree (gameid);


--
-- Name: idx_pg_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pg_player ON public.player_gamelog USING btree (player);


--
-- Name: idx_pg_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pg_season ON public.player_gamelog USING btree (season);


--
-- Name: idx_pg_season_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pg_season_player ON public.player_gamelog USING btree (season, player);


--
-- Name: idx_pg_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pg_team ON public.player_gamelog USING btree (team);


--
-- Name: idx_pl404_first_seen; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pl404_first_seen ON public.player_lineups_404 USING btree (first_seen);


--
-- Name: idx_player_lineups_lineup_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_player_lineups_lineup_key ON public.player_lineups USING btree (lineup_key);


--
-- Name: idx_player_lineups_pid_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_player_lineups_pid_season ON public.player_lineups USING btree (player_id, season);


--
-- Name: idx_player_lineups_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_player_lineups_season ON public.player_lineups USING btree (season);


--
-- Name: idx_player_lineups_team_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_player_lineups_team_id ON public.player_lineups USING btree (team_id);


--
-- Name: idx_player_onoff_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_player_onoff_player ON public.player_onoff USING btree (player_id);


--
-- Name: idx_player_onoff_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_player_onoff_season ON public.player_onoff USING btree (season);


--
-- Name: idx_pmd_nbaid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmd_nbaid ON public.player_metrics_daily USING btree (metric, nba_id, snapshot_date);


--
-- Name: idx_pmd_series; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmd_series ON public.player_metrics_daily USING btree (metric, player_key, snapshot_date);


--
-- Name: idx_pnu_abbr; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pnu_abbr ON public.player_name_unified USING btree (abbreviation);


--
-- Name: idx_psc_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_psc_game ON public.player_shot_chart USING btree (game_id);


--
-- Name: idx_psc_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_psc_player ON public.player_shot_chart USING btree (player_id);


--
-- Name: idx_psc_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_psc_season ON public.player_shot_chart USING btree (player_id, season);


--
-- Name: idx_pss_pid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pss_pid ON public.player_season_splits USING btree (player_id);


--
-- Name: idx_pss_player_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pss_player_season ON public.player_season_splits USING btree (player_name, season);


--
-- Name: idx_pss_season_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pss_season_category ON public.player_season_splits USING btree (season, split_category);


--
-- Name: idx_salaries_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_salaries_player ON public.player_salaries_historical USING btree (player_name);


--
-- Name: idx_salaries_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_salaries_season ON public.player_salaries_historical USING btree (season);


--
-- Name: idx_salaries_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_salaries_team ON public.player_salaries_historical USING btree (team_abbr);


--
-- Name: idx_te_exec; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_te_exec ON public.team_executives USING btree (executive);


--
-- Name: idx_te_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_te_team ON public.team_executives USING btree (team_abbr);


--
-- Name: idx_team_coaches_team_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_team_coaches_team_season ON public.team_coaches USING btree (team_abbr, season);


--
-- Name: idx_team_leaderboards_team_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_team_leaderboards_team_season ON public.team_leaderboards USING btree (team_abbr, season);


--
-- Name: idx_team_lineups_team_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_team_lineups_team_season ON public.team_lineups USING btree (team_abbr, season);


--
-- Name: idx_team_logos_franchise; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_team_logos_franchise ON public.team_logos USING btree (franchise_id);


--
-- Name: idx_team_mapping_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_team_mapping_code ON public.dim_teams USING btree (team_abbr);


--
-- Name: idx_team_on_off_team_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_team_on_off_team_season ON public.team_on_off USING btree (team_abbr, season);


--
-- Name: idx_team_page_raw_table_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_team_page_raw_table_id ON public.team_page_raw USING btree (table_id);


--
-- Name: idx_team_page_raw_team_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_team_page_raw_team_season ON public.team_page_raw USING btree (team_abbr, season, season_type);


--
-- Name: idx_team_pbp_raw_table_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_team_pbp_raw_table_id ON public.team_pbp_raw USING btree (table_id);


--
-- Name: idx_team_pbp_raw_team_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_team_pbp_raw_team_season ON public.team_pbp_raw USING btree (team_abbr, season, season_type);


--
-- Name: idx_team_per_36_team_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_team_per_36_team_season ON public.team_per_36 USING btree (team_abbr, season);


--
-- Name: idx_team_referees_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_team_referees_ref ON public.team_referees USING btree (referee_slug);


--
-- Name: idx_team_referees_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_team_referees_season ON public.team_referees USING btree (season);


--
-- Name: idx_team_roster_team_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_team_roster_team_season ON public.team_roster USING btree (team_abbr, season);


--
-- Name: idx_tfas_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tfas_team ON public.team_franchise_all_star USING btree (team_abbr);


--
-- Name: idx_tfh_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tfh_team ON public.team_franchise_head2head USING btree (team_abbr);


--
-- Name: idx_tfhof_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tfhof_team ON public.team_franchise_hof USING btree (team_abbr);


--
-- Name: idx_tfn_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tfn_team ON public.team_franchise_numbers USING btree (team_abbr);


--
-- Name: idx_tfp_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tfp_team ON public.team_franchise_players USING btree (team_abbr);


--
-- Name: idx_tfs_franchise; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tfs_franchise ON public.team_franchise_stats USING btree (franchise_id);


--
-- Name: idx_tfs_table_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tfs_table_id ON public.team_franchise_stats USING btree (table_id);


--
-- Name: idx_tfs_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tfs_team ON public.team_franchise_stats USING btree (team_abbr);


--
-- Name: idx_th_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_th_player ON public.team_hof USING btree (player_name);


--
-- Name: idx_th_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_th_team ON public.team_hof USING btree (team_abbr);


--
-- Name: idx_ts_season_playoffs_w; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ts_season_playoffs_w ON public.team_summaries USING btree (season, playoffs, w DESC);


--
-- Name: ix_analysis_flows_ws; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_analysis_flows_ws ON public.analysis_flows USING btree (workspace_id);


--
-- Name: ix_ws_charts_ws; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ws_charts_ws ON public.workspace_charts USING btree (workspace_id);


--
-- Name: ix_ws_datasets_ws; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ws_datasets_ws ON public.workspace_datasets USING btree (workspace_id);


--
-- Name: ix_ws_formulas_ws; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ws_formulas_ws ON public.workspace_formulas USING btree (workspace_id);


--
-- Name: play_by_play_p_1997_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1997_event_type_idx ON public.play_by_play_p_1997 USING btree (event_type);


--
-- Name: play_by_play_p_1997_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1997_gameid_idx ON public.play_by_play_p_1997 USING btree (gameid);


--
-- Name: play_by_play_p_1997_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1997_gameid_player_idx ON public.play_by_play_p_1997 USING btree (gameid, player);


--
-- Name: play_by_play_p_1997_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1997_player_idx ON public.play_by_play_p_1997 USING btree (player);


--
-- Name: play_by_play_p_1997_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1997_season_idx ON public.play_by_play_p_1997 USING btree (season);


--
-- Name: play_by_play_p_1998_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1998_event_type_idx ON public.play_by_play_p_1998 USING btree (event_type);


--
-- Name: play_by_play_p_1998_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1998_gameid_idx ON public.play_by_play_p_1998 USING btree (gameid);


--
-- Name: play_by_play_p_1998_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1998_gameid_player_idx ON public.play_by_play_p_1998 USING btree (gameid, player);


--
-- Name: play_by_play_p_1998_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1998_player_idx ON public.play_by_play_p_1998 USING btree (player);


--
-- Name: play_by_play_p_1998_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1998_season_idx ON public.play_by_play_p_1998 USING btree (season);


--
-- Name: play_by_play_p_1999_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1999_event_type_idx ON public.play_by_play_p_1999 USING btree (event_type);


--
-- Name: play_by_play_p_1999_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1999_gameid_idx ON public.play_by_play_p_1999 USING btree (gameid);


--
-- Name: play_by_play_p_1999_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1999_gameid_player_idx ON public.play_by_play_p_1999 USING btree (gameid, player);


--
-- Name: play_by_play_p_1999_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1999_player_idx ON public.play_by_play_p_1999 USING btree (player);


--
-- Name: play_by_play_p_1999_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_1999_season_idx ON public.play_by_play_p_1999 USING btree (season);


--
-- Name: play_by_play_p_2000_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2000_event_type_idx ON public.play_by_play_p_2000 USING btree (event_type);


--
-- Name: play_by_play_p_2000_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2000_gameid_idx ON public.play_by_play_p_2000 USING btree (gameid);


--
-- Name: play_by_play_p_2000_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2000_gameid_player_idx ON public.play_by_play_p_2000 USING btree (gameid, player);


--
-- Name: play_by_play_p_2000_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2000_player_idx ON public.play_by_play_p_2000 USING btree (player);


--
-- Name: play_by_play_p_2000_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2000_season_idx ON public.play_by_play_p_2000 USING btree (season);


--
-- Name: play_by_play_p_2001_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2001_event_type_idx ON public.play_by_play_p_2001 USING btree (event_type);


--
-- Name: play_by_play_p_2001_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2001_gameid_idx ON public.play_by_play_p_2001 USING btree (gameid);


--
-- Name: play_by_play_p_2001_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2001_gameid_player_idx ON public.play_by_play_p_2001 USING btree (gameid, player);


--
-- Name: play_by_play_p_2001_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2001_player_idx ON public.play_by_play_p_2001 USING btree (player);


--
-- Name: play_by_play_p_2001_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2001_season_idx ON public.play_by_play_p_2001 USING btree (season);


--
-- Name: play_by_play_p_2002_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2002_event_type_idx ON public.play_by_play_p_2002 USING btree (event_type);


--
-- Name: play_by_play_p_2002_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2002_gameid_idx ON public.play_by_play_p_2002 USING btree (gameid);


--
-- Name: play_by_play_p_2002_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2002_gameid_player_idx ON public.play_by_play_p_2002 USING btree (gameid, player);


--
-- Name: play_by_play_p_2002_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2002_player_idx ON public.play_by_play_p_2002 USING btree (player);


--
-- Name: play_by_play_p_2002_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2002_season_idx ON public.play_by_play_p_2002 USING btree (season);


--
-- Name: play_by_play_p_2003_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2003_event_type_idx ON public.play_by_play_p_2003 USING btree (event_type);


--
-- Name: play_by_play_p_2003_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2003_gameid_idx ON public.play_by_play_p_2003 USING btree (gameid);


--
-- Name: play_by_play_p_2003_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2003_gameid_player_idx ON public.play_by_play_p_2003 USING btree (gameid, player);


--
-- Name: play_by_play_p_2003_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2003_player_idx ON public.play_by_play_p_2003 USING btree (player);


--
-- Name: play_by_play_p_2003_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2003_season_idx ON public.play_by_play_p_2003 USING btree (season);


--
-- Name: play_by_play_p_2004_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2004_event_type_idx ON public.play_by_play_p_2004 USING btree (event_type);


--
-- Name: play_by_play_p_2004_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2004_gameid_idx ON public.play_by_play_p_2004 USING btree (gameid);


--
-- Name: play_by_play_p_2004_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2004_gameid_player_idx ON public.play_by_play_p_2004 USING btree (gameid, player);


--
-- Name: play_by_play_p_2004_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2004_player_idx ON public.play_by_play_p_2004 USING btree (player);


--
-- Name: play_by_play_p_2004_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2004_season_idx ON public.play_by_play_p_2004 USING btree (season);


--
-- Name: play_by_play_p_2005_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2005_event_type_idx ON public.play_by_play_p_2005 USING btree (event_type);


--
-- Name: play_by_play_p_2005_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2005_gameid_idx ON public.play_by_play_p_2005 USING btree (gameid);


--
-- Name: play_by_play_p_2005_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2005_gameid_player_idx ON public.play_by_play_p_2005 USING btree (gameid, player);


--
-- Name: play_by_play_p_2005_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2005_player_idx ON public.play_by_play_p_2005 USING btree (player);


--
-- Name: play_by_play_p_2005_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2005_season_idx ON public.play_by_play_p_2005 USING btree (season);


--
-- Name: play_by_play_p_2006_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2006_event_type_idx ON public.play_by_play_p_2006 USING btree (event_type);


--
-- Name: play_by_play_p_2006_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2006_gameid_idx ON public.play_by_play_p_2006 USING btree (gameid);


--
-- Name: play_by_play_p_2006_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2006_gameid_player_idx ON public.play_by_play_p_2006 USING btree (gameid, player);


--
-- Name: play_by_play_p_2006_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2006_player_idx ON public.play_by_play_p_2006 USING btree (player);


--
-- Name: play_by_play_p_2006_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2006_season_idx ON public.play_by_play_p_2006 USING btree (season);


--
-- Name: play_by_play_p_2007_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2007_event_type_idx ON public.play_by_play_p_2007 USING btree (event_type);


--
-- Name: play_by_play_p_2007_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2007_gameid_idx ON public.play_by_play_p_2007 USING btree (gameid);


--
-- Name: play_by_play_p_2007_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2007_gameid_player_idx ON public.play_by_play_p_2007 USING btree (gameid, player);


--
-- Name: play_by_play_p_2007_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2007_player_idx ON public.play_by_play_p_2007 USING btree (player);


--
-- Name: play_by_play_p_2007_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2007_season_idx ON public.play_by_play_p_2007 USING btree (season);


--
-- Name: play_by_play_p_2008_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2008_event_type_idx ON public.play_by_play_p_2008 USING btree (event_type);


--
-- Name: play_by_play_p_2008_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2008_gameid_idx ON public.play_by_play_p_2008 USING btree (gameid);


--
-- Name: play_by_play_p_2008_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2008_gameid_player_idx ON public.play_by_play_p_2008 USING btree (gameid, player);


--
-- Name: play_by_play_p_2008_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2008_player_idx ON public.play_by_play_p_2008 USING btree (player);


--
-- Name: play_by_play_p_2008_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2008_season_idx ON public.play_by_play_p_2008 USING btree (season);


--
-- Name: play_by_play_p_2009_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2009_event_type_idx ON public.play_by_play_p_2009 USING btree (event_type);


--
-- Name: play_by_play_p_2009_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2009_gameid_idx ON public.play_by_play_p_2009 USING btree (gameid);


--
-- Name: play_by_play_p_2009_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2009_gameid_player_idx ON public.play_by_play_p_2009 USING btree (gameid, player);


--
-- Name: play_by_play_p_2009_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2009_player_idx ON public.play_by_play_p_2009 USING btree (player);


--
-- Name: play_by_play_p_2009_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2009_season_idx ON public.play_by_play_p_2009 USING btree (season);


--
-- Name: play_by_play_p_2010_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2010_event_type_idx ON public.play_by_play_p_2010 USING btree (event_type);


--
-- Name: play_by_play_p_2010_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2010_gameid_idx ON public.play_by_play_p_2010 USING btree (gameid);


--
-- Name: play_by_play_p_2010_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2010_gameid_player_idx ON public.play_by_play_p_2010 USING btree (gameid, player);


--
-- Name: play_by_play_p_2010_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2010_player_idx ON public.play_by_play_p_2010 USING btree (player);


--
-- Name: play_by_play_p_2010_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2010_season_idx ON public.play_by_play_p_2010 USING btree (season);


--
-- Name: play_by_play_p_2011_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2011_event_type_idx ON public.play_by_play_p_2011 USING btree (event_type);


--
-- Name: play_by_play_p_2011_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2011_gameid_idx ON public.play_by_play_p_2011 USING btree (gameid);


--
-- Name: play_by_play_p_2011_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2011_gameid_player_idx ON public.play_by_play_p_2011 USING btree (gameid, player);


--
-- Name: play_by_play_p_2011_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2011_player_idx ON public.play_by_play_p_2011 USING btree (player);


--
-- Name: play_by_play_p_2011_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2011_season_idx ON public.play_by_play_p_2011 USING btree (season);


--
-- Name: play_by_play_p_2012_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2012_event_type_idx ON public.play_by_play_p_2012 USING btree (event_type);


--
-- Name: play_by_play_p_2012_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2012_gameid_idx ON public.play_by_play_p_2012 USING btree (gameid);


--
-- Name: play_by_play_p_2012_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2012_gameid_player_idx ON public.play_by_play_p_2012 USING btree (gameid, player);


--
-- Name: play_by_play_p_2012_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2012_player_idx ON public.play_by_play_p_2012 USING btree (player);


--
-- Name: play_by_play_p_2012_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2012_season_idx ON public.play_by_play_p_2012 USING btree (season);


--
-- Name: play_by_play_p_2013_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2013_event_type_idx ON public.play_by_play_p_2013 USING btree (event_type);


--
-- Name: play_by_play_p_2013_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2013_gameid_idx ON public.play_by_play_p_2013 USING btree (gameid);


--
-- Name: play_by_play_p_2013_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2013_gameid_player_idx ON public.play_by_play_p_2013 USING btree (gameid, player);


--
-- Name: play_by_play_p_2013_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2013_player_idx ON public.play_by_play_p_2013 USING btree (player);


--
-- Name: play_by_play_p_2013_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2013_season_idx ON public.play_by_play_p_2013 USING btree (season);


--
-- Name: play_by_play_p_2014_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2014_event_type_idx ON public.play_by_play_p_2014 USING btree (event_type);


--
-- Name: play_by_play_p_2014_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2014_gameid_idx ON public.play_by_play_p_2014 USING btree (gameid);


--
-- Name: play_by_play_p_2014_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2014_gameid_player_idx ON public.play_by_play_p_2014 USING btree (gameid, player);


--
-- Name: play_by_play_p_2014_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2014_player_idx ON public.play_by_play_p_2014 USING btree (player);


--
-- Name: play_by_play_p_2014_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2014_season_idx ON public.play_by_play_p_2014 USING btree (season);


--
-- Name: play_by_play_p_2015_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2015_event_type_idx ON public.play_by_play_p_2015 USING btree (event_type);


--
-- Name: play_by_play_p_2015_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2015_gameid_idx ON public.play_by_play_p_2015 USING btree (gameid);


--
-- Name: play_by_play_p_2015_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2015_gameid_player_idx ON public.play_by_play_p_2015 USING btree (gameid, player);


--
-- Name: play_by_play_p_2015_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2015_player_idx ON public.play_by_play_p_2015 USING btree (player);


--
-- Name: play_by_play_p_2015_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2015_season_idx ON public.play_by_play_p_2015 USING btree (season);


--
-- Name: play_by_play_p_2016_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2016_event_type_idx ON public.play_by_play_p_2016 USING btree (event_type);


--
-- Name: play_by_play_p_2016_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2016_gameid_idx ON public.play_by_play_p_2016 USING btree (gameid);


--
-- Name: play_by_play_p_2016_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2016_gameid_player_idx ON public.play_by_play_p_2016 USING btree (gameid, player);


--
-- Name: play_by_play_p_2016_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2016_player_idx ON public.play_by_play_p_2016 USING btree (player);


--
-- Name: play_by_play_p_2016_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2016_season_idx ON public.play_by_play_p_2016 USING btree (season);


--
-- Name: play_by_play_p_2017_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2017_event_type_idx ON public.play_by_play_p_2017 USING btree (event_type);


--
-- Name: play_by_play_p_2017_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2017_gameid_idx ON public.play_by_play_p_2017 USING btree (gameid);


--
-- Name: play_by_play_p_2017_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2017_gameid_player_idx ON public.play_by_play_p_2017 USING btree (gameid, player);


--
-- Name: play_by_play_p_2017_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2017_player_idx ON public.play_by_play_p_2017 USING btree (player);


--
-- Name: play_by_play_p_2017_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2017_season_idx ON public.play_by_play_p_2017 USING btree (season);


--
-- Name: play_by_play_p_2018_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2018_event_type_idx ON public.play_by_play_p_2018 USING btree (event_type);


--
-- Name: play_by_play_p_2018_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2018_gameid_idx ON public.play_by_play_p_2018 USING btree (gameid);


--
-- Name: play_by_play_p_2018_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2018_gameid_player_idx ON public.play_by_play_p_2018 USING btree (gameid, player);


--
-- Name: play_by_play_p_2018_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2018_player_idx ON public.play_by_play_p_2018 USING btree (player);


--
-- Name: play_by_play_p_2018_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2018_season_idx ON public.play_by_play_p_2018 USING btree (season);


--
-- Name: play_by_play_p_2019_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2019_event_type_idx ON public.play_by_play_p_2019 USING btree (event_type);


--
-- Name: play_by_play_p_2019_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2019_gameid_idx ON public.play_by_play_p_2019 USING btree (gameid);


--
-- Name: play_by_play_p_2019_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2019_gameid_player_idx ON public.play_by_play_p_2019 USING btree (gameid, player);


--
-- Name: play_by_play_p_2019_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2019_player_idx ON public.play_by_play_p_2019 USING btree (player);


--
-- Name: play_by_play_p_2019_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2019_season_idx ON public.play_by_play_p_2019 USING btree (season);


--
-- Name: play_by_play_p_2020_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2020_event_type_idx ON public.play_by_play_p_2020 USING btree (event_type);


--
-- Name: play_by_play_p_2020_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2020_gameid_idx ON public.play_by_play_p_2020 USING btree (gameid);


--
-- Name: play_by_play_p_2020_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2020_gameid_player_idx ON public.play_by_play_p_2020 USING btree (gameid, player);


--
-- Name: play_by_play_p_2020_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2020_player_idx ON public.play_by_play_p_2020 USING btree (player);


--
-- Name: play_by_play_p_2020_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2020_season_idx ON public.play_by_play_p_2020 USING btree (season);


--
-- Name: play_by_play_p_2021_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2021_event_type_idx ON public.play_by_play_p_2021 USING btree (event_type);


--
-- Name: play_by_play_p_2021_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2021_gameid_idx ON public.play_by_play_p_2021 USING btree (gameid);


--
-- Name: play_by_play_p_2021_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2021_gameid_player_idx ON public.play_by_play_p_2021 USING btree (gameid, player);


--
-- Name: play_by_play_p_2021_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2021_player_idx ON public.play_by_play_p_2021 USING btree (player);


--
-- Name: play_by_play_p_2021_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2021_season_idx ON public.play_by_play_p_2021 USING btree (season);


--
-- Name: play_by_play_p_2022_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2022_event_type_idx ON public.play_by_play_p_2022 USING btree (event_type);


--
-- Name: play_by_play_p_2022_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2022_gameid_idx ON public.play_by_play_p_2022 USING btree (gameid);


--
-- Name: play_by_play_p_2022_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2022_gameid_player_idx ON public.play_by_play_p_2022 USING btree (gameid, player);


--
-- Name: play_by_play_p_2022_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2022_player_idx ON public.play_by_play_p_2022 USING btree (player);


--
-- Name: play_by_play_p_2022_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2022_season_idx ON public.play_by_play_p_2022 USING btree (season);


--
-- Name: play_by_play_p_2023_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2023_event_type_idx ON public.play_by_play_p_2023 USING btree (event_type);


--
-- Name: play_by_play_p_2023_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2023_gameid_idx ON public.play_by_play_p_2023 USING btree (gameid);


--
-- Name: play_by_play_p_2023_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2023_gameid_player_idx ON public.play_by_play_p_2023 USING btree (gameid, player);


--
-- Name: play_by_play_p_2023_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2023_player_idx ON public.play_by_play_p_2023 USING btree (player);


--
-- Name: play_by_play_p_2023_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2023_season_idx ON public.play_by_play_p_2023 USING btree (season);


--
-- Name: play_by_play_p_2024_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2024_event_type_idx ON public.play_by_play_p_2024 USING btree (event_type);


--
-- Name: play_by_play_p_2024_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2024_gameid_idx ON public.play_by_play_p_2024 USING btree (gameid);


--
-- Name: play_by_play_p_2024_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2024_gameid_player_idx ON public.play_by_play_p_2024 USING btree (gameid, player);


--
-- Name: play_by_play_p_2024_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2024_player_idx ON public.play_by_play_p_2024 USING btree (player);


--
-- Name: play_by_play_p_2024_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2024_season_idx ON public.play_by_play_p_2024 USING btree (season);


--
-- Name: play_by_play_p_2025_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2025_event_type_idx ON public.play_by_play_p_2025 USING btree (event_type);


--
-- Name: play_by_play_p_2025_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2025_gameid_idx ON public.play_by_play_p_2025 USING btree (gameid);


--
-- Name: play_by_play_p_2025_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2025_gameid_player_idx ON public.play_by_play_p_2025 USING btree (gameid, player);


--
-- Name: play_by_play_p_2025_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2025_player_idx ON public.play_by_play_p_2025 USING btree (player);


--
-- Name: play_by_play_p_2025_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2025_season_idx ON public.play_by_play_p_2025 USING btree (season);


--
-- Name: play_by_play_p_2026_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2026_event_type_idx ON public.play_by_play_p_2026 USING btree (event_type);


--
-- Name: play_by_play_p_2026_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2026_gameid_idx ON public.play_by_play_p_2026 USING btree (gameid);


--
-- Name: play_by_play_p_2026_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2026_gameid_player_idx ON public.play_by_play_p_2026 USING btree (gameid, player);


--
-- Name: play_by_play_p_2026_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2026_player_idx ON public.play_by_play_p_2026 USING btree (player);


--
-- Name: play_by_play_p_2026_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2026_season_idx ON public.play_by_play_p_2026 USING btree (season);


--
-- Name: play_by_play_p_2027_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2027_event_type_idx ON public.play_by_play_p_2027 USING btree (event_type);


--
-- Name: play_by_play_p_2027_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2027_gameid_idx ON public.play_by_play_p_2027 USING btree (gameid);


--
-- Name: play_by_play_p_2027_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2027_gameid_player_idx ON public.play_by_play_p_2027 USING btree (gameid, player);


--
-- Name: play_by_play_p_2027_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2027_player_idx ON public.play_by_play_p_2027 USING btree (player);


--
-- Name: play_by_play_p_2027_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_2027_season_idx ON public.play_by_play_p_2027 USING btree (season);


--
-- Name: play_by_play_p_default_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_default_event_type_idx ON public.play_by_play_p_default USING btree (event_type);


--
-- Name: play_by_play_p_default_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_default_gameid_idx ON public.play_by_play_p_default USING btree (gameid);


--
-- Name: play_by_play_p_default_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_default_gameid_player_idx ON public.play_by_play_p_default USING btree (gameid, player);


--
-- Name: play_by_play_p_default_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_default_player_idx ON public.play_by_play_p_default USING btree (player);


--
-- Name: play_by_play_p_default_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_p_default_season_idx ON public.play_by_play_p_default USING btree (season);


--
-- Name: player_gamelog_jones_fix_bak_br_player_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_jones_fix_bak_br_player_id_idx ON public.player_gamelog_jones_fix_bak USING btree (br_player_id);


--
-- Name: player_gamelog_jones_fix_bak_game_id_full_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_jones_fix_bak_game_id_full_idx ON public.player_gamelog_jones_fix_bak USING btree (game_id_full);


--
-- Name: player_gamelog_jones_fix_bak_gameid_br_player_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX player_gamelog_jones_fix_bak_gameid_br_player_id_idx ON public.player_gamelog_jones_fix_bak USING btree (gameid, br_player_id) WHERE (br_player_id IS NOT NULL);


--
-- Name: player_gamelog_jones_fix_bak_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_jones_fix_bak_gameid_idx ON public.player_gamelog_jones_fix_bak USING btree (gameid);


--
-- Name: player_gamelog_jones_fix_bak_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_jones_fix_bak_gameid_player_idx ON public.player_gamelog_jones_fix_bak USING btree (gameid, player);


--
-- Name: player_gamelog_jones_fix_bak_player_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_jones_fix_bak_player_id_idx ON public.player_gamelog_jones_fix_bak USING btree (player_id);


--
-- Name: player_gamelog_jones_fix_bak_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_jones_fix_bak_player_idx ON public.player_gamelog_jones_fix_bak USING btree (player);


--
-- Name: player_gamelog_jones_fix_bak_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_jones_fix_bak_season_idx ON public.player_gamelog_jones_fix_bak USING btree (season);


--
-- Name: player_gamelog_jones_fix_bak_season_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_jones_fix_bak_season_player_idx ON public.player_gamelog_jones_fix_bak USING btree (season, player);


--
-- Name: player_gamelog_jones_fix_bak_team_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_jones_fix_bak_team_idx ON public.player_gamelog_jones_fix_bak USING btree (team);


--
-- Name: player_gamelog_teamown_fix_bak_br_player_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_teamown_fix_bak_br_player_id_idx ON public.player_gamelog_teamown_fix_bak USING btree (br_player_id);


--
-- Name: player_gamelog_teamown_fix_bak_game_id_full_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_teamown_fix_bak_game_id_full_idx ON public.player_gamelog_teamown_fix_bak USING btree (game_id_full);


--
-- Name: player_gamelog_teamown_fix_bak_gameid_br_player_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX player_gamelog_teamown_fix_bak_gameid_br_player_id_idx ON public.player_gamelog_teamown_fix_bak USING btree (gameid, br_player_id) WHERE (br_player_id IS NOT NULL);


--
-- Name: player_gamelog_teamown_fix_bak_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_teamown_fix_bak_gameid_idx ON public.player_gamelog_teamown_fix_bak USING btree (gameid);


--
-- Name: player_gamelog_teamown_fix_bak_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_teamown_fix_bak_gameid_player_idx ON public.player_gamelog_teamown_fix_bak USING btree (gameid, player);


--
-- Name: player_gamelog_teamown_fix_bak_player_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_teamown_fix_bak_player_id_idx ON public.player_gamelog_teamown_fix_bak USING btree (player_id);


--
-- Name: player_gamelog_teamown_fix_bak_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_teamown_fix_bak_player_idx ON public.player_gamelog_teamown_fix_bak USING btree (player);


--
-- Name: player_gamelog_teamown_fix_bak_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_teamown_fix_bak_season_idx ON public.player_gamelog_teamown_fix_bak USING btree (season);


--
-- Name: player_gamelog_teamown_fix_bak_season_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_teamown_fix_bak_season_player_idx ON public.player_gamelog_teamown_fix_bak USING btree (season, player);


--
-- Name: player_gamelog_teamown_fix_bak_team_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_teamown_fix_bak_team_idx ON public.player_gamelog_teamown_fix_bak USING btree (team);


--
-- Name: uq_player_shooting_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_player_shooting_key ON public.player_shooting USING btree (player_id, season, season_type, team);


--
-- Name: ux_dim_games_nba_api_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_dim_games_nba_api_id ON public.dim_games USING btree (nba_api_id) WHERE (nba_api_id IS NOT NULL);


--
-- Name: ux_player_gamelog_game_player; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_player_gamelog_game_player ON public.player_gamelog USING btree (gameid, br_player_id) WHERE (br_player_id IS NOT NULL);


--
-- Name: play_by_play_p_1997_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_1997_event_type_idx;


--
-- Name: play_by_play_p_1997_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_1997_gameid_idx;


--
-- Name: play_by_play_p_1997_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_1997_gameid_player_idx;


--
-- Name: play_by_play_p_1997_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_1997_id_season_key;


--
-- Name: play_by_play_p_1997_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_1997_player_idx;


--
-- Name: play_by_play_p_1997_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_1997_season_idx;


--
-- Name: play_by_play_p_1998_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_1998_event_type_idx;


--
-- Name: play_by_play_p_1998_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_1998_gameid_idx;


--
-- Name: play_by_play_p_1998_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_1998_gameid_player_idx;


--
-- Name: play_by_play_p_1998_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_1998_id_season_key;


--
-- Name: play_by_play_p_1998_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_1998_player_idx;


--
-- Name: play_by_play_p_1998_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_1998_season_idx;


--
-- Name: play_by_play_p_1999_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_1999_event_type_idx;


--
-- Name: play_by_play_p_1999_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_1999_gameid_idx;


--
-- Name: play_by_play_p_1999_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_1999_gameid_player_idx;


--
-- Name: play_by_play_p_1999_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_1999_id_season_key;


--
-- Name: play_by_play_p_1999_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_1999_player_idx;


--
-- Name: play_by_play_p_1999_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_1999_season_idx;


--
-- Name: play_by_play_p_2000_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2000_event_type_idx;


--
-- Name: play_by_play_p_2000_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2000_gameid_idx;


--
-- Name: play_by_play_p_2000_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2000_gameid_player_idx;


--
-- Name: play_by_play_p_2000_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2000_id_season_key;


--
-- Name: play_by_play_p_2000_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2000_player_idx;


--
-- Name: play_by_play_p_2000_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2000_season_idx;


--
-- Name: play_by_play_p_2001_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2001_event_type_idx;


--
-- Name: play_by_play_p_2001_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2001_gameid_idx;


--
-- Name: play_by_play_p_2001_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2001_gameid_player_idx;


--
-- Name: play_by_play_p_2001_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2001_id_season_key;


--
-- Name: play_by_play_p_2001_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2001_player_idx;


--
-- Name: play_by_play_p_2001_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2001_season_idx;


--
-- Name: play_by_play_p_2002_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2002_event_type_idx;


--
-- Name: play_by_play_p_2002_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2002_gameid_idx;


--
-- Name: play_by_play_p_2002_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2002_gameid_player_idx;


--
-- Name: play_by_play_p_2002_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2002_id_season_key;


--
-- Name: play_by_play_p_2002_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2002_player_idx;


--
-- Name: play_by_play_p_2002_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2002_season_idx;


--
-- Name: play_by_play_p_2003_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2003_event_type_idx;


--
-- Name: play_by_play_p_2003_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2003_gameid_idx;


--
-- Name: play_by_play_p_2003_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2003_gameid_player_idx;


--
-- Name: play_by_play_p_2003_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2003_id_season_key;


--
-- Name: play_by_play_p_2003_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2003_player_idx;


--
-- Name: play_by_play_p_2003_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2003_season_idx;


--
-- Name: play_by_play_p_2004_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2004_event_type_idx;


--
-- Name: play_by_play_p_2004_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2004_gameid_idx;


--
-- Name: play_by_play_p_2004_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2004_gameid_player_idx;


--
-- Name: play_by_play_p_2004_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2004_id_season_key;


--
-- Name: play_by_play_p_2004_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2004_player_idx;


--
-- Name: play_by_play_p_2004_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2004_season_idx;


--
-- Name: play_by_play_p_2005_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2005_event_type_idx;


--
-- Name: play_by_play_p_2005_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2005_gameid_idx;


--
-- Name: play_by_play_p_2005_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2005_gameid_player_idx;


--
-- Name: play_by_play_p_2005_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2005_id_season_key;


--
-- Name: play_by_play_p_2005_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2005_player_idx;


--
-- Name: play_by_play_p_2005_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2005_season_idx;


--
-- Name: play_by_play_p_2006_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2006_event_type_idx;


--
-- Name: play_by_play_p_2006_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2006_gameid_idx;


--
-- Name: play_by_play_p_2006_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2006_gameid_player_idx;


--
-- Name: play_by_play_p_2006_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2006_id_season_key;


--
-- Name: play_by_play_p_2006_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2006_player_idx;


--
-- Name: play_by_play_p_2006_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2006_season_idx;


--
-- Name: play_by_play_p_2007_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2007_event_type_idx;


--
-- Name: play_by_play_p_2007_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2007_gameid_idx;


--
-- Name: play_by_play_p_2007_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2007_gameid_player_idx;


--
-- Name: play_by_play_p_2007_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2007_id_season_key;


--
-- Name: play_by_play_p_2007_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2007_player_idx;


--
-- Name: play_by_play_p_2007_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2007_season_idx;


--
-- Name: play_by_play_p_2008_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2008_event_type_idx;


--
-- Name: play_by_play_p_2008_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2008_gameid_idx;


--
-- Name: play_by_play_p_2008_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2008_gameid_player_idx;


--
-- Name: play_by_play_p_2008_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2008_id_season_key;


--
-- Name: play_by_play_p_2008_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2008_player_idx;


--
-- Name: play_by_play_p_2008_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2008_season_idx;


--
-- Name: play_by_play_p_2009_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2009_event_type_idx;


--
-- Name: play_by_play_p_2009_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2009_gameid_idx;


--
-- Name: play_by_play_p_2009_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2009_gameid_player_idx;


--
-- Name: play_by_play_p_2009_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2009_id_season_key;


--
-- Name: play_by_play_p_2009_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2009_player_idx;


--
-- Name: play_by_play_p_2009_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2009_season_idx;


--
-- Name: play_by_play_p_2010_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2010_event_type_idx;


--
-- Name: play_by_play_p_2010_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2010_gameid_idx;


--
-- Name: play_by_play_p_2010_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2010_gameid_player_idx;


--
-- Name: play_by_play_p_2010_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2010_id_season_key;


--
-- Name: play_by_play_p_2010_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2010_player_idx;


--
-- Name: play_by_play_p_2010_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2010_season_idx;


--
-- Name: play_by_play_p_2011_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2011_event_type_idx;


--
-- Name: play_by_play_p_2011_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2011_gameid_idx;


--
-- Name: play_by_play_p_2011_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2011_gameid_player_idx;


--
-- Name: play_by_play_p_2011_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2011_id_season_key;


--
-- Name: play_by_play_p_2011_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2011_player_idx;


--
-- Name: play_by_play_p_2011_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2011_season_idx;


--
-- Name: play_by_play_p_2012_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2012_event_type_idx;


--
-- Name: play_by_play_p_2012_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2012_gameid_idx;


--
-- Name: play_by_play_p_2012_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2012_gameid_player_idx;


--
-- Name: play_by_play_p_2012_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2012_id_season_key;


--
-- Name: play_by_play_p_2012_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2012_player_idx;


--
-- Name: play_by_play_p_2012_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2012_season_idx;


--
-- Name: play_by_play_p_2013_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2013_event_type_idx;


--
-- Name: play_by_play_p_2013_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2013_gameid_idx;


--
-- Name: play_by_play_p_2013_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2013_gameid_player_idx;


--
-- Name: play_by_play_p_2013_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2013_id_season_key;


--
-- Name: play_by_play_p_2013_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2013_player_idx;


--
-- Name: play_by_play_p_2013_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2013_season_idx;


--
-- Name: play_by_play_p_2014_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2014_event_type_idx;


--
-- Name: play_by_play_p_2014_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2014_gameid_idx;


--
-- Name: play_by_play_p_2014_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2014_gameid_player_idx;


--
-- Name: play_by_play_p_2014_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2014_id_season_key;


--
-- Name: play_by_play_p_2014_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2014_player_idx;


--
-- Name: play_by_play_p_2014_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2014_season_idx;


--
-- Name: play_by_play_p_2015_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2015_event_type_idx;


--
-- Name: play_by_play_p_2015_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2015_gameid_idx;


--
-- Name: play_by_play_p_2015_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2015_gameid_player_idx;


--
-- Name: play_by_play_p_2015_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2015_id_season_key;


--
-- Name: play_by_play_p_2015_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2015_player_idx;


--
-- Name: play_by_play_p_2015_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2015_season_idx;


--
-- Name: play_by_play_p_2016_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2016_event_type_idx;


--
-- Name: play_by_play_p_2016_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2016_gameid_idx;


--
-- Name: play_by_play_p_2016_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2016_gameid_player_idx;


--
-- Name: play_by_play_p_2016_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2016_id_season_key;


--
-- Name: play_by_play_p_2016_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2016_player_idx;


--
-- Name: play_by_play_p_2016_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2016_season_idx;


--
-- Name: play_by_play_p_2017_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2017_event_type_idx;


--
-- Name: play_by_play_p_2017_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2017_gameid_idx;


--
-- Name: play_by_play_p_2017_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2017_gameid_player_idx;


--
-- Name: play_by_play_p_2017_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2017_id_season_key;


--
-- Name: play_by_play_p_2017_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2017_player_idx;


--
-- Name: play_by_play_p_2017_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2017_season_idx;


--
-- Name: play_by_play_p_2018_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2018_event_type_idx;


--
-- Name: play_by_play_p_2018_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2018_gameid_idx;


--
-- Name: play_by_play_p_2018_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2018_gameid_player_idx;


--
-- Name: play_by_play_p_2018_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2018_id_season_key;


--
-- Name: play_by_play_p_2018_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2018_player_idx;


--
-- Name: play_by_play_p_2018_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2018_season_idx;


--
-- Name: play_by_play_p_2019_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2019_event_type_idx;


--
-- Name: play_by_play_p_2019_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2019_gameid_idx;


--
-- Name: play_by_play_p_2019_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2019_gameid_player_idx;


--
-- Name: play_by_play_p_2019_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2019_id_season_key;


--
-- Name: play_by_play_p_2019_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2019_player_idx;


--
-- Name: play_by_play_p_2019_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2019_season_idx;


--
-- Name: play_by_play_p_2020_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2020_event_type_idx;


--
-- Name: play_by_play_p_2020_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2020_gameid_idx;


--
-- Name: play_by_play_p_2020_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2020_gameid_player_idx;


--
-- Name: play_by_play_p_2020_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2020_id_season_key;


--
-- Name: play_by_play_p_2020_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2020_player_idx;


--
-- Name: play_by_play_p_2020_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2020_season_idx;


--
-- Name: play_by_play_p_2021_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2021_event_type_idx;


--
-- Name: play_by_play_p_2021_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2021_gameid_idx;


--
-- Name: play_by_play_p_2021_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2021_gameid_player_idx;


--
-- Name: play_by_play_p_2021_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2021_id_season_key;


--
-- Name: play_by_play_p_2021_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2021_player_idx;


--
-- Name: play_by_play_p_2021_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2021_season_idx;


--
-- Name: play_by_play_p_2022_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2022_event_type_idx;


--
-- Name: play_by_play_p_2022_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2022_gameid_idx;


--
-- Name: play_by_play_p_2022_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2022_gameid_player_idx;


--
-- Name: play_by_play_p_2022_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2022_id_season_key;


--
-- Name: play_by_play_p_2022_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2022_player_idx;


--
-- Name: play_by_play_p_2022_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2022_season_idx;


--
-- Name: play_by_play_p_2023_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2023_event_type_idx;


--
-- Name: play_by_play_p_2023_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2023_gameid_idx;


--
-- Name: play_by_play_p_2023_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2023_gameid_player_idx;


--
-- Name: play_by_play_p_2023_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2023_id_season_key;


--
-- Name: play_by_play_p_2023_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2023_player_idx;


--
-- Name: play_by_play_p_2023_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2023_season_idx;


--
-- Name: play_by_play_p_2024_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2024_event_type_idx;


--
-- Name: play_by_play_p_2024_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2024_gameid_idx;


--
-- Name: play_by_play_p_2024_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2024_gameid_player_idx;


--
-- Name: play_by_play_p_2024_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2024_id_season_key;


--
-- Name: play_by_play_p_2024_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2024_player_idx;


--
-- Name: play_by_play_p_2024_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2024_season_idx;


--
-- Name: play_by_play_p_2025_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2025_event_type_idx;


--
-- Name: play_by_play_p_2025_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2025_gameid_idx;


--
-- Name: play_by_play_p_2025_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2025_gameid_player_idx;


--
-- Name: play_by_play_p_2025_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2025_id_season_key;


--
-- Name: play_by_play_p_2025_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2025_player_idx;


--
-- Name: play_by_play_p_2025_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2025_season_idx;


--
-- Name: play_by_play_p_2026_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2026_event_type_idx;


--
-- Name: play_by_play_p_2026_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2026_gameid_idx;


--
-- Name: play_by_play_p_2026_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2026_gameid_player_idx;


--
-- Name: play_by_play_p_2026_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2026_id_season_key;


--
-- Name: play_by_play_p_2026_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2026_player_idx;


--
-- Name: play_by_play_p_2026_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2026_season_idx;


--
-- Name: play_by_play_p_2027_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_2027_event_type_idx;


--
-- Name: play_by_play_p_2027_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_2027_gameid_idx;


--
-- Name: play_by_play_p_2027_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_2027_gameid_player_idx;


--
-- Name: play_by_play_p_2027_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_2027_id_season_key;


--
-- Name: play_by_play_p_2027_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_2027_player_idx;


--
-- Name: play_by_play_p_2027_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_2027_season_idx;


--
-- Name: play_by_play_p_default_event_type_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_event ATTACH PARTITION public.play_by_play_p_default_event_type_idx;


--
-- Name: play_by_play_p_default_gameid_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_gameid ATTACH PARTITION public.play_by_play_p_default_gameid_idx;


--
-- Name: play_by_play_p_default_gameid_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_game_player ATTACH PARTITION public.play_by_play_p_default_gameid_player_idx;


--
-- Name: play_by_play_p_default_id_season_key; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.play_by_play_uq ATTACH PARTITION public.play_by_play_p_default_id_season_key;


--
-- Name: play_by_play_p_default_player_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_player ATTACH PARTITION public.play_by_play_p_default_player_idx;


--
-- Name: play_by_play_p_default_season_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_pbp_season ATTACH PARTITION public.play_by_play_p_default_season_idx;


--
-- Name: fact_player_season_stats fk_fpss_player; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_player_season_stats
    ADD CONSTRAINT fk_fpss_player FOREIGN KEY (player_id) REFERENCES public.dim_players(player_id);


--
-- Name: player_gamelog fk_gamelog_dim_players; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_gamelog
    ADD CONSTRAINT fk_gamelog_dim_players FOREIGN KEY (br_player_id) REFERENCES public.dim_players(player_id);


--
-- Name: player_career_honors player_career_honors_player_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_career_honors
    ADD CONSTRAINT player_career_honors_player_id_fkey FOREIGN KEY (player_id) REFERENCES public.dim_players(player_id) ON DELETE CASCADE;


--
-- Name: player_lineups player_lineups_br_pid1_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_lineups
    ADD CONSTRAINT player_lineups_br_pid1_fkey FOREIGN KEY (br_player_id1) REFERENCES public.dim_players(player_id);


--
-- Name: player_lineups player_lineups_br_pid2_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_lineups
    ADD CONSTRAINT player_lineups_br_pid2_fkey FOREIGN KEY (br_player_id2) REFERENCES public.dim_players(player_id);


--
-- Name: player_lineups player_lineups_br_pid3_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_lineups
    ADD CONSTRAINT player_lineups_br_pid3_fkey FOREIGN KEY (br_player_id3) REFERENCES public.dim_players(player_id);


--
-- Name: player_lineups player_lineups_br_pid4_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_lineups
    ADD CONSTRAINT player_lineups_br_pid4_fkey FOREIGN KEY (br_player_id4) REFERENCES public.dim_players(player_id);


--
-- Name: player_lineups player_lineups_br_pid5_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_lineups
    ADD CONSTRAINT player_lineups_br_pid5_fkey FOREIGN KEY (br_player_id5) REFERENCES public.dim_players(player_id);


--
-- Name: team_coaches team_coaches_franchise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_coaches
    ADD CONSTRAINT team_coaches_franchise_id_fkey FOREIGN KEY (franchise_id) REFERENCES public.dim_franchise(franchise_id);


--
-- Name: team_leaderboards team_leaderboards_franchise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_leaderboards
    ADD CONSTRAINT team_leaderboards_franchise_id_fkey FOREIGN KEY (franchise_id) REFERENCES public.dim_franchise(franchise_id);


--
-- Name: team_lineups team_lineups_br_player_id1_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_lineups
    ADD CONSTRAINT team_lineups_br_player_id1_fkey FOREIGN KEY (br_player_id1) REFERENCES public.dim_players(player_id);


--
-- Name: team_lineups team_lineups_br_player_id2_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_lineups
    ADD CONSTRAINT team_lineups_br_player_id2_fkey FOREIGN KEY (br_player_id2) REFERENCES public.dim_players(player_id);


--
-- Name: team_lineups team_lineups_br_player_id3_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_lineups
    ADD CONSTRAINT team_lineups_br_player_id3_fkey FOREIGN KEY (br_player_id3) REFERENCES public.dim_players(player_id);


--
-- Name: team_lineups team_lineups_br_player_id4_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_lineups
    ADD CONSTRAINT team_lineups_br_player_id4_fkey FOREIGN KEY (br_player_id4) REFERENCES public.dim_players(player_id);


--
-- Name: team_lineups team_lineups_br_player_id5_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_lineups
    ADD CONSTRAINT team_lineups_br_player_id5_fkey FOREIGN KEY (br_player_id5) REFERENCES public.dim_players(player_id);


--
-- Name: team_lineups team_lineups_franchise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_lineups
    ADD CONSTRAINT team_lineups_franchise_id_fkey FOREIGN KEY (franchise_id) REFERENCES public.dim_franchise(franchise_id);


--
-- Name: team_logos team_logos_franchise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_logos
    ADD CONSTRAINT team_logos_franchise_id_fkey FOREIGN KEY (franchise_id) REFERENCES public.dim_franchise(franchise_id);


--
-- Name: team_on_off team_on_off_br_player_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_on_off
    ADD CONSTRAINT team_on_off_br_player_id_fkey FOREIGN KEY (br_player_id) REFERENCES public.dim_players(player_id);


--
-- Name: team_per_36 team_per_36_franchise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_per_36
    ADD CONSTRAINT team_per_36_franchise_id_fkey FOREIGN KEY (franchise_id) REFERENCES public.dim_franchise(franchise_id);


--
-- Name: team_referees team_referees_franchise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_referees
    ADD CONSTRAINT team_referees_franchise_id_fkey FOREIGN KEY (franchise_id) REFERENCES public.dim_franchise(franchise_id);


--
-- Name: team_roster team_roster_franchise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_roster
    ADD CONSTRAINT team_roster_franchise_id_fkey FOREIGN KEY (franchise_id) REFERENCES public.dim_franchise(franchise_id);


--
-- Name: team_summaries team_summaries_franchise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_summaries
    ADD CONSTRAINT team_summaries_franchise_id_fkey FOREIGN KEY (franchise_id) REFERENCES public.dim_franchise(franchise_id);


--
-- PostgreSQL database dump complete
--


