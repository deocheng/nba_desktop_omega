"""NBACore v8.2-C — Career engine service (orchestration + post-processing).

Executes the read-only SQL built by ``career_queries`` via the single data-layer
primitive (``db.batch_query``), then derives peak rows, age curves, and similarity
rankings. No pandas / no SQL strings / no per-row loops that belong in SQL.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.core import db
from backend.services.career_engine import (
    career_constants as C,
    career_queries,
    career_utils as u,
)


# ── Internal curve builder ─────────────────────────────────────────────────
def _rows_to_curves(rows: list[dict]) -> dict[str, dict]:
    """Group raw rows by player_id into a curve structure with age fallback.

    Returns: { player_id: {
        'player_name': str,
        'points': [ {age, value, season, team}, ... ] sorted by age,
        'last_team': str|None, 'last_season': int|None } }
    Age is taken from ``age``; when NULL, ``age_in_season(birth_date, season)``
    is used as the fallback.
    """
    groups: dict[str, dict] = {}
    for r in rows:
        pid = r.get("player_id")
        if pid is None:
            continue
        g = groups.setdefault(
            pid,
            {"player_name": r.get("player_name"), "points": [], "last_team": None, "last_season": None},
        )
        age = r.get("age")
        if age is None:
            age = u.age_in_season(r.get("birth_date"), r.get("season"))
        val = r.get("metric_value")
        if age is None or val is None:
            continue
        g["points"].append(
            {
                "age": float(age),
                "value": float(val),
                "season": r.get("season"),
                "team": r.get("team"),
            }
        )
        season = r.get("season")
        if season is not None and (g["last_season"] is None or season > g["last_season"]):
            g["last_season"] = int(season)
            g["last_team"] = r.get("team")
    for g in groups.values():
        g["points"].sort(key=lambda p: p["age"])
    return groups


def _peak_age_of(points: list[dict]) -> float | None:
    if not points:
        return None
    best = max(points, key=lambda p: p["value"])
    return best["age"]


# ── Peak ─────────────────────────────────────────────────────────────────
def get_peak_players(
    metric: str,
    min_games: int = C.DEFAULT_MIN_GAMES,
    position: str | None = None,
    era: str | None = None,
    limit: int = C.DEFAULT_LIMIT,
) -> list[dict]:
    """Top players by career-best single-season ``metric`` value."""
    sql, params = career_queries.build_peak_sql(
        metric=metric, min_games=min_games, position=position, era=era, limit=limit
    )
    rows = db.batch_query(sql, params)
    out: list[dict] = []
    for i, r in enumerate(rows, 1):
        if r.get("peak_value") is None:
            continue
        peak_age = r.get("peak_age")
        if peak_age is None:
            peak_age = u.age_in_season(r.get("birth_date"), r.get("peak_season"))
        out.append(
            {
                "rank": i,
                "player_id": r.get("player_id"),
                "player_name": r.get("player_name"),
                "peak_value": u.r3(r.get("peak_value")),
                "peak_season": r.get("peak_season"),
                "peak_age": peak_age,
                "peak_team": r.get("peak_team"),
                "second_value": u.r3(r.get("second_value")),
                "seasons_played": r.get("seasons_played") or 0,
            }
        )
    return out


# ── Age Curve ───────────────────────────────────────────────────────────────
def get_age_curves(
    player_ids: list[str],
    metric: str,
    min_games: int = C.DEFAULT_AGE_CURVE_MIN_GAMES,
) -> list[dict]:
    """Per-player (age, value) career curve, sorted by age."""
    sql, params = career_queries.build_age_curve_sql(
        player_ids=player_ids, metric=metric, min_games=min_games
    )
    rows = db.batch_query(sql, params)
    groups = _rows_to_curves(rows)
    out: list[dict] = []
    for pid in player_ids:
        g = groups.get(pid)
        if not g or not g["points"]:
            out.append(
                {
                    "player_id": pid,
                    "player_name": None,
                    "team_last": None,
                    "peak_age": None,
                    "curve": [],
                }
            )
            continue
        out.append(
            {
                "player_id": pid,
                "player_name": g["player_name"],
                "team_last": g["last_team"],
                "peak_age": _peak_age_of(g["points"]),
                "curve": [
                    {
                        "season": p["season"],
                        "age": p["age"],
                        "value": u.r3(p["value"]),
                        "team": p["team"],
                    }
                    for p in g["points"]
                ],
            }
        )
    return out


def get_age_curves_multi(
    player_ids: list[str],
    metrics: list[str],
    min_games: int = C.DEFAULT_AGE_CURVE_MIN_GAMES,
) -> list[dict]:
    """Per-player career curves for MULTIPLE metrics (no new SQL).

    Reuses the existing single-metric ``get_age_curves`` path for every metric,
    so no SQL strings are added (v8 §6). Returns each player with:

        curves:    { metric: [AgeCurvePoint-ish...] }
        peak_ages: { metric: peak_age | None }
        curve/peak_age: back-compat copies of ``metrics[0]`` (kept for old clients)

    The player's ``player_name`` / ``team_last`` are taken from the first metric
    that actually produced data (so they never require an extra query).
    """
    out: list[dict] = []
    for pid in player_ids:
        curves: dict[str, list[dict]] = {}
        peak_ages: dict[str, float | None] = {}
        name: str | None = None
        team_last: str | None = None
        for m in metrics:
            single = get_age_curves(player_ids=[pid], metric=m, min_games=min_games)
            if not single:
                continue
            row = single[0]
            if name is None and row.get("player_name") is not None:
                name = row.get("player_name")
            if team_last is None and row.get("team_last") is not None:
                team_last = row.get("team_last")
            if row.get("curve"):
                curves[m] = row["curve"]
                peak_ages[m] = row.get("peak_age")
        first_metric = metrics[0] if metrics else None
        out.append(
            {
                "player_id": pid,
                "player_name": name,
                "team_last": team_last,
                "curves": curves,
                "peak_ages": peak_ages,
                # back-compat: curve/peak_age mirror the first requested metric
                "curve": curves[first_metric] if first_metric and first_metric in curves else [],
                "peak_age": peak_ages.get(first_metric) if first_metric else None,
            }
        )
    return out


# ── Similar Evolution ─────────────────────────────────────────────────────
def get_similar_evolution(
    player_id: str,
    metric: str,
    top_k: int = C.DEFAULT_TOP_K,
    min_games: int = C.DEFAULT_MIN_GAMES,
    same_position: bool = True,
    algorithm: str = C.DEFAULT_ALGORITHM,
    min_seasons: int = C.DEFAULT_MIN_SEASONS,
) -> dict:
    """Find ``top_k`` players whose age->metric trajectory is most similar."""
    # 1. target curve (full, min_games=1 to capture entire career)
    t_sql, t_params = career_queries.build_age_curve_sql(
        player_ids=[player_id], metric=metric, min_games=1
    )
    t_rows = db.batch_query(t_sql, t_params)
    t_groups = _rows_to_curves(t_rows)
    t_g = t_groups.get(player_id)
    if not t_g or not t_g["points"]:
        return {
            "target": {
                "player_id": player_id,
                "player_name": None,
                "curve": [],
                "peak_age": None,
            },
            "similar": [],
        }

    t_points = t_g["points"]
    t_vec = u.resample_curve_to_grid(t_points, C.AGE_GRID, age_key="age", value_key="value")

    # 2. candidate pool
    t_pos = _target_pos_from_rows(t_rows)
    c_sql, c_params = career_queries.build_similar_candidates_sql(
        metric=metric,
        min_games=min_games,
        target_pos=t_pos if same_position else None,
        same_position=same_position,
        min_seasons=min_seasons,
    )
    c_rows = db.batch_query(c_sql, c_params)
    c_groups = _rows_to_curves(c_rows)

    scored = []
    for cid, g in c_groups.items():
        if cid == player_id:
            continue
        if len(g["points"]) < min_seasons:
            continue
        c_vec = u.resample_curve_to_grid(g["points"], C.AGE_GRID, age_key="age", value_key="value")
        score = u.similarity_score(t_vec, c_vec, algorithm)
        scored.append(
            {
                "player_id": cid,
                "player_name": g["player_name"],
                "similarity": round(score, 4),
                "peak_age": _peak_age_of(g["points"]),
                "curve": [{"age": p["age"], "value": u.r3(p["value"])} for p in g["points"]],
            }
        )

    scored.sort(key=lambda d: d["similarity"], reverse=True)
    similar = scored[: max(0, top_k)]

    return {
        "target": {
            "player_id": player_id,
            "player_name": t_g["player_name"],
            "curve": [{"age": p["age"], "value": u.r3(p["value"])} for p in t_points],
            "peak_age": _peak_age_of(t_points),
        },
        "similar": similar,
    }


def _target_pos_from_rows(rows: list[dict]) -> str | None:
    """Best-effort position of the target (used for same-position filtering)."""
    for r in rows:
        pos = r.get("pos")
        if pos:
            return pos
    return None
