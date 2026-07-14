#!/usr/bin/env python3
"""
2026 季后赛 + Play-In 数据入库（完整统计版）
================================================
使用 cdn.nba.com boxscore API 获取球员统计，
补全 games / game_metadata / player_game_details / starting_lineups 表。

数据源: https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json

用法:
    python crawler/ingest_2026_playoffs.py
    python crawler/ingest_2026_playoffs.py --dry-run
    python crawler/ingest_2026_playoffs.py --limit 20
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import random
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import execute_batch
from curl_cffi import requests as cffi_requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("PlayoffIngest")

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}

CDN_BOXSCORE = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.nba.com/",
}

_last_req = 0.0
RATE_LIMIT = 1.5   # seconds between requests


def _wait():
    global _last_req
    elapsed = time.time() - _last_req
    if elapsed < RATE_LIMIT:
        time.sleep(RATE_LIMIT - elapsed + random.uniform(0, 0.3))
    _last_req = time.time()


def fetch_boxscore(game_id_10: str) -> Optional[dict]:
    """Fetch CDN boxscore JSON for a game."""
    url = CDN_BOXSCORE.format(game_id=game_id_10)
    for attempt in range(3):
        try:
            _wait()
            resp = cffi_requests.get(url, headers=HEADERS, impersonate="chrome124", timeout=20)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                logger.warning(f"  404 Not found: {game_id_10}")
                return None
            elif resp.status_code == 403:
                delay = 3 * (2 ** attempt) + random.uniform(0, 2)
                logger.warning(f"  403 blocked for {game_id_10}, retry in {delay:.1f}s")
                time.sleep(delay)
            else:
                logger.warning(f"  HTTP {resp.status_code} for {game_id_10}")
                if attempt < 2:
                    time.sleep(2 ** attempt * 2)
        except Exception as e:
            logger.warning(f"  Exception for {game_id_10}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    return None


def _safe_int(v) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _mins_to_str(minutes_str: str) -> Optional[str]:
    """Convert PT12M34.00S or '12:34' to 'MM:SS'."""
    if not minutes_str:
        return None
    if minutes_str.startswith("PT"):
        # PT12M34.00S
        minutes_str = minutes_str[2:]  # 12M34.00S
        m, s = 0, 0
        if "M" in minutes_str:
            parts = minutes_str.split("M")
            m = int(parts[0])
            s = float(parts[1].replace("S", ""))
        else:
            s = float(minutes_str.replace("S", ""))
        return f"{m:02d}:{int(s):02d}"
    return minutes_str


def parse_game(data: dict, game_id_8: str) -> Optional[dict]:
    """Parse CDN boxscore into DB-ready dicts."""
    game = data.get("game", {})
    if game.get("gameStatus") != 3:
        return None  # Not final

    gid_10 = game_id_8.zfill(10)
    game_date = game.get("gameEt", "")[:10]  # "2026-04-18"
    season_end = 2026

    home = game.get("homeTeam", {})
    away = game.get("awayTeam", {})

    arena = game.get("arena", {})
    officials_list = game.get("officials", [])
    officials = json.dumps([{
        "name": o.get("name"),
        "jersey": o.get("jerseyNum"),
    } for o in officials_list])

    # game_metadata
    period_scores = game.get("homeTeam", {}).get("periods", [])
    home_quarters = {f"home_q{i+1}": p.get("score") for i, p in enumerate(period_scores[:4])}
    away_periods = away.get("periods", [])
    away_quarters = {f"away_q{i+1}": p.get("score") for i, p in enumerate(away_periods[:4])}

    meta = {
        "game_id": gid_10,
        "arena_name": arena.get("arenaName"),
        "arena_city": arena.get("arenaCity"),
        "arena_state": arena.get("arenaState"),
        "attendance": _safe_int(game.get("attendance")),
        "officials": officials,
        "duration": game.get("duration"),
        "away_q1": away_quarters.get("away_q1"),
        "away_q2": away_quarters.get("away_q2"),
        "away_q3": away_quarters.get("away_q3"),
        "away_q4": away_quarters.get("away_q4"),
        "home_q1": home_quarters.get("home_q1"),
        "home_q2": home_quarters.get("home_q2"),
        "home_q3": home_quarters.get("home_q3"),
        "home_q4": home_quarters.get("home_q4"),
        "api_season": "2025",
        "api_status": 3,
    }

    # players
    players = []
    for team, is_home in [(home, True), (away, False)]:
        team_id = str(team.get("teamId", ""))
        team_abbr = team.get("teamTricode", "")
        for p in team.get("players", []):
            s = p.get("statistics", {})
            mins_str = s.get("minutes", "")
            players.append({
                "game_id": gid_10,
                "team_id": team_id,
                "team_abbreviation": team_abbr,
                "player_id": str(p.get("personId", "")),
                "player_name": p.get("name", ""),
                "start_position": p.get("position", ""),
                "minutes": _mins_to_str(mins_str),
                "jersey_num": p.get("jerseyNum"),
                "position": p.get("position"),
                "seconds_played": None,
                "pts": _safe_int(s.get("points")),
                "fgm": _safe_int(s.get("fieldGoalsMade")),
                "fga": _safe_int(s.get("fieldGoalsAttempted")),
                "tpm": _safe_int(s.get("threePointersMade")),
                "tpa": _safe_int(s.get("threePointersAttempted")),
                "ftm": _safe_int(s.get("freeThrowsMade")),
                "fta": _safe_int(s.get("freeThrowsAttempted")),
                "oreb": _safe_int(s.get("reboundsOffensive")),
                "dreb": _safe_int(s.get("reboundsDefensive")),
                "reb": _safe_int(s.get("reboundsTotal")),
                "ast": _safe_int(s.get("assists")),
                "stl": _safe_int(s.get("steals")),
                "blk": _safe_int(s.get("blocks")),
                "tov": _safe_int(s.get("turnovers")),
                "pf": _safe_int(s.get("foulsPersonal")),
                "plus_minus": _safe_int(s.get("plusMinusPoints")),
                "fbpts": None,
                "fbptsa": None,
                "fbptsm": None,
                "pip": None,
                "pipa": None,
                "pipm": None,
                "blka": _safe_int(s.get("blocksReceived")),
                "tech_fouls": _safe_int(s.get("foulsTechnical")),
                "court_status": 1 if p.get("played") == "1" else 0,
                "player_status": "A" if p.get("status") == "ACTIVE" else (p.get("status", "") or "")[:5],
                "nba_player_id": _safe_int(p.get("personId")),
            })

    # starting lineups
    lineups = []
    for team, is_home in [(home, True), (away, False)]:
        starters = [p for p in team.get("players", []) if p.get("starter") == "1"]
        if len(starters) >= 5:
            lineup = {
                "season": season_end,
                "team_abbr": team.get("teamTricode", ""),
                "game_date": game_date,
                "lineup_type": "home" if is_home else "away",
                "player1": starters[0].get("name", "") if len(starters) > 0 else None,
                "player2": starters[1].get("name", "") if len(starters) > 1 else None,
                "player3": starters[2].get("name", "") if len(starters) > 2 else None,
                "player4": starters[3].get("name", "") if len(starters) > 3 else None,
                "player5": starters[4].get("name", "") if len(starters) > 4 else None,
                "minutes": None,
                "source": "nba_cdn_api",
            }
            lineups.append(lineup)

    return {
        "meta": meta,
        "players": players,
        "lineups": lineups,
        "home_score": home.get("score"),
        "away_score": away.get("score"),
    }


def upsert_to_db(conn, parsed: dict, game_id_8: str):
    """Write parsed game to DB."""
    cur = conn.cursor()
    gid_10 = game_id_8.zfill(10)

    # 1. game_metadata (unique on game_id)
    m = parsed["meta"]
    # Check if already exists
    cur.execute("SELECT id FROM game_metadata WHERE game_id = %s", (m["game_id"],))
    existing = cur.fetchone()
    if existing:
        cur.execute("""
            UPDATE game_metadata SET
                arena_name = %(arena_name)s,
                attendance = %(attendance)s,
                officials = %(officials)s::jsonb,
                duration = %(duration)s,
                away_q1 = %(away_q1)s, away_q2 = %(away_q2)s,
                away_q3 = %(away_q3)s, away_q4 = %(away_q4)s,
                home_q1 = %(home_q1)s, home_q2 = %(home_q2)s,
                home_q3 = %(home_q3)s, home_q4 = %(home_q4)s,
                api_season = %(api_season)s, api_status = %(api_status)s
            WHERE game_id = %(game_id)s
        """, m)
    else:
        cur.execute("""
            INSERT INTO game_metadata (
                game_id, arena_name, arena_city, arena_state, attendance,
                officials, duration,
                away_q1, away_q2, away_q3, away_q4,
                home_q1, home_q2, home_q3, home_q4,
                api_season, api_status
            ) VALUES (
                %(game_id)s, %(arena_name)s, %(arena_city)s, %(arena_state)s, %(attendance)s,
                %(officials)s::jsonb, %(duration)s,
                %(away_q1)s, %(away_q2)s, %(away_q3)s, %(away_q4)s,
                %(home_q1)s, %(home_q2)s, %(home_q3)s, %(home_q4)s,
                %(api_season)s, %(api_status)s
            )
        """, m)

    # 2. player_game_details (no PK, use DELETE + INSERT)
    if parsed["players"]:
        gid_10_str = game_id_8.zfill(10)
        cur.execute("DELETE FROM player_game_details WHERE game_id = %s", (gid_10_str,))
        execute_batch(cur, """
            INSERT INTO player_game_details (
                game_id, team_id, team_abbreviation, player_id, player_name,
                start_position, minutes, jersey_num, position, seconds_played,
                pts, fgm, fga, tpm, tpa, ftm, fta,
                oreb, dreb, reb, ast, stl, blk, tov, pf,
                plus_minus, fbpts, fbptsa, fbptsm, pip, pipa, pipm,
                blka, tech_fouls, court_status, player_status, nba_player_id
            ) VALUES (
                %(game_id)s, %(team_id)s, %(team_abbreviation)s, %(player_id)s, %(player_name)s,
                %(start_position)s, %(minutes)s, %(jersey_num)s, %(position)s, %(seconds_played)s,
                %(pts)s, %(fgm)s, %(fga)s, %(tpm)s, %(tpa)s, %(ftm)s, %(fta)s,
                %(oreb)s, %(dreb)s, %(reb)s, %(ast)s, %(stl)s, %(blk)s, %(tov)s, %(pf)s,
                %(plus_minus)s, %(fbpts)s, %(fbptsa)s, %(fbptsm)s, %(pip)s, %(pipa)s, %(pipm)s,
                %(blka)s, %(tech_fouls)s, %(court_status)s, %(player_status)s, %(nba_player_id)s
            )
        """, parsed["players"], page_size=50)

    # 3. starting lineups
    for lineup in parsed["lineups"]:
        cur.execute("""
            INSERT INTO starting_lineups (
                season, team_abbr, game_date, lineup_type,
                player1, player2, player3, player4, player5,
                minutes, source, created_at
            ) VALUES (
                %(season)s, %(team_abbr)s, %(game_date)s, %(lineup_type)s,
                %(player1)s, %(player2)s, %(player3)s, %(player4)s, %(player5)s,
                %(minutes)s, %(source)s, NOW()
            )
            ON CONFLICT DO NOTHING
        """, lineup)

    # 4. Update games table with score verification
    cur.execute("""
        UPDATE games SET
            home_pts = COALESCE(home_pts, %(home_score)s),
            away_pts = COALESCE(away_pts, %(away_score)s),
            arena_name = %(arena_name)s,
            attendance = %(attendance)s,
            officials = %(officials)s::jsonb
        WHERE game_id = %(game_id_8)s
    """, {
        "home_score": parsed["home_score"],
        "away_score": parsed["away_score"],
        "arena_name": m["arena_name"],
        "attendance": m["attendance"],
        "officials": m["officials"],
        "game_id_8": game_id_8,
    })

    conn.commit()


def get_playoff_games(conn) -> list[tuple[str, str]]:
    """Get all 2026 playoff+playin games from DB that need ingest."""
    cur = conn.cursor()
    cur.execute("""
        SELECT g.game_id 
        FROM games g
        WHERE g.season = 2026 
          AND g.season_type IN ('Playoffs', 'Play-In')
          AND g.home_pts IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM game_metadata gm 
              WHERE gm.game_id = g.game_id::text || ''
          )
        ORDER BY g.game_date, g.game_id
    """)
    return [(r[0], "2025") for r in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser(description="Ingest 2026 NBA playoff/playin player stats")
    parser.add_argument("--dry-run", action="store_true", help="Print only, don't write DB")
    parser.add_argument("--limit", type=int, default=200, help="Max games to process")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)

    # Find games needing ingest
    # For playoffs, game_id is like 42500101 (8-digit)
    # game_metadata uses 10-digit game_id (0042500101)
    cur = conn.cursor()
    cur.execute("""
        SELECT g.game_id
        FROM games g
        WHERE g.season = 2026 
          AND g.season_type IN ('Playoffs', 'Play-In')
          AND g.home_pts IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM game_metadata gm 
              WHERE gm.game_id = LPAD(g.game_id, 10, '0')
          )
        ORDER BY g.game_date, g.game_id
    """)
    games_to_process = [r[0] for r in cur.fetchall()]

    if args.limit:
        games_to_process = games_to_process[:args.limit]

    logger.info(f"Found {len(games_to_process)} playoff games needing ingest")

    if not games_to_process:
        logger.info("All playoff games already ingested!")
        conn.close()
        return

    success = skipped = failed = 0
    start_time = time.time()

    for i, gid_8 in enumerate(games_to_process):
        gid_10 = gid_8.zfill(10)
        try:
            if args.dry_run:
                logger.info(f"  [DRY RUN] Would fetch: {gid_10}")
                success += 1
                continue

            data = fetch_boxscore(gid_10)
            if not data:
                logger.warning(f"  No data for {gid_10}")
                skipped += 1
                continue

            parsed = parse_game(data, gid_8)
            if not parsed:
                logger.warning(f"  Not final: {gid_10}")
                skipped += 1
                continue

            upsert_to_db(conn, parsed, gid_8)
            players_count = len(parsed["players"])
            logger.info(
                f"  [{i+1}/{len(games_to_process)}] {gid_10}: "
                f"{parsed.get('away_score')}-{parsed.get('home_score')} | "
                f"{players_count} players"
            )
            success += 1

        except Exception as e:
            logger.error(f"  Error on {gid_10}: {e}")
            conn.rollback()
            failed += 1

        if (i + 1) % 20 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            eta = (len(games_to_process) - i - 1) / rate if rate > 0 else 0
            logger.info(
                f"  Progress: {i+1}/{len(games_to_process)} | "
                f"OK={success} skip={skipped} fail={failed} | "
                f"{rate:.1f} g/s | ETA={eta/60:.0f}min"
            )

    elapsed = time.time() - start_time
    logger.info(f"\n{'='*60}")
    logger.info(f"DONE: {success} success, {skipped} skipped, {failed} failed")
    logger.info(f"Time: {elapsed:.0f}s")
    logger.info(f"{'='*60}")

    conn.close()


if __name__ == "__main__":
    main()
