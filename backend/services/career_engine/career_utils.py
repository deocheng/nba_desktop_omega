"""NBACore v8.2-C — Career engine pure Python helpers (no DB / no pandas).

Everything here is trivially unit-testable and keeps all SQL in exactly one
place (``career_queries``). Functions:
    - ``round_rate``: percentage with graceful None.
    - ``age_in_season``: fallback age from birth_date when fact age is NULL.
    - ``resample_curve_to_grid``: linear-interp a (age, value) curve onto AGE_GRID.
    - ``similarity_score``: pearson / cosine / euclidean -> [0,1].
    - ``_parse_era`` / ``_pos_group``: small shared helpers for query building.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Sequence

import math


# ── Numeric helpers ──────────────────────────────────────────────────────
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


def r3(x: float | None) -> float | None:
    """Round to 3 decimals, pass through None (display convenience)."""
    if x is None:
        return None
    try:
        return round(float(x), 3)
    except (TypeError, ValueError):
        return None


# ── Age helpers ───────────────────────────────────────────────────────────
def _coerce_date(birth_date: Any) -> date | None:
    if birth_date is None:
        return None
    if isinstance(birth_date, date):
        return birth_date
    if isinstance(birth_date, datetime):
        return birth_date.date()
    if isinstance(birth_date, str):
        s = birth_date.strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(s[: len(fmt) + 2], fmt).date()
            except ValueError:
                continue
        # last resort: take the leading YYYY-MM-DD
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def age_in_season(birth_date: Any, season: int | None) -> float | None:
    """Age of a player during ``season`` (NBA season starting that calendar year).

    Uses Oct 1 of the season's starting year as the reference date (matches the
    convention Basketball-Reference uses when labelling a season's age). Returns
    ``None`` when birth_date or season is missing/unparseable.
    """
    if season is None:
        return None
    bd = _coerce_date(birth_date)
    if bd is None:
        return None
    try:
        season_start = date(int(season), 10, 1)
    except (TypeError, ValueError):
        return None
    age = (
        season_start.year
        - bd.year
        - ((season_start.month, season_start.day) < (bd.month, bd.day))
    )
    return float(age)


# ── Curve resampling ───────────────────────────────────────────────────────
def resample_curve_to_grid(
    points: Sequence[tuple[float, float | None]],
    grid: Sequence[float],
    age_key: str = "age",
    value_key: str = "value",
) -> list[float | None]:
    """Resample a (age, value) curve onto ``grid`` via linear interpolation.

    ``points`` may be a list of tuples OR a list of dicts (using age_key/value_key).
    Out-of-range ages are clamped to the nearest endpoint value (per design).
    Returns a list aligned to ``grid``; each element is a float or None when no
    source point had a usable value (e.g. empty input).
    """
    if points and isinstance(points[0], dict):
        pts = [
            (float(p[age_key]), p[value_key])
            for p in points
            if p.get(age_key) is not None
        ]
    else:
        pts = [
            (float(a), v)
            for (a, v) in points
            if a is not None
            and isinstance(a, (int, float))
        ]

    pts = [(a, v) for (a, v) in pts if v is not None]
    if not pts:
        return [None for _ in grid]

    pts.sort(key=lambda kv: kv[0])
    ages = [a for (a, _) in pts]
    vals = [v for (_, v) in pts]
    lo, hi = ages[0], ages[-1]

    out: list[float | None] = []
    for g in grid:
        if g <= lo:
            out.append(vals[0])
        elif g >= hi:
            out.append(vals[-1])
        else:
            # find bracketing segment
            for i in range(1, len(ages)):
                if ages[i] >= g:
                    a0, a1 = ages[i - 1], ages[i]
                    v0, v1 = vals[i - 1], vals[i]
                    if a1 == a0:
                        out.append(v0)
                    else:
                        frac = (g - a0) / (a1 - a0)
                        out.append(v0 + (v1 - v0) * frac)
                    break
    return out


# ── Similarity ─────────────────────────────────────────────────────────────
def _paired(t: Sequence[float | None], c: Sequence[float | None]) -> list[tuple[float, float]]:
    pairs = [
        (a, b)
        for (a, b) in zip(t, c)
        if a is not None and b is not None and isinstance(a, (int, float)) and isinstance(b, (int, float))
    ]
    return pairs


def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    n = len(pairs)
    if n < 2:
        return None
    mx = sum(a for a, _ in pairs) / n
    my = sum(b for _, b in pairs) / n
    num = sum((a - mx) * (b - my) for a, b in pairs)
    dx = math.sqrt(sum((a - mx) ** 2 for a, _ in pairs))
    dy = math.sqrt(sum((b - my) ** 2 for _, b in pairs))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _cosine(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    dot = sum(a * b for a, b in pairs)
    na = math.sqrt(sum(a * a for a, _ in pairs))
    nb = math.sqrt(sum(b * b for _, b in pairs))
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)


def _euclidean(pairs: list[tuple[float, float]]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in pairs))


def similarity_score(
    t: Sequence[float | None],
    c: Sequence[float | None],
    method: str = "pearson",
) -> float:
    """Similarity of two equal-length vectors aligned on AGE_GRID -> [0,1].

    pearson: r in [-1,1] -> (r+1)/2
    cosine:  cos in [-1,1] -> (cos+1)/2
    euclidean: distance d -> 1/(1+d)  (bounded in (0,1])
    Returns 0.0 when there is no overlapping numeric data.
    """
    pairs = _paired(t, c)
    if not pairs:
        return 0.0

    if method == "pearson":
        r = _pearson(pairs)
        if r is None:
            return 0.0
        return max(0.0, min(1.0, (r + 1) / 2))
    if method == "cosine":
        cos = _cosine(pairs)
        if cos is None:
            return 0.0
        return max(0.0, min(1.0, (cos + 1) / 2))
    if method == "euclidean":
        d = _euclidean(pairs)
        return 1.0 / (1.0 + d)

    raise ValueError(f"unknown similarity method {method!r}")


# ── Query-building shared helpers ──────────────────────────────────────────
def _parse_era(era: str | None) -> tuple[int, int] | None:
    """Decode a decade string like '2010s' -> (2010, 2019). None if unparseable."""
    if not era:
        return None
    import re

    m = re.match(r"^(\d{4})s$", str(era).strip().lower())
    if not m:
        return None
    dec = int(m.group(1))
    return (dec, dec + 9)


def _pos_group(pos: str | None) -> str | None:
    """Collapse a position string to its G/F/C category for same-position filtering.

    Guards (PG/SG/G) -> 'G', centers (C/C-F) -> 'C', everything else (SF/PF/F/
    hybrids) -> 'F'. 'C' takes precedence so C-F / F-C count as centers.
    """
    if not pos:
        return None
    p = str(pos).strip().upper()
    if "C" in p:
        return "C"
    if "G" in p:
        return "G"
    return "F"


def pos_group_sql(col: str = "pos") -> str:
    """SQL CASE fragment mapping a position column to its G/F/C category.

    Mirrors :func:`_pos_group` so the candidate filter matches the Python side.
    """
    return (
        f"CASE "
        f"WHEN {col} ILIKE '%C%' THEN 'C' "
        f"WHEN {col} ILIKE '%G%' THEN 'G' "
        f"ELSE 'F' END"
    )


def _in_placeholders(values: Sequence[Any]) -> str:
    """Comma-separated %s placeholders for an IN / NOT IN list."""
    return ", ".join(["%s"] * len(values))
