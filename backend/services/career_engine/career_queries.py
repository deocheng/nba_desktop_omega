"""NBACore v8.2-C — Career engine SQL builders (read-only SELECT only).

All aggregation SQL lives HERE. The API router only orchestrates and never
contains a SQL substring. Every builder returns ``(sql, params)`` where params
is a flat list consumed positionally by psycopg2 (``%s`` placeholders).

Design notes (validated against the live schema):
    - ``fact_player_season_stats`` has no ``pts_per_game`` column, so that
      metric is derived via ``pts / g`` inside METRIC_WHITELIST[...]["expr"].
    - Duplicate (player, season) rows (regular vs playoffs, multi-team trades)
      are collapsed by a ``ROW_NUMBER() OVER (PARTITION BY player_id, season
      ORDER BY g DESC)`` dedup that keeps the regular-season row with the most
      games — mirroring growth_loader. ``season_type = 'Regular'`` filters
      playoffs out entirely.
    - All SQL is validated by ``db.validate_batch_sql`` on execution.
"""
from __future__ import annotations

from backend.services.career_engine import career_constants as C
from backend.services.career_engine import career_utils as u


def build_peak_sql(
    metric: str,
    min_games: int = C.DEFAULT_MIN_GAMES,
    position: str | None = None,
    era: str | None = None,
    limit: int = C.DEFAULT_LIMIT,
) -> tuple[str, list]:
    """Career-best single-season value per player, ranked, top ``limit``.

    Peak = ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY metric DESC
    NULLS LAST) rank 1. ``second_value`` is the rank-2 value (context).
    """
    metric_expr = C.metric_expr(metric)
    era_range = u._parse_era(era)
    pos_group = u._pos_group(position)

    params: list = list(C.EXCLUDED_TEAMS)
    params.append(C.SEASON_TYPE)
    params.append(int(min_games))
    if pos_group:
        params.append(pos_group)
    if era_range:
        params.append(era_range[0])
        params.append(era_range[1])
    params.append(int(limit))

    pos_filter = f"AND {u.pos_group_sql('f.pos')} = %s" if pos_group else ""
    era_filter = "AND f.season >= %s AND f.season <= %s" if era_range else ""

    sql = f"""
    WITH raw AS (
        SELECT f.player_id, f.season, f.age, f.team, f.pos,
               {metric_expr} AS metric_value,
               ROW_NUMBER() OVER (
                   PARTITION BY f.player_id, f.season ORDER BY f.g DESC
               ) AS drn
        FROM {C.FACT_TABLE} f
        WHERE f.team NOT IN ({u._in_placeholders(C.EXCLUDED_TEAMS)})
          AND f.season_type = %s
          AND f.g >= %s
          {pos_filter}
          {era_filter}
    ),
    base AS (
        SELECT player_id, season, age, team, pos, metric_value
        FROM raw WHERE drn = 1
    ),
    ranked AS (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY player_id
                   ORDER BY metric_value DESC NULLS LAST
               ) AS rn
        FROM base
    ),
    peak_rows AS (
        SELECT player_id,
               MAX(CASE WHEN rn = 1 THEN metric_value END) AS peak_value,
               MAX(CASE WHEN rn = 2 THEN metric_value END) AS second_value,
               MAX(CASE WHEN rn = 1 THEN season END)::int AS peak_season,
               MAX(CASE WHEN rn = 1 THEN age END) AS peak_age,
               MAX(CASE WHEN rn = 1 THEN team END) AS peak_team,
               COUNT(*)::int AS seasons_played
        FROM ranked
        GROUP BY player_id
    )
    SELECT p.player_id,
           COALESCE(p.full_name, p.player_name) AS player_name,
           pr.peak_value,
           pr.peak_season,
           pr.peak_age,
           pr.peak_team,
           pr.second_value,
           pr.seasons_played,
           p.birth_date
    FROM peak_rows pr
    JOIN {C.PLAYERS_TABLE} p ON p.player_id = pr.player_id
    WHERE pr.peak_value IS NOT NULL
    ORDER BY pr.peak_value DESC
    LIMIT %s
    """
    return sql, params


def build_age_curve_sql(
    player_ids: list[str],
    metric: str,
    min_games: int = C.DEFAULT_AGE_CURVE_MIN_GAMES,
) -> tuple[str, list]:
    """Per-season (age, value) curve for 1..N players, ordered by age.

    Returns columns: player_id, player_name, season, age, team, metric_value,
    birth_date (birth_date enables the age fallback in the service).
    """
    if not player_ids:
        raise ValueError("player_ids must contain at least one id")
    metric_expr = C.metric_expr(metric)
    params: list = list(player_ids)
    params.extend(C.EXCLUDED_TEAMS)
    params.append(C.SEASON_TYPE)
    params.append(int(min_games))

    sql = f"""
    WITH raw AS (
        SELECT f.player_id,
               COALESCE(p.full_name, p.player_name) AS player_name,
               f.season, f.age, f.team,
               {metric_expr} AS metric_value,
               p.birth_date AS birth_date,
               ROW_NUMBER() OVER (
                   PARTITION BY f.player_id, f.season ORDER BY f.g DESC
               ) AS drn
        FROM {C.FACT_TABLE} f
        JOIN {C.PLAYERS_TABLE} p ON p.player_id = f.player_id
        WHERE f.player_id IN ({u._in_placeholders(player_ids)})
          AND f.team NOT IN ({u._in_placeholders(C.EXCLUDED_TEAMS)})
          AND f.season_type = %s
          AND f.g >= %s
    )
    SELECT player_id, player_name, season, age, team, metric_value, birth_date
    FROM raw
    WHERE drn = 1
    ORDER BY player_id, age ASC, season ASC
    """
    return sql, params


def build_similar_candidates_sql(
    metric: str,
    min_games: int = C.DEFAULT_MIN_GAMES,
    target_pos: str | None = None,
    same_position: bool = True,
    min_seasons: int = C.DEFAULT_MIN_SEASONS,
) -> tuple[str, list]:
    """All candidate (player, season) rows for Similar Evolution.

    Optionally restricted to the target's G/F/C position group. ``min_seasons``
    is enforced in the service (after grouping) so the SQL only needs the
    per-season filters. Returns player_id, player_name, season, age,
    metric_value, birth_date, pos.
    """
    metric_expr = C.metric_expr(metric)
    pos_group = u._pos_group(target_pos) if same_position else None

    params: list = list(C.EXCLUDED_TEAMS)
    params.append(C.SEASON_TYPE)
    params.append(int(min_games))
    if pos_group:
        params.append(pos_group)

    pos_filter = f"AND {u.pos_group_sql('f.pos')} = %s" if pos_group else ""

    sql = f"""
    WITH raw AS (
        SELECT f.player_id,
               COALESCE(p.full_name, p.player_name) AS player_name,
               f.season, f.age, f.team, f.pos,
               {metric_expr} AS metric_value,
               p.birth_date AS birth_date,
               ROW_NUMBER() OVER (
                   PARTITION BY f.player_id, f.season ORDER BY f.g DESC
               ) AS drn
        FROM {C.FACT_TABLE} f
        JOIN {C.PLAYERS_TABLE} p ON p.player_id = f.player_id
        WHERE f.team NOT IN ({u._in_placeholders(C.EXCLUDED_TEAMS)})
          AND f.season_type = %s
          AND f.g >= %s
          {pos_filter}
    )
    SELECT player_id, player_name, season, age, team, pos,
           metric_value, birth_date
    FROM raw
    WHERE drn = 1
    ORDER BY player_id, age ASC, season ASC
    """
    return sql, params
