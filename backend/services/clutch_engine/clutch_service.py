"""NBACore v8 — Clutch engine service (orchestration + post-processing).

Executes the read-only SQL built by ``clutch_queries`` via the single data-layer
access primitive (``db.batch_query``), then derives rates, the dribble
identifiability flag, and rounds everything. No pandas / no per-row loops.
"""
from __future__ import annotations

from backend.core import db
from backend.services.clutch_engine import clutch_queries, clutch_utils as u


def _post_process(row: dict) -> dict:
    """Compute rates / coverage / null-handling from raw aggregate counts."""
    fga = row.get("fga") or 0
    fgm = row.get("fgm") or 0
    fga2 = row.get("fga2") or 0
    fgm2 = row.get("fgm2") or 0
    fga3 = row.get("fga3") or 0
    fgm3 = row.get("fgm3") or 0
    fta = row.get("fta") or 0
    ftm = row.get("ftm") or 0
    catch = row.get("catch_shots") or 0
    dribble = row.get("dribble_shots") or 0
    identified = catch + dribble

    fg_pct = u.round_rate(fgm, fga)
    fg2_pct = u.round_rate(fgm2, fga2)
    fg3_pct = u.round_rate(fgm3, fga3)
    ft_pct = u.round_rate(ftm, fta)
    dribble_coverage = u.round_rate(identified, fga)

    # When no dribble-identifiable attempts exist (e.g. the player's clutch shots
    # are all sourced from BBRef / nba_api), the catch/dribble dimension is
    # indistinguishable -> return NULL so the frontend can render "—".
    identifiable = identified > 0
    if not identifiable:
        catch_out = None
        dribble_out = None
        dribble_coverage_out = None
    else:
        catch_out = catch
        dribble_out = dribble
        dribble_coverage_out = dribble_coverage

    return {
        "player_id": row.get("player_id"),
        "player_name": row.get("player_name"),
        "team": row.get("team"),
        "poss": row.get("poss"),
        "fgm": fgm, "fga": fga, "fg_pct": fg_pct,
        "fgm2": fgm2, "fga2": fga2, "fg2_pct": fg2_pct,
        "fgm3": fgm3, "fga3": fga3, "fg3_pct": fg3_pct,
        "ftm": ftm, "fta": fta, "ft_pct": ft_pct,
        "catch_shots": catch_out,
        "dribble_shots": dribble_out,
        "dribble_coverage": dribble_coverage_out,
        "oreb": row.get("oreb") or 0,
        "dreb": row.get("dreb") or 0,
        "ast": row.get("ast") or 0,
        "stl": row.get("stl") or 0,
        "tov": row.get("tov") or 0,
        "pf": row.get("pf") or 0,
        "pts": row.get("pts") or 0,
        "net_eff": None,
    }


def get_clutch_players(
    period: int = 4,
    clock_max: int = 300,
    margin_max: int = 5,
    season: int | None = None,
    metric: str = "possessions",
    min_poss: int = 10,
    limit: int = 30,
) -> list[dict]:
    """Aggregate clutch player stats, sort by ``metric``, slice to ``limit``."""
    sql, params = clutch_queries.build_clutch_players_sql(
        period=period,
        clock_max=clock_max,
        margin_max=margin_max,
        season=season,
        min_poss=min_poss,
    )
    rows = db.batch_query(sql, params)
    processed = [_post_process(r) for r in rows]
    sort_key = "pts" if metric == "points" else "poss"
    processed.sort(key=lambda d: (d.get(sort_key) or 0), reverse=True)
    return processed[: max(0, limit)]


def fetch_clutch_events(
    gameid: str,
    season,
    period: int = 4,
    clock_max: int = 300,
    margin_max: int = 5,
) -> list[dict]:
    """Event-level clutch rows for ONE game (br_crawler only).

    Delegates SQL to ``clutch_queries.build_clutch_events_sql`` and normalises
    each row into a flat dict the fusion mapper can consume:
    ``{eventnum, period, clock_seconds, playerid, player, team, margin}``.
    """
    sql, params = clutch_queries.build_clutch_events_sql(
        gameid, season, period, clock_max, margin_max
    )
    rows = db.batch_query(sql, params)
    return [
        {
            "eventnum": int(r["eventnum"]),
            "period": int(r["period"]),
            "clock_seconds": float(r["clock_seconds"]),
            "playerid": r["playerid"],
            "player": r["player"] or "",
            "team": r["team"],
            "margin": int(r["margin"]),
        }
        for r in rows
    ]


def get_clutch_players_for_game(
    gameid: str,
    season,
    period: int = 4,
    clock_max: int = 300,
    margin_max: int = 5,
    min_poss: int = 0,
) -> list[dict]:
    """Per-player clutch stats for ONE game (sidebar source for the fusion page).

    Reuses :func:`build_clutch_players_sql` with a ``gameid`` filter (so no
    cross-game ``LIMIT`` is needed) and the existing :func:`_post_process`
    post-processor. Players are grouped by *name* (not ``playerid``) to avoid the
    BBRef ``playerid = NULL`` grouping bug (architecture §8.4). The default
    ``min_poss = 0`` keeps every clutch participant of a single game visible.
    """
    sql, params = clutch_queries.build_clutch_players_sql(
        period=period,
        clock_max=clock_max,
        margin_max=margin_max,
        season=season,
        gameid=gameid,
        min_poss=min_poss,
    )
    rows = db.batch_query(sql, params)
    processed = [_post_process(r) for r in rows]
    processed.sort(key=lambda d: (d.get("poss") or 0), reverse=True)
    return processed


def get_seasons() -> list[int]:
    """Distinct seasons available for the clutch filter."""
    sql = clutch_queries.build_seasons_sql()
    rows = db.batch_query(sql)
    return [int(r["season"]) for r in rows if r.get("season") is not None]
