--
-- PostgreSQL database dump
--

\restrict Lp9gcENnHEvbWzfIiFB4rT3VI13E9hbXwNjPhGAJYMD7D44Fh7xdGVPBFsn8xLG

-- Dumped from database version 17.9
-- Dumped by pg_dump version 17.9

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

SET default_tablespace = '';

SET default_table_access_method = heap;

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
-- Name: dim_draft_history_bak_20260712; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_draft_history_bak_20260712 (
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
    player_id_orig character varying
);


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
    nba_api_id bigint
);


--
-- Name: dim_games_2002_null_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_games_2002_null_bak (
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
    nba_api_id bigint
);


--
-- Name: dim_games_br_id_fix_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_games_br_id_fix_bak (
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
    nba_api_id bigint
);


--
-- Name: dim_games_recent_br_id_fix_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dim_games_recent_br_id_fix_bak (
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
    nba_api_id bigint
);


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
    year_to integer
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
-- Name: game_metadata_2002_null_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.game_metadata_2002_null_bak (
    game_id text,
    season_end integer,
    visitor_team text,
    home_team text,
    visitor_score integer,
    home_score integer,
    game_date date,
    boxscore_url text,
    pbp_saved boolean,
    pbp_imported boolean,
    saved_at timestamp without time zone,
    imported_at timestamp without time zone,
    created_at timestamp without time zone,
    location text,
    series_summary text,
    nba_gameid text,
    arena_name character varying(200),
    arena_city character varying(100),
    arena_state character varying(100),
    attendance integer,
    officials jsonb,
    duration character varying(50),
    away_q1 integer,
    away_q2 integer,
    away_q3 integer,
    away_q4 integer,
    away_ot integer,
    home_q1 integer,
    home_q2 integer,
    home_q3 integer,
    home_q4 integer,
    home_ot integer,
    api_season integer,
    api_status character varying(50)
);


--
-- Name: game_videos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.game_videos (
    id integer NOT NULL,
    gameid text NOT NULL,
    season integer NOT NULL,
    source text DEFAULT 'other'::text NOT NULL,
    video_url text,
    local_path text,
    video_offset_seconds numeric(10,3) DEFAULT 0.0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT game_videos_source_chk CHECK ((source = ANY (ARRAY['youtube'::text, 'local_file'::text, 'cloud_drive'::text, 'other'::text])))
);


--
-- Name: TABLE game_videos; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.game_videos IS 'Video Library source registration: one video per game (v1 single-offset).';


--
-- Name: COLUMN game_videos.video_offset_seconds; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.game_videos.video_offset_seconds IS 'Seconds: video t=0 relative to Q1 0:00 (NUMERIC(10,3), default 0).';


--
-- Name: game_videos_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.game_videos_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: game_videos_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.game_videos_id_seq OWNED BY public.game_videos.id;


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
-- Name: games_2002_null_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.games_2002_null_bak (
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
    nba_api_id bigint
);


--
-- Name: games_bak_pre_br; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.games_bak_pre_br (
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
    nba_api_id bigint
);


--
-- Name: games_dup2024_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.games_dup2024_bak (
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
    nba_api_id bigint
);


--
-- Name: games_dup2026_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.games_dup2026_bak (
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
    nba_api_id bigint
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
-- Name: play_by_play; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play (
    id bigint NOT NULL,
    gameid character varying(20) NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying(20),
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying(20),
    playerid character varying(20),
    player character varying(200),
    event_type character varying(50),
    subtype character varying(50),
    result character varying(50),
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying(20),
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying(20),
    scorevisitor character varying(20),
    scoremargin character varying(20),
    pctimestring character varying(20),
    player1_id character varying(20),
    player1_name character varying(200),
    player1_team_id character varying(20),
    player1_team_abbreviation character varying(10),
    player2_id character varying(20),
    player2_name character varying(200),
    player2_team_id character varying(20),
    player2_team_abbreviation character varying(10),
    player3_id character varying(20),
    player3_name character varying(200),
    player3_team_id character varying(20),
    player3_team_abbreviation character varying(10),
    source character varying(20) DEFAULT 'br_crawler'::character varying,
    br_player_id character varying(32),
    action_verb character varying(32)
);


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
-- Name: play_by_play_dup2026_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.play_by_play_dup2026_bak (
    id bigint DEFAULT nextval('public.play_by_play_new_id_seq'::regclass) NOT NULL,
    gameid character varying(20) NOT NULL,
    season integer,
    eventnum integer,
    period integer,
    clock character varying(20),
    clock_seconds double precision,
    h_pts double precision,
    a_pts double precision,
    team character varying(20),
    playerid character varying(20),
    player character varying(200),
    event_type character varying(50),
    subtype character varying(50),
    result character varying(50),
    x integer,
    y integer,
    dist integer,
    description text,
    current_team character varying(20),
    eventmsgtype integer,
    eventmsgactiontype integer,
    homedescription text,
    visitordescription text,
    neutraldescription text,
    scorehome character varying(20),
    scorevisitor character varying(20),
    scoremargin character varying(20),
    pctimestring character varying(20),
    player1_id character varying(20),
    player1_name character varying(200),
    player1_team_id character varying(20),
    player1_team_abbreviation character varying(10),
    player2_id character varying(20),
    player2_name character varying(200),
    player2_team_id character varying(20),
    player2_team_abbreviation character varying(10),
    player3_id character varying(20),
    player3_name character varying(200),
    player3_team_id character varying(20),
    player3_team_abbreviation character varying(10),
    source character varying(20) DEFAULT 'br_crawler'::character varying,
    br_player_id character varying(32)
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
    scraped_at
   FROM public.dim_players;


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
-- Name: player_gamelog_dup2026_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.player_gamelog_dup2026_bak (
    id bigint DEFAULT nextval('public.player_gamelog_id_seq'::regclass) NOT NULL,
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
    player_id bigint,
    player_name character varying(200),
    start_position character varying(10),
    minutes character varying(20),
    jersey_num character varying(10),
    "position" character varying(10),
    player_status character varying(10),
    game_id_full character varying(20),
    br_player_id character varying(32)
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
    created_at timestamp without time zone DEFAULT now()
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
    attend_g double precision
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
-- Name: v_unified_games_2002_null_bak; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.v_unified_games_2002_null_bak (
    game_id text,
    game_date date,
    season integer,
    season_type text,
    home_team_abbr text,
    away_team_abbr text,
    home_pts integer,
    away_pts integer,
    nba_api_id bigint,
    br_crawled_id character varying,
    source text
);


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
-- Name: analysis_flows id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analysis_flows ALTER COLUMN id SET DEFAULT nextval('public.analysis_flows_id_seq'::regclass);


--
-- Name: coach_stats id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coach_stats ALTER COLUMN id SET DEFAULT nextval('public.coach_stats_id_seq'::regclass);


--
-- Name: crawl_failures id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crawl_failures ALTER COLUMN id SET DEFAULT nextval('public.crawl_failures_id_seq'::regclass);


--
-- Name: dim_teams id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dim_teams ALTER COLUMN id SET DEFAULT nextval('public.team_mapping_id_seq'::regclass);


--
-- Name: draft_combine id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft_combine ALTER COLUMN id SET DEFAULT nextval('public.draft_combine_id_seq'::regclass);


--
-- Name: fact_player_season_stats id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_player_season_stats ALTER COLUMN id SET DEFAULT nextval('public.fact_player_season_stats_id_seq'::regclass);


--
-- Name: game_videos id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.game_videos ALTER COLUMN id SET DEFAULT nextval('public.game_videos_id_seq'::regclass);


--
-- Name: injuries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.injuries ALTER COLUMN id SET DEFAULT nextval('public.injuries_id_seq'::regclass);


--
-- Name: league_salary_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.league_salary_rules ALTER COLUMN id SET DEFAULT nextval('public.league_salary_rules_id_seq'::regclass);


--
-- Name: play_by_play id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play ALTER COLUMN id SET DEFAULT nextval('public.play_by_play_new_id_seq'::regclass);


--
-- Name: player_career_totals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_career_totals ALTER COLUMN id SET DEFAULT nextval('public.player_career_totals_id_seq'::regclass);


--
-- Name: player_gamelog id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_gamelog ALTER COLUMN id SET DEFAULT nextval('public.player_gamelog_id_seq'::regclass);


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
-- Name: team_game_splits id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_game_splits ALTER COLUMN id SET DEFAULT nextval('public.team_game_splits_id_seq'::regclass);


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
-- Name: analysis_flows analysis_flows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analysis_flows
    ADD CONSTRAINT analysis_flows_pkey PRIMARY KEY (id);


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
-- Name: fact_player_season_stats fact_player_season_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_player_season_stats
    ADD CONSTRAINT fact_player_season_stats_pkey PRIMARY KEY (id);


--
-- Name: game_videos game_videos_gameid_season_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.game_videos
    ADD CONSTRAINT game_videos_gameid_season_key UNIQUE (gameid, season);


--
-- Name: game_videos game_videos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.game_videos
    ADD CONSTRAINT game_videos_pkey PRIMARY KEY (id);


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
-- Name: play_by_play_dup2026_bak play_by_play_dup2026_bak_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play_dup2026_bak
    ADD CONSTRAINT play_by_play_dup2026_bak_pkey PRIMARY KEY (id);


--
-- Name: play_by_play play_by_play_new_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.play_by_play
    ADD CONSTRAINT play_by_play_new_pkey PRIMARY KEY (id);


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
-- Name: player_gamelog_dup2026_bak player_gamelog_dup2026_bak_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_gamelog_dup2026_bak
    ADD CONSTRAINT player_gamelog_dup2026_bak_pkey PRIMARY KEY (id);


--
-- Name: player_gamelog player_gamelog_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_gamelog
    ADD CONSTRAINT player_gamelog_pkey PRIMARY KEY (id);


--
-- Name: player_id_bridge player_id_bridge_player_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_id_bridge
    ADD CONSTRAINT player_id_bridge_player_name_key UNIQUE (player_name);


--
-- Name: player_name_unified player_name_unified_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_name_unified
    ADD CONSTRAINT player_name_unified_pkey PRIMARY KEY (id);


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
-- Name: player_weight_history player_weight_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.player_weight_history
    ADD CONSTRAINT player_weight_history_pkey PRIMARY KEY (player_id);


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
-- Name: team_depth_chart team_depth_chart_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_depth_chart
    ADD CONSTRAINT team_depth_chart_pkey PRIMARY KEY (id);


--
-- Name: team_depth_chart team_depth_chart_season_team_abbr_player_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_depth_chart
    ADD CONSTRAINT team_depth_chart_season_team_abbr_player_name_key UNIQUE (season, team_abbr, player_name);


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
-- Name: dim_teams team_mapping_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dim_teams
    ADD CONSTRAINT team_mapping_pkey PRIMARY KEY (id);


--
-- Name: team_payroll team_payroll_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_payroll
    ADD CONSTRAINT team_payroll_pkey PRIMARY KEY (team_abbr, season);


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
-- Name: idx_dim_players_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_players_name ON public.dim_players USING btree (player_name);


--
-- Name: idx_dim_teams_abbr; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_teams_abbr ON public.dim_teams USING btree (team_abbr);


--
-- Name: idx_dim_teams_current; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dim_teams_current ON public.dim_teams USING btree (current_code);


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
-- Name: idx_game_videos_gameid_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_game_videos_gameid_season ON public.game_videos USING btree (gameid, season);


--
-- Name: idx_gamelog_br_pid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gamelog_br_pid ON public.player_gamelog USING btree (br_player_id);


--
-- Name: idx_games_game_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_games_game_id ON public.dim_games USING btree (game_id);


--
-- Name: idx_la_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_la_lookup ON public.league_averages USING btree (lg, season, metric_type, team);


--
-- Name: idx_league_salary_rules_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_league_salary_rules_season ON public.league_salary_rules USING btree (league, season);


--
-- Name: idx_pbp_new_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pbp_new_event ON public.play_by_play USING btree (event_type);


--
-- Name: idx_pbp_new_game_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pbp_new_game_player ON public.play_by_play USING btree (gameid, player);


--
-- Name: idx_pbp_new_gameid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pbp_new_gameid ON public.play_by_play USING btree (gameid);


--
-- Name: idx_pbp_new_player; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pbp_new_player ON public.play_by_play USING btree (player);


--
-- Name: idx_pbp_new_season; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pbp_new_season ON public.play_by_play USING btree (season);


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
-- Name: idx_pnu_abbr; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pnu_abbr ON public.player_name_unified USING btree (abbreviation);


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
-- Name: idx_team_mapping_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_team_mapping_code ON public.dim_teams USING btree (team_abbr);


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
-- Name: play_by_play_dup2026_bak_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_dup2026_bak_event_type_idx ON public.play_by_play_dup2026_bak USING btree (event_type);


--
-- Name: play_by_play_dup2026_bak_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_dup2026_bak_gameid_idx ON public.play_by_play_dup2026_bak USING btree (gameid);


--
-- Name: play_by_play_dup2026_bak_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_dup2026_bak_gameid_player_idx ON public.play_by_play_dup2026_bak USING btree (gameid, player);


--
-- Name: play_by_play_dup2026_bak_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_dup2026_bak_player_idx ON public.play_by_play_dup2026_bak USING btree (player);


--
-- Name: play_by_play_dup2026_bak_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX play_by_play_dup2026_bak_season_idx ON public.play_by_play_dup2026_bak USING btree (season);


--
-- Name: player_gamelog_dup2026_bak_br_player_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_dup2026_bak_br_player_id_idx ON public.player_gamelog_dup2026_bak USING btree (br_player_id);


--
-- Name: player_gamelog_dup2026_bak_gameid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_dup2026_bak_gameid_idx ON public.player_gamelog_dup2026_bak USING btree (gameid);


--
-- Name: player_gamelog_dup2026_bak_gameid_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_dup2026_bak_gameid_player_idx ON public.player_gamelog_dup2026_bak USING btree (gameid, player);


--
-- Name: player_gamelog_dup2026_bak_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_dup2026_bak_player_idx ON public.player_gamelog_dup2026_bak USING btree (player);


--
-- Name: player_gamelog_dup2026_bak_season_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_dup2026_bak_season_idx ON public.player_gamelog_dup2026_bak USING btree (season);


--
-- Name: player_gamelog_dup2026_bak_season_player_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_dup2026_bak_season_player_idx ON public.player_gamelog_dup2026_bak USING btree (season, player);


--
-- Name: player_gamelog_dup2026_bak_team_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX player_gamelog_dup2026_bak_team_idx ON public.player_gamelog_dup2026_bak USING btree (team);


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
-- PostgreSQL database dump complete
--

\unrestrict Lp9gcENnHEvbWzfIiFB4rT3VI13E9hbXwNjPhGAJYMD7D44Fh7xdGVPBFsn8xLG

