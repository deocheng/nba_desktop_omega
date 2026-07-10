"""NBACore v8 — Clutch engine SQL-fragment + rating helpers.

Every ``*_sql`` function returns a *SQL expression string* (no execution).
They are composed by ``clutch_queries`` into a single read-only SELECT.
``round_rate`` is a pure Python post-processor used by the service.

No DB / pandas / psycopg2 here — these helpers are trivially unit-testable
and keep all aggregation SQL in exactly one place (clutch_queries).
"""
from __future__ import annotations

from backend.core.clutch_constants import (
    SOURCE_BBREF,
    SOURCE_BR_CRAWLER,
    SOURCE_NBA_API,
    SOURCE_PRIORITY,
)


def source_priority_sql(source_col: str = "source") -> str:
    """CASE expression mapping a source name to its dedup priority (low = keep)."""
    parts = " ".join(
        f"WHEN {source_col} = '{src}' THEN {pri}"
        for src, pri in sorted(SOURCE_PRIORITY.items(), key=lambda kv: kv[1])
    )
    return f"CASE {parts} ELSE 9 END"


def parse_score_margin_sql(col: str = "scoremargin") -> str:
    """Parse a BBRef ``scoremargin`` varchar ('3', '-11', 'TIE') to an int.

    TIE -> 0, NULL -> NULL, otherwise strip everything except [0-9-]
    and cast to int.
    """
    return (
        f"CASE WHEN {col} IS NULL THEN NULL "
        f"WHEN {col} = 'TIE' THEN 0 "
        f"ELSE NULLIF(REGEXP_REPLACE({col}, '[^0-9-]', '', 'g'), '')::int END"
    )


def derive_margin_sql(base_margin_expr: str, h_fill: str, a_fill: str) -> str:
    """Coalesce the BBRef-parsed margin with the derived |h - a| fallback."""
    return (
        f"COALESCE({base_margin_expr}, "
        f"ABS(COALESCE({h_fill}, 0) - COALESCE({a_fill}, 0)))"
    )


def shot_value_sql(
    source_col: str = "source",
    subtype_col: str = "subtype",
    desc_col: str = "description",
    is_fg_col: str = "is_fg",
    shot_delta_col: str = "shot_delta",
) -> str:
    """2/3-point value of a shot attempt (NULL when indistinguishable).

    * BBRef: ``^3-pt`` -> 3, ``^2-pt`` -> 2 (regex on subtype).
    * br_crawler: made-shot score delta in {2,3} wins; a missed shot falls
      back to a ``3-pt``/``three`` substring in the description. A missed
      FG attempt with no 3-pt signal is, by definition, a 2-point attempt
      (basketball has no other FG value), so it defaults to 2 rather than
      NULL — this keeps ``fga2`` from dropping 2pt misses and forcing
      ``fg2_pct`` to 100%.
    * nba_api: always NULL (numeric subtype codes carry no value).
    """
    return (
        f"CASE "
        f"WHEN {source_col} = '{SOURCE_BBREF}' THEN ("
        f"CASE WHEN {subtype_col} ~* '^3-pt' THEN 3 "
        f"WHEN {subtype_col} ~* '^2-pt' THEN 2 ELSE NULL END) "
        f"WHEN {source_col} = '{SOURCE_BR_CRAWLER}' THEN ("
        f"CASE WHEN {shot_delta_col} IN (2, 3) THEN {shot_delta_col} "
        f"WHEN {is_fg_col} AND {desc_col} ~* '3-pt|three' THEN 3 "
        f"WHEN {is_fg_col} THEN 2 "
        f"ELSE NULL END) "
        f"ELSE NULL END"
    )


def shot_type_sql(
    event_type_col: str = "event_type",
    subtype_col: str = "subtype",
) -> str:
    """Shot-family classification (Jump Shot / Layup / Dunk / Hook / Tip / Free Throw / Other)."""
    return (
        f"CASE "
        f"WHEN {event_type_col} ILIKE '%%free throw%%' OR {subtype_col} ILIKE '%%free throw%%' THEN 'Free Throw' "
        f"WHEN {subtype_col} ILIKE '%%jump shot%%' OR {subtype_col} ILIKE '%%jump%%' THEN 'Jump Shot' "
        f"WHEN {subtype_col} ILIKE '%%layup%%' THEN 'Layup' "
        f"WHEN {subtype_col} ILIKE '%%dunk%%' THEN 'Dunk' "
        f"WHEN {subtype_col} ILIKE '%%hook%%' THEN 'Hook' "
        f"WHEN {subtype_col} ILIKE '%%tip%%' THEN 'Tip' "
        f"ELSE 'Other' END"
    )


def finish_type_sql(
    source_col: str = "source",
    subtype_col: str = "subtype",
) -> str:
    """Catch vs dribble finish — ONLY distinguishable for br_crawler (NULL otherwise).

    Dribble = pullup / step back / running / driving / turnaround.
    Catch    = plain jump / layup / dunk / hook / tip.
    """
    return (
        f"CASE WHEN {source_col} = '{SOURCE_BR_CRAWLER}' THEN ("
        f"CASE "
        f"WHEN {subtype_col} ILIKE '%%pullup%%' OR {subtype_col} ILIKE '%%step back%%' "
        f"OR {subtype_col} ILIKE '%%running%%' OR {subtype_col} ILIKE '%%driving%%' "
        f"OR {subtype_col} ILIKE '%%turnaround%%' THEN 'dribble' "
        f"WHEN {subtype_col} ILIKE '%%jump%%' OR {subtype_col} ILIKE '%%layup%%' "
        f"OR {subtype_col} ILIKE '%%dunk%%' OR {subtype_col} ILIKE '%%hook%%' "
        f"OR {subtype_col} ILIKE '%%tip%%' THEN 'catch' "
        f"ELSE NULL END) "
        f"ELSE NULL END"
    )


def round_rate(
    num: float | int | None,
    denom: float | int | None,
    digits: int = 2,
) -> float | None:
    """Percentage in 0-100 with graceful ``None`` when denom is missing/zero."""
    if num is None or denom is None or denom == 0:
        return None
    try:
        return round((float(num) / float(denom)) * 100.0, digits)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
