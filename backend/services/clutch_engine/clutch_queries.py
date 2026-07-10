"""NBACore v8 — Clutch engine SQL builder (read-only SELECT only).

Builds a single CTE-chain SELECT aggregating ``play_by_play`` rows that fall
inside the clutch window (period = :period, clock <= :clock_max,
|derived margin| <= :margin_max). All aggregate SQL lives HERE — the API
router only orchestrates. The produced SQL is validated by ``db.validate_batch_sql``
on execution (SELECT-only; no DML/DDL).

Parameter style: positional ``%s`` (consumed by psycopg2). Literal ``%``
inside LIKE patterns are doubled (``%%``) so psycopg2 renders them as ``%``.
"""
from __future__ import annotations

from backend.core.clutch_constants import GAMES_TABLE, PBP_TABLE
from backend.services.clutch_engine import clutch_utils as u


def build_clutch_players_sql(
    period: int = 4,
    clock_max: int = 300,
    margin_max: int = 5,
    season: int | None = None,
    min_poss: int = 10,
    gameid: str | None = None,
) -> tuple[str, list]:
    """Return ``(sql, params)`` for the per-player clutch aggregation.

    params order: ``[period, clock_max, season, season, margin_max, min_poss]``.
    The season filter uses ``season IS NULL OR season = :season`` so that a
    ``NULL`` season (the default "all seasons") passes everything while a
    concrete season restricts to that season.
    """
    src_prio = u.source_priority_sql("source")
    parse_margin = u.parse_score_margin_sql("scoremargin")
    derive_margin = u.derive_margin_sql("base_margin", "h_fill", "a_fill")
    shot_type = u.shot_type_sql("event_type", "subtype")
    shot_value = u.shot_value_sql(
        source_col="source",
        subtype_col="subtype",
        desc_col="description",
        is_fg_col="is_fg",
        shot_delta_col="shot_delta",
    )
    finish_type = u.finish_type_sql("source", "subtype")

    season_filter = "AND (%s IS NULL OR season = %s)"

    sql = f"""
    WITH src_priority AS (
        SELECT
            *,
            {src_prio} AS src_priority
        FROM {PBP_TABLE}
        WHERE period = %s
          AND clock_seconds <= %s
          {season_filter}
          AND (%s IS NULL OR gameid = %s)
          AND player IS NOT NULL AND player <> ''
    ),
    dedup AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY gameid, eventnum ORDER BY src_priority
            ) AS rn
        FROM src_priority
    ),
    clutch_base AS (
        SELECT
            gameid, eventnum, period, clock_seconds,
            season, source, team, playerid, player,
            event_type, subtype, description,
            h_pts, a_pts,
            CASE WHEN source = 'BBRef' THEN {parse_margin} ELSE NULL END AS base_margin
        FROM dedup
        WHERE rn = 1
    ),
    clutch AS (
        SELECT
            *,
            MAX(h_pts) OVER (
                PARTITION BY gameid ORDER BY eventnum
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS h_fill,
            MAX(a_pts) OVER (
                PARTITION BY gameid ORDER BY eventnum
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS a_fill,
            (COALESCE(h_pts, 0) + COALESCE(a_pts, 0)) AS total,
            COALESCE(
                LAG(COALESCE(h_pts, 0) + COALESCE(a_pts, 0)) OVER (
                    PARTITION BY gameid ORDER BY eventnum
                ), 0
            ) AS prev_total
        FROM clutch_base
    ),
    clutch_win AS (
        SELECT *,
            {derive_margin} AS margin,
            (total - prev_total) AS shot_delta
        FROM clutch
        WHERE ABS({derive_margin}) <= %s
    ),
    enriched AS (
        SELECT *,
            {shot_type} AS shot_type,
            {finish_type} AS finish_type
        FROM clutch_win
    ),
    enriched_flags AS (
        SELECT *,
            (
                shot_type IN ('Jump Shot', 'Layup', 'Dunk', 'Hook', 'Tip')
                OR (event_type ILIKE '%%shot%%' AND shot_type <> 'Free Throw')
            ) AS is_fg,
            (shot_type = 'Free Throw') AS is_ft
        FROM enriched
    ),
    enriched_val AS (
        SELECT *,
            {shot_value} AS shot_value,
            (
                (is_fg AND (total - prev_total) IN (2, 3))
                OR (is_ft AND (total - prev_total) = 1)
            ) AS is_make
        FROM enriched_flags
    )
    SELECT
        player AS player_name,
        MAX(playerid) AS player_id,
        MAX(NULLIF(team, '')) AS team,
        COUNT(*) AS poss,
        SUM(CASE WHEN is_fg THEN 1 ELSE 0 END)::int AS fga,
        SUM(CASE WHEN is_fg AND is_make THEN 1 ELSE 0 END)::int AS fgm,
        SUM(CASE WHEN is_fg AND shot_value = 2 THEN 1 ELSE 0 END)::int AS fga2,
        SUM(CASE WHEN is_fg AND shot_value = 2 AND is_make THEN 1 ELSE 0 END)::int AS fgm2,
        SUM(CASE WHEN is_fg AND shot_value = 3 THEN 1 ELSE 0 END)::int AS fga3,
        SUM(CASE WHEN is_fg AND shot_value = 3 AND is_make THEN 1 ELSE 0 END)::int AS fgm3,
        SUM(CASE WHEN is_ft THEN 1 ELSE 0 END)::int AS fta,
        SUM(CASE WHEN is_ft AND is_make THEN 1 ELSE 0 END)::int AS ftm,
        SUM(CASE WHEN finish_type = 'catch' THEN 1 ELSE 0 END)::int AS catch_shots,
        SUM(CASE WHEN finish_type = 'dribble' THEN 1 ELSE 0 END)::int AS dribble_shots,
        SUM(CASE WHEN (event_type ILIKE '%%rebound%%' OR subtype ILIKE '%%rebound%%')
                 AND subtype ILIKE '%%offensive%%' THEN 1 ELSE 0 END)::int AS oreb,
        SUM(CASE WHEN (event_type ILIKE '%%rebound%%' OR subtype ILIKE '%%rebound%%')
                 AND subtype ILIKE '%%defensive%%' THEN 1 ELSE 0 END)::int AS dreb,
        SUM(CASE WHEN event_type ILIKE '%%assist%%' OR subtype ILIKE '%%assist%%' THEN 1 ELSE 0 END)::int AS ast,
        SUM(CASE WHEN event_type ILIKE '%%steal%%' OR subtype ILIKE '%%steal%%' THEN 1 ELSE 0 END)::int AS stl,
        SUM(CASE WHEN event_type ILIKE '%%turnover%%' OR subtype ILIKE '%%turnover%%' THEN 1 ELSE 0 END)::int AS tov,
        SUM(CASE WHEN event_type ILIKE '%%foul%%' OR subtype ILIKE '%%foul%%' THEN 1 ELSE 0 END)::int AS pf,
        (
            SUM(CASE WHEN is_fg AND is_make THEN shot_value ELSE 0 END)
            + SUM(CASE WHEN is_ft AND is_make THEN 1 ELSE 0 END)
        )::int AS pts
    FROM enriched_val
    GROUP BY player
    HAVING SUM(CASE WHEN is_fg THEN 1 ELSE 0 END) >= %s
    """

    params: list = [period, clock_max, season, season, gameid, gameid, margin_max, min_poss]
    return sql, params


def build_clutch_events_sql(
    gameid: str,
    season,
    period: int = 4,
    clock_max: int = 300,
    margin_max: int = 5,
) -> tuple[str, list]:
    """Return ``(sql, params)`` for *event-level* clutch rows of ONE game.

    Reuses the same CTE chain as :func:`build_clutch_players_sql` (with the
    same ``clutch_utils`` fragments) but terminates at the per-event level and
    restricts to ``source = 'br_crawler'`` so every returned ``eventnum`` has a
    matching tactics replay frame. The terminal SELECT projects the columns the
    fusion mapper needs: ``(eventnum, period, clock_seconds, playerid, player,
    team, margin)``.

    params order: ``[period, clock_max, gameid, season, margin_max]``.
    """
    src_prio = u.source_priority_sql("source")
    parse_margin = u.parse_score_margin_sql("scoremargin")
    derive_margin = u.derive_margin_sql("base_margin", "h_fill", "a_fill")

    sql = f"""
    WITH src_priority AS (
        SELECT *,
            {src_prio} AS src_priority
        FROM {PBP_TABLE}
        WHERE period = %s
          AND clock_seconds <= %s
          AND gameid = %s
          AND season = %s::integer
          AND source = 'br_crawler'
          AND player IS NOT NULL AND player <> ''
    ),
    dedup AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY gameid, eventnum ORDER BY src_priority
            ) AS rn
        FROM src_priority
    ),
    clutch_base AS (
        SELECT
            gameid, eventnum, period, clock_seconds,
            season, source, team, playerid, player,
            h_pts, a_pts,
            CASE WHEN source = 'BBRef' THEN {parse_margin} ELSE NULL END AS base_margin
        FROM dedup
        WHERE rn = 1
    ),
    clutch AS (
        SELECT
            *,
            MAX(h_pts) OVER (
                PARTITION BY gameid ORDER BY eventnum
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS h_fill,
            MAX(a_pts) OVER (
                PARTITION BY gameid ORDER BY eventnum
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS a_fill,
            (COALESCE(h_pts, 0) + COALESCE(a_pts, 0)) AS total,
            COALESCE(
                LAG(COALESCE(h_pts, 0) + COALESCE(a_pts, 0)) OVER (
                    PARTITION BY gameid ORDER BY eventnum
                ), 0
            ) AS prev_total
        FROM clutch_base
    ),
    clutch_win AS (
        SELECT *,
            {derive_margin} AS margin,
            (total - prev_total) AS shot_delta
        FROM clutch
        WHERE ABS({derive_margin}) <= %s
    )
    SELECT eventnum, period, clock_seconds, playerid, player, team, margin
    FROM clutch_win
    ORDER BY clock_seconds DESC, eventnum ASC
    """

    params: list = [period, clock_max, str(gameid), int(season), margin_max]
    return sql, params


def build_seasons_sql() -> str:
    """Distinct seasons available in the curated games table."""
    return (
        f"SELECT DISTINCT season FROM {GAMES_TABLE} "
        f"WHERE season IS NOT NULL ORDER BY season"
    )
