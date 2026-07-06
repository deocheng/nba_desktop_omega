"""NBACore v8 §2 Layer 1 — Charts Loader.

Complex chart computations that require Python-side processing
of database data (e.g. late-clock shot analysis from play-by-play).

All functions follow v8 §2 rules:
    - season parameter is REQUIRED (no default)
    - Only SELECT statements for DB access
    - All SQL passes through backend.core.db.batch_query
    - Returns list[dict]
"""
from __future__ import annotations

from collections import defaultdict

from backend.core.db import batch_query


def get_late_clock_team_stats(season: int) -> list[dict]:
    """Team-level late shot clock stats (last 4 seconds) from play-by-play.

    Uses possession tracking: a new possession starts after defensive rebounds,
    turnovers, or made baskets. Shot clock = 24s, so if time elapsed in
    possession >= 20s, the shot was in the last 4 seconds.

    Args:
        season: NBA season (required, no default).

    Returns:
        list[dict]: Each dict has team, total_shots, late_shots, late_pct,
            early_shots, early_pct, late_fg_pct, early_fg_pct, overall_fg_pct,
            late_pts, total_pts, late_pts_pct.
            Sorted by total_shots descending.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")

    sql = """
        SELECT gameid, eventnum, period, clock_seconds, team,
               event_type, subtype, result
        FROM play_by_play
        WHERE season = %s
          AND event_type IN ('Made Shot', 'Missed Shot', 'Rebound', 'Turnover')
        ORDER BY gameid, eventnum
    """
    rows = batch_query(sql, (season,))

    game_poss_start: dict = {}
    team_stats: dict = defaultdict(lambda: {
        "total_shots": 0,
        "late_shots": 0,
        "late_made": 0,
        "early_shots": 0,
        "early_made": 0,
        "total_made": 0,
        "total_pts": 0,
        "late_pts": 0,
    })

    for row in rows:
        gameid = row["gameid"]
        clock_sec = row["clock_seconds"]
        team = row["team"]
        etype = row["event_type"]
        subtype = row["subtype"]
        result = row["result"]

        if etype in ("Rebound", "Turnover"):
            game_poss_start[gameid] = clock_sec
            continue

        if etype in ("Made Shot", "Missed Shot"):
            poss_start = game_poss_start.get(gameid)
            if poss_start is None:
                game_poss_start[gameid] = clock_sec
                poss_start = clock_sec

            elapsed = poss_start - clock_sec if poss_start and clock_sec else 0

            is_three = subtype and "3" in str(subtype)
            pts = 3 if is_three else 2
            made = (etype == "Made Shot")

            if team:
                ts = team_stats[team]
                ts["total_shots"] += 1
                if made:
                    ts["total_made"] += 1
                    ts["total_pts"] += pts

                if elapsed >= 20:
                    ts["late_shots"] += 1
                    if made:
                        ts["late_made"] += 1
                        ts["late_pts"] += pts
                else:
                    ts["early_shots"] += 1
                    if made:
                        ts["early_made"] += 1

            if made:
                game_poss_start[gameid] = clock_sec

    result_list = []
    for team, s in sorted(
        team_stats.items(), key=lambda x: x[1]["total_shots"], reverse=True
    ):
        total = s["total_shots"]
        if total == 0:
            continue
        late = s["late_shots"]
        result_list.append({
            "team": team,
            "total_shots": total,
            "late_shots": late,
            "late_pct": round(late / total * 100, 1) if total else 0,
            "early_shots": s["early_shots"],
            "early_pct": round(s["early_shots"] / total * 100, 1) if total else 0,
            "late_fg_pct": round(s["late_made"] / late * 100, 1) if late else 0,
            "early_fg_pct": (
                round(s["early_made"] / s["early_shots"] * 100, 1)
                if s["early_shots"] else 0
            ),
            "overall_fg_pct": round(s["total_made"] / total * 100, 1) if total else 0,
            "late_pts": s["late_pts"],
            "total_pts": s["total_pts"],
            "late_pts_pct": (
                round(s["late_pts"] / s["total_pts"] * 100, 1)
                if s["total_pts"] else 0
            ),
        })

    return result_list


def get_late_clock_player_stats(season: int, min_shots: int) -> list[dict]:
    """Player-level late shot clock stats (last 4 seconds) from play-by-play.

    Tracks possession per game and attributes late-clock shots to players.

    Args:
        season: NBA season (required, no default).
        min_shots: Minimum total shots to qualify for the ranking.

    Returns:
        list[dict]: Each dict has player, team, total_shots, late_shots,
            late_pct, early_shots, early_pct, late_fg_pct, early_fg_pct,
            overall_fg_pct, late_pts, total_pts, late_pts_pct.
            Sorted by late_pct descending.
    """
    if not isinstance(season, int) or season < 1900 or season > 2100:
        raise ValueError(f"Invalid season {season!r}")
    if not isinstance(min_shots, int) or min_shots < 0:
        raise ValueError(f"Invalid min_shots {min_shots!r}")

    sql = """
        SELECT gameid, eventnum, period, clock_seconds, team, player,
               event_type, subtype, result
        FROM play_by_play
        WHERE season = %s
          AND event_type IN ('Made Shot', 'Missed Shot', 'Rebound', 'Turnover')
        ORDER BY gameid, eventnum
    """
    rows = batch_query(sql, (season,))

    game_poss_start: dict = {}
    player_stats: dict = defaultdict(lambda: {
        "total_shots": 0,
        "late_shots": 0,
        "late_made": 0,
        "early_shots": 0,
        "early_made": 0,
        "total_made": 0,
        "total_pts": 0,
        "late_pts": 0,
        "team": "",
    })

    for row in rows:
        gameid = row["gameid"]
        clock_sec = row["clock_seconds"]
        team = row["team"]
        player = row["player"]
        etype = row["event_type"]
        subtype = row["subtype"]

        if etype in ("Rebound", "Turnover"):
            game_poss_start[gameid] = clock_sec
            continue

        if etype in ("Made Shot", "Missed Shot"):
            poss_start = game_poss_start.get(gameid, clock_sec)
            elapsed = poss_start - clock_sec if poss_start and clock_sec else 0

            is_three = subtype and "3" in str(subtype)
            pts = 3 if is_three else 2
            made = (etype == "Made Shot")

            if player and player.strip():
                ps = player_stats[player]
                ps["total_shots"] += 1
                if team:
                    ps["team"] = team
                if made:
                    ps["total_made"] += 1
                    ps["total_pts"] += pts

                if elapsed >= 20:
                    ps["late_shots"] += 1
                    if made:
                        ps["late_made"] += 1
                        ps["late_pts"] += pts
                else:
                    ps["early_shots"] += 1
                    if made:
                        ps["early_made"] += 1

            if made:
                game_poss_start[gameid] = clock_sec

    result_list = []
    for player, s in player_stats.items():
        total = s["total_shots"]
        if total < min_shots:
            continue
        late = s["late_shots"]
        result_list.append({
            "player": player,
            "team": s["team"],
            "total_shots": total,
            "late_shots": late,
            "late_pct": round(late / total * 100, 1) if total else 0,
            "early_shots": s["early_shots"],
            "early_pct": round(s["early_shots"] / total * 100, 1) if total else 0,
            "late_fg_pct": round(s["late_made"] / late * 100, 1) if late else 0,
            "early_fg_pct": (
                round(s["early_made"] / s["early_shots"] * 100, 1)
                if s["early_shots"] else 0
            ),
            "overall_fg_pct": round(s["total_made"] / total * 100, 1) if total else 0,
            "late_pts": s["late_pts"],
            "total_pts": s["total_pts"],
            "late_pts_pct": (
                round(s["late_pts"] / s["total_pts"] * 100, 1)
                if s["total_pts"] else 0
            ),
        })

    result_list.sort(key=lambda x: x["late_pct"], reverse=True)
    return result_list
