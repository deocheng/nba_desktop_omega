"""Smoke test for the clutch engine (read-only)."""
from __future__ import annotations

from backend.services.clutch_engine import clutch_queries as q
from backend.services.clutch_engine import clutch_service as svc


def show_sql():
    sql, params = q.build_clutch_players_sql(season=None, min_poss=10)
    print("=== SQL (first 1400 chars) ===")
    print(sql.strip()[:1400])
    print("\n=== param count ===", len(params), "params =", params)
    # basic sanity: number of bare %s must equal len(params)
    import re
    n_s = len(re.findall(r"(?<!%)%s", sql))  # %s not preceded by %
    n_pct = sql.count("%%")
    print(f"bare %s (approx) = {n_s}, '%%' literals = {n_pct}")
    print("=== seasons SQL ===")
    print(q.build_seasons_sql())


def run():
    print("\n=== SEASONS ===")
    seasons = svc.get_seasons()
    print("seasons:", seasons[:12], "total", len(seasons))

    print("\n=== PLAYERS (all seasons, metric=possessions, min_poss=10, limit=30) ===")
    rows = svc.get_clutch_players(season=None, metric="possessions", min_poss=10, limit=30)
    print("returned rows:", len(rows))
    for r in rows[:3]:
        print(r)

    print("\n=== PLAYERS (metric=points) top3 ===")
    rows2 = svc.get_clutch_players(season=None, metric="points", min_poss=10, limit=30)
    for r in rows2[:3]:
        print({k: r[k] for k in ("player_name","team","poss","pts","fg_pct","dribble_coverage","catch_shots","dribble_shots")})

    print("\n=== PLAYERS (season=2026) top3 ===")
    rows3 = svc.get_clutch_players(season=2026, metric="possessions", min_poss=10, limit=30)
    print("returned rows:", len(rows3))
    for r in rows3[:3]:
        print({k: r[k] for k in ("player_name","team","poss","fg_pct","fg2_pct","fg3_pct","catch_shots","dribble_shots","dribble_coverage")})

    print("\n=== N/A coverage check (rows with dribble_coverage None) ===")
    na = [r for r in rows if r["dribble_coverage"] is None]
    print(f"of {len(rows)} rows, {len(na)} have dribble_coverage=None (N/A)")


if __name__ == "__main__":
    show_sql()
    run()
    print("\nSMOKE OK")
