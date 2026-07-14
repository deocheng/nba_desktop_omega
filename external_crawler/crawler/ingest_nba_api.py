#!/usr/bin/env python3
"""
NBA data.nba.com → PostgreSQL 入库管道
======================================

从 data.nba.com 移动 API 爬取 gamedetail 数据，入库到 PostgreSQL。

目标表:
  1. game_metadata     — 场馆/观众/裁判/时长/逐节比分
  2. player_game_details — 35 字段球员统计（从 7 字段扩展）
  3. starting_lineups   — 首发 5 人
  4. games              — 球队级统计补充（出手数/快攻/内线/板凳等）

用法:
  python crawler/ingest_nba_api.py --season 2024 --batch 50
  python crawler/ingest_nba_api.py --season 2024 --start 0022400001 --end 0022400100
  python crawler/ingest_nba_api.py --season 2023 --dry-run

Author: Senior Developer
Date: 2026-06-18
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import psycopg2
from psycopg2.extras import execute_batch
from curl_cffi import requests as cffi_requests

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("NBAIngest")

# ── Config ───────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}

API_BASE = "https://data.nba.com/data/10s/v2015/json/mobile_teams/nba"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                  " (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.nba.com/",
}
IMPERSONATE = "chrome124"
RATE_LIMIT_RPS = 2.0
MAX_RETRIES = 3


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                          SCHEMA MIGRATION                                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝

MIGRATION_SQL = """
-- ============================================================
-- 1. game_metadata: 新增场馆/观众/裁判/时长/逐节比分
-- ============================================================
ALTER TABLE game_metadata 
  ADD COLUMN IF NOT EXISTS arena_name VARCHAR(200),
  ADD COLUMN IF NOT EXISTS arena_city VARCHAR(100),
  ADD COLUMN IF NOT EXISTS arena_state VARCHAR(10),
  ADD COLUMN IF NOT EXISTS attendance INTEGER,
  ADD COLUMN IF NOT EXISTS officials JSONB,
  ADD COLUMN IF NOT EXISTS duration VARCHAR(20),
  ADD COLUMN IF NOT EXISTS away_q1 INTEGER, ADD COLUMN IF NOT EXISTS away_q2 INTEGER,
  ADD COLUMN IF NOT EXISTS away_q3 INTEGER, ADD COLUMN IF NOT EXISTS away_q4 INTEGER,
  ADD COLUMN IF NOT EXISTS away_ot INTEGER,
  ADD COLUMN IF NOT EXISTS home_q1 INTEGER, ADD COLUMN IF NOT EXISTS home_q2 INTEGER,
  ADD COLUMN IF NOT EXISTS home_q3 INTEGER, ADD COLUMN IF NOT EXISTS home_q4 INTEGER,
  ADD COLUMN IF NOT EXISTS home_ot INTEGER,
  ADD COLUMN IF NOT EXISTS api_season VARCHAR(10),
  ADD COLUMN IF NOT EXISTS api_status INTEGER;

-- ============================================================
-- 2. player_game_details: 从 7 字段扩展到完整统计
-- ============================================================
ALTER TABLE player_game_details
  ADD COLUMN IF NOT EXISTS jersey_num VARCHAR(5),
  ADD COLUMN IF NOT EXISTS position VARCHAR(5),
  ADD COLUMN IF NOT EXISTS seconds_played INTEGER,
  ADD COLUMN IF NOT EXISTS pts INTEGER,
  ADD COLUMN IF NOT EXISTS fgm INTEGER, ADD COLUMN IF NOT EXISTS fga INTEGER,
  ADD COLUMN IF NOT EXISTS tpm INTEGER, ADD COLUMN IF NOT EXISTS tpa INTEGER,
  ADD COLUMN IF NOT EXISTS ftm INTEGER, ADD COLUMN IF NOT EXISTS fta INTEGER,
  ADD COLUMN IF NOT EXISTS oreb INTEGER, ADD COLUMN IF NOT EXISTS dreb INTEGER,
  ADD COLUMN IF NOT EXISTS reb INTEGER,
  ADD COLUMN IF NOT EXISTS ast INTEGER, ADD COLUMN IF NOT EXISTS stl INTEGER,
  ADD COLUMN IF NOT EXISTS blk INTEGER, ADD COLUMN IF NOT EXISTS tov INTEGER,
  ADD COLUMN IF NOT EXISTS pf INTEGER,
  ADD COLUMN IF NOT EXISTS plus_minus INTEGER,
  ADD COLUMN IF NOT EXISTS fbpts INTEGER, ADD COLUMN IF NOT EXISTS fbptsa INTEGER,
  ADD COLUMN IF NOT EXISTS fbptsm INTEGER,
  ADD COLUMN IF NOT EXISTS pip INTEGER, ADD COLUMN IF NOT EXISTS pipa INTEGER,
  ADD COLUMN IF NOT EXISTS pipm INTEGER,
  ADD COLUMN IF NOT EXISTS blka INTEGER,
  ADD COLUMN IF NOT EXISTS tech_fouls INTEGER,
  ADD COLUMN IF NOT EXISTS court_status INTEGER,
  ADD COLUMN IF NOT EXISTS player_status VARCHAR(5),
  ADD COLUMN IF NOT EXISTS nba_player_id BIGINT;

-- ============================================================
-- 3. games: 新增球队级出手数 + 高阶得分
-- ============================================================
ALTER TABLE games
  ADD COLUMN IF NOT EXISTS home_fgm INTEGER, ADD COLUMN IF NOT EXISTS home_fga INTEGER,
  ADD COLUMN IF NOT EXISTS home_tpm INTEGER, ADD COLUMN IF NOT EXISTS home_tpa INTEGER,
  ADD COLUMN IF NOT EXISTS home_ftm INTEGER, ADD COLUMN IF NOT EXISTS home_fta INTEGER,
  ADD COLUMN IF NOT EXISTS home_q1 INTEGER, ADD COLUMN IF NOT EXISTS home_q2 INTEGER,
  ADD COLUMN IF NOT EXISTS home_q3 INTEGER, ADD COLUMN IF NOT EXISTS home_q4 INTEGER,
  ADD COLUMN IF NOT EXISTS home_ot INTEGER,
  ADD COLUMN IF NOT EXISTS home_bpts INTEGER,
  ADD COLUMN IF NOT EXISTS home_fbpts INTEGER,
  ADD COLUMN IF NOT EXISTS home_pip INTEGER,
  ADD COLUMN IF NOT EXISTS home_scp INTEGER,
  ADD COLUMN IF NOT EXISTS home_potov INTEGER,
  ADD COLUMN IF NOT EXISTS home_tmreb INTEGER,
  ADD COLUMN IF NOT EXISTS home_tmtov INTEGER,
  ADD COLUMN IF NOT EXISTS away_fgm INTEGER, ADD COLUMN IF NOT EXISTS away_fga INTEGER,
  ADD COLUMN IF NOT EXISTS away_tpm INTEGER, ADD COLUMN IF NOT EXISTS away_tpa INTEGER,
  ADD COLUMN IF NOT EXISTS away_ftm INTEGER, ADD COLUMN IF NOT EXISTS away_fta INTEGER,
  ADD COLUMN IF NOT EXISTS away_q1 INTEGER, ADD COLUMN IF NOT EXISTS away_q2 INTEGER,
  ADD COLUMN IF NOT EXISTS away_q3 INTEGER, ADD COLUMN IF NOT EXISTS away_q4 INTEGER,
  ADD COLUMN IF NOT EXISTS away_ot INTEGER,
  ADD COLUMN IF NOT EXISTS away_bpts INTEGER,
  ADD COLUMN IF NOT EXISTS away_fbpts INTEGER,
  ADD COLUMN IF NOT EXISTS away_pip INTEGER,
  ADD COLUMN IF NOT EXISTS away_scp INTEGER,
  ADD COLUMN IF NOT EXISTS away_potov INTEGER,
  ADD COLUMN IF NOT EXISTS away_tmreb INTEGER,
  ADD COLUMN IF NOT EXISTS away_tmtov INTEGER,
  ADD COLUMN IF NOT EXISTS attendance INTEGER,
  ADD COLUMN IF NOT EXISTS arena_name VARCHAR(200),
  ADD COLUMN IF NOT EXISTS officials JSONB;
"""


def run_migration(conn):
    """执行表结构迁移"""
    logger.info("Running schema migration...")
    cur = conn.cursor()
    cur.execute(MIGRATION_SQL)
    conn.commit()
    logger.info("Schema migration complete.")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                          API CLIENT                                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

_last_request = 0.0


def _wait():
    global _last_request
    now = time.time()
    elapsed = now - _last_request
    min_interval = 1.0 / RATE_LIMIT_RPS
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed + random.uniform(0, 0.3))
    _last_request = time.time()


def fetch_gamedetail(gid_10: str, season: str) -> Optional[Dict]:
    """从 data.nba.com 获取单场比赛详情
    
    Args:
        gid_10: 10位比赛ID (如 "0022400061")
        season: 赛季 (如 "2024" = 2024-25赛季)
    
    Returns:
        gamedetail JSON dict or None
    """
    url = f"{API_BASE}/{season}/scores/gamedetail/{gid_10}_gamedetail.json"

    for attempt in range(MAX_RETRIES + 1):
        try:
            _wait()
            resp = cffi_requests.get(
                url, headers=HEADERS, impersonate=IMPERSONATE, timeout=30
            )

            if resp.status_code == 200:
                text = resp.text.strip()
                if text.startswith("{"):
                    return resp.json()
                else:
                    logger.warning(f"Non-JSON response for {gid_10}: {text[:100]}")
                    return None

            elif resp.status_code == 404:
                return None

            elif resp.status_code == 403:
                if attempt < MAX_RETRIES:
                    delay = 2.0 * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"403 for {gid_10}, retry in {delay:.1f}s")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"403 blocked after {MAX_RETRIES} retries: {gid_10}")
                    return None

            else:
                logger.warning(f"HTTP {resp.status_code} for {gid_10}")
                if attempt < MAX_RETRIES:
                    time.sleep(2.0 * (2 ** attempt))
                    continue
                return None

        except Exception as e:
            logger.warning(f"Error fetching {gid_10}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(2.0 * (2 ** attempt))
                continue
            return None

    return None


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                          DATA PARSERS                                     ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def _safe_int(val) -> Optional[int]:
    """Safely convert to int, return None for empty/invalid"""
    if val is None or val == "" or val == "0":
        try:
            return int(val) if val != "" else None
        except (ValueError, TypeError):
            return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def parse_game_metadata(g: Dict, api_season: str) -> Dict:
    """解析比赛元数据"""
    vls = g.get("vls", {})
    hls = g.get("hls", {})
    
    # Officials
    offs_data = g.get("offs", {})
    officials = None
    if offs_data and "off" in offs_data:
        officials = json.dumps(offs_data["off"], ensure_ascii=False)

    # OT score (sum of all OT periods)
    def _ot_sum(team):
        return sum(_safe_int(team.get(f"ot{i}")) or 0 for i in range(1, 11))

    return {
        "game_id": g.get("gid"),
        "arena_name": g.get("an"),
        "arena_city": g.get("ac"),
        "arena_state": g.get("as"),
        "attendance": _safe_int(g.get("at")),
        "officials": officials,
        "duration": g.get("dur") or None,
        "away_q1": _safe_int(vls.get("q1")),
        "away_q2": _safe_int(vls.get("q2")),
        "away_q3": _safe_int(vls.get("q3")),
        "away_q4": _safe_int(vls.get("q4")),
        "away_ot": _ot_sum(vls) or None,
        "home_q1": _safe_int(hls.get("q1")),
        "home_q2": _safe_int(hls.get("q2")),
        "home_q3": _safe_int(hls.get("q3")),
        "home_q4": _safe_int(hls.get("q4")),
        "home_ot": _ot_sum(hls) or None,
        "api_season": api_season,
        "api_status": g.get("st"),
    }


def parse_player_stats(pstsg: List[Dict], game_id: str, team_id: str,
                       team_abbr: str, is_home: bool) -> List[Dict]:
    """解析球员统计"""
    players = []
    for p in pstsg:
        players.append({
            "game_id": game_id,
            "team_id": team_id,
            "team_abbreviation": team_abbr,
            "player_id": str(p.get("pid", "")),
            "player_name": f"{p.get('fn', '')} {p.get('ln', '')}".strip(),
            "start_position": p.get("pos") if p.get("court") == 1 else "",
            "minutes": str(p.get("min", "")),
            "jersey_num": str(p.get("num", "")),
            "position": p.get("pos"),
            "seconds_played": _safe_int(p.get("totsec")),
            "pts": _safe_int(p.get("pts")),
            "fgm": _safe_int(p.get("fgm")),
            "fga": _safe_int(p.get("fga")),
            "tpm": _safe_int(p.get("tpm")),
            "tpa": _safe_int(p.get("tpa")),
            "ftm": _safe_int(p.get("ftm")),
            "fta": _safe_int(p.get("fta")),
            "oreb": _safe_int(p.get("oreb")),
            "dreb": _safe_int(p.get("dreb")),
            "reb": _safe_int(p.get("reb")),
            "ast": _safe_int(p.get("ast")),
            "stl": _safe_int(p.get("stl")),
            "blk": _safe_int(p.get("blk")),
            "tov": _safe_int(p.get("tov")),
            "pf": _safe_int(p.get("pf")),
            "plus_minus": _safe_int(p.get("pm")),
            "fbpts": _safe_int(p.get("fbpts")),
            "fbptsa": _safe_int(p.get("fbptsa")),
            "fbptsm": _safe_int(p.get("fbptsm")),
            "pip": _safe_int(p.get("pip")),
            "pipa": _safe_int(p.get("pipa")),
            "pipm": _safe_int(p.get("pipm")),
            "blka": _safe_int(p.get("blka")),
            "tech_fouls": _safe_int(p.get("tf")),
            "court_status": _safe_int(p.get("court")),
            "player_status": p.get("status"),
            "nba_player_id": _safe_int(p.get("pid")),
        })
    return players


def parse_starting_lineup(pstsg: List[Dict], game_id: str, team_abbr: str,
                          game_date: str, season: int) -> Optional[Dict]:
    """从 pstsg 提取首发 5 人（court=1 的前5个或 pos 不为空的前5个）"""
    # starters = players with court=1, sorted by position
    starters = [p for p in pstsg if p.get("court") == 1]
    if len(starters) < 5:
        # Fallback: first 5 players with minutes > 0
        starters = [p for p in pstsg if _safe_int(p.get("min", 0)) and _safe_int(p.get("min", 0)) > 0]
    
    if len(starters) < 5:
        return None

    starters = starters[:5]
    names = [f"{p.get('fn', '')} {p.get('ln', '')}".strip() for p in starters]
    
    return {
        "season": season,
        "team_abbr": team_abbr,
        "game_date": game_date,
        "lineup_type": "starting",
        "player1": names[0] if len(names) > 0 else None,
        "player2": names[1] if len(names) > 1 else None,
        "player3": names[2] if len(names) > 2 else None,
        "player4": names[3] if len(names) > 3 else None,
        "player5": names[4] if len(names) > 4 else None,
        "minutes": None,
        "source": "data.nba.com",
    }


def parse_team_stats(tstsg: Dict, is_home: bool) -> Dict:
    """解析球队统计（用于更新 games 表）"""
    prefix = "home" if is_home else "away"
    return {
        f"{prefix}_fgm": _safe_int(tstsg.get("fgm")),
        f"{prefix}_fga": _safe_int(tstsg.get("fga")),
        f"{prefix}_tpm": _safe_int(tstsg.get("tpm")),
        f"{prefix}_tpa": _safe_int(tstsg.get("tpa")),
        f"{prefix}_ftm": _safe_int(tstsg.get("ftm")),
        f"{prefix}_fta": _safe_int(tstsg.get("fta")),
        f"{prefix}_bpts": _safe_int(tstsg.get("bpts")),
        f"{prefix}_fbpts": _safe_int(tstsg.get("fbpts")),
        f"{prefix}_pip": _safe_int(tstsg.get("pip")),
        f"{prefix}_scp": _safe_int(tstsg.get("scp")),
        f"{prefix}_potov": _safe_int(tstsg.get("potov")),
        f"{prefix}_tmreb": _safe_int(tstsg.get("tmreb")),
        f"{prefix}_tmtov": _safe_int(tstsg.get("tmtov")),
    }


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                          DB OPERATIONS                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def upsert_game_metadata(conn, meta: Dict):
    """插入/更新 game_metadata"""
    cur = conn.cursor()
    
    # Check if record exists
    cur.execute(
        "SELECT id FROM game_metadata WHERE game_id = %s OR nba_gameid = %s",
        (meta["game_id"], int(meta["game_id"]) if meta["game_id"].isdigit() else None)
    )
    existing = cur.fetchone()
    
    if existing:
        # Update existing
        cur.execute("""
            UPDATE game_metadata SET
                arena_name = COALESCE(%(arena_name)s, arena_name),
                arena_city = COALESCE(%(arena_city)s, arena_city),
                arena_state = COALESCE(%(arena_state)s, arena_state),
                attendance = COALESCE(%(attendance)s, attendance),
                officials = COALESCE(%(officials)s, officials),
                duration = COALESCE(%(duration)s, duration),
                away_q1 = COALESCE(%(away_q1)s, away_q1),
                away_q2 = COALESCE(%(away_q2)s, away_q2),
                away_q3 = COALESCE(%(away_q3)s, away_q3),
                away_q4 = COALESCE(%(away_q4)s, away_q4),
                away_ot = COALESCE(%(away_ot)s, away_ot),
                home_q1 = COALESCE(%(home_q1)s, home_q1),
                home_q2 = COALESCE(%(home_q2)s, home_q2),
                home_q3 = COALESCE(%(home_q3)s, home_q3),
                home_q4 = COALESCE(%(home_q4)s, home_q4),
                home_ot = COALESCE(%(home_ot)s, home_ot),
                api_season = %(api_season)s,
                api_status = %(api_status)s
            WHERE id = %(id)s
        """, {**meta, "id": existing[0]})
    else:
        # Insert new
        cur.execute("""
            INSERT INTO game_metadata (
                game_id, nba_gameid, arena_name, arena_city, arena_state,
                attendance, officials, duration,
                away_q1, away_q2, away_q3, away_q4, away_ot,
                home_q1, home_q2, home_q3, home_q4, home_ot,
                api_season, api_status, created_at
            ) VALUES (
                %(game_id)s, %(nba_gameid)s, %(arena_name)s, %(arena_city)s, %(arena_state)s,
                %(attendance)s, %(officials)s, %(duration)s,
                %(away_q1)s, %(away_q2)s, %(away_q3)s, %(away_q4)s, %(away_ot)s,
                %(home_q1)s, %(home_q2)s, %(home_q3)s, %(home_q4)s, %(home_ot)s,
                %(api_season)s, %(api_status)s, NOW()
            )
            ON CONFLICT DO NOTHING
        """, {
            **meta,
            "nba_gameid": int(meta["game_id"]) if meta["game_id"].isdigit() else None,
        })
    
    conn.commit()


def upsert_player_stats(conn, players: List[Dict]):
    """批量 upsert player_game_details"""
    if not players:
        return
    
    cur = conn.cursor()
    
    # Delete existing records for this game+team, then insert
    game_ids = set(p["game_id"] for p in players)
    for gid in game_ids:
        team_ids = set(p["team_id"] for p in players if p["game_id"] == gid)
        for tid in team_ids:
            cur.execute(
                "DELETE FROM player_game_details WHERE game_id = %s AND team_id = %s",
                (gid, tid)
            )
    
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
    """, players, page_size=50)
    
    conn.commit()


def upsert_starting_lineup(conn, lineup: Dict):
    """插入首发阵容"""
    if not lineup:
        return
    
    cur = conn.cursor()
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
    conn.commit()


def update_games_table(conn, game_id: str, home_stats: Dict, away_stats: Dict,
                       meta: Dict):
    """更新 games 表的球队统计字段"""
    cur = conn.cursor()
    
    # Convert 10-digit game_id to 8-digit for matching
    gid_8 = game_id.lstrip("0") or "0"
    
    set_clauses = []
    params = {}
    
    for key, val in {**home_stats, **away_stats}.items():
        set_clauses.append(f"{key} = COALESCE(%({key})s, {key})")
        params[key] = val
    
    # Also update attendance and arena
    set_clauses.append("attendance = COALESCE(%(attendance)s, attendance)")
    params["attendance"] = meta["attendance"]
    set_clauses.append("arena_name = COALESCE(%(arena_name)s, arena_name)")
    params["arena_name"] = meta["arena_name"]
    
    # Officials
    set_clauses.append("officials = COALESCE(%(officials)s, officials)")
    params["officials"] = meta["officials"]
    
    # Quarter scores
    for side in ["home", "away"]:
        for q in ["q1", "q2", "q3", "q4", "ot"]:
            col = f"{side}_{q}"
            set_clauses.append(f"{col} = COALESCE(%({col})s, {col})")
            params[col] = meta.get(col)
    
    params["game_id"] = gid_8
    
    sql = f"UPDATE games SET {', '.join(set_clauses)} WHERE game_id = %(game_id)s"
    cur.execute(sql, params)
    conn.commit()


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                          MAIN PIPELINE                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def get_game_ids_from_db(conn, season_end: int, limit: Optional[int] = None,
                         resume: bool = False) -> List[Tuple[str, str]]:
    """从 DB 获取需要爬取的 game_id 列表
    
    Args:
        season_end: DB赛季 (如 2025 = 2024-25赛季)
        limit: 最多爬取场次
        resume: True 时跳过已在 game_metadata 中有 arena_name 的比赛
    
    Returns:
        [(gid_8, api_season), ...]  e.g. [("22400061", "2024"), ...]
    """
    cur = conn.cursor()
    
    # season_end is the DB season (e.g., 2025 = 2024-25 season)
    # api_season is the start year (e.g., "2024" for 2024-25)
    api_season = str(season_end - 1)
    
    if resume:
        # Skip games already in game_metadata with arena_name
        query = """
            SELECT g.game_id FROM games g
            WHERE g.season = %s 
              AND g.game_id ~ '^[0-9]+$'
              AND g.home_pts IS NOT NULL
              AND g.home_pts > 0
              AND NOT EXISTS (
                  SELECT 1 FROM game_metadata gm 
                  WHERE gm.game_id = g.game_id AND gm.arena_name IS NOT NULL
              )
            ORDER BY g.game_id
        """
    else:
        query = """
            SELECT game_id FROM games 
            WHERE season = %s 
              AND game_id ~ '^[0-9]+$'
              AND home_pts IS NOT NULL
              AND home_pts > 0
            ORDER BY game_id
        """
    
    if limit:
        query += f" LIMIT {limit}"
    
    cur.execute(query, (season_end,))
    return [(r[0], api_season) for r in cur.fetchall()]


def get_next_incomplete_season(conn) -> Optional[int]:
    """自动检测下一个有未完成比赛的赛季
    
    按从近到远扫描 2025→2016，返回第一个还有未入库比赛的 season_end
    Returns None if all seasons complete
    """
    cur = conn.cursor()
    
    for season_end in range(2025, 2015, -1):  # 2025 → 2016
        api_season = season_end - 1
        if api_season < 2015:
            break
        
        # Count remaining games: in games table but NOT in game_metadata with arena_name
        cur.execute("""
            SELECT COUNT(*) FROM games g
            WHERE g.season = %s 
              AND g.game_id ~ '^[0-9]+$'
              AND g.home_pts IS NOT NULL
              AND g.home_pts > 0
              AND NOT EXISTS (
                  SELECT 1 FROM game_metadata gm 
                  WHERE gm.game_id = g.game_id AND gm.arena_name IS NOT NULL
              )
        """, (season_end,))
        
        remaining = cur.fetchone()[0]
        if remaining > 0:
            return season_end
    
    return None


def process_game(conn, gid_8: str, api_season: str, dry_run: bool = False) -> bool:
    """处理单场比赛: fetch → parse → upsert
    
    Returns:
        True if data was fetched and stored, False otherwise
    """
    gid_10 = gid_8.zfill(10)
    
    # Fetch
    data = fetch_gamedetail(gid_10, api_season)
    if not data:
        return False
    
    g = data.get("g", {})
    st = g.get("st")
    
    # Skip if game not final (st != 3)
    if st != 3:
        logger.debug(f"  Skip {gid_10}: status={st} (not final)")
        return False
    
    # Check if has player stats
    vls = g.get("vls", {})
    hls = g.get("hls", {})
    pstsg_v = vls.get("pstsg", [])
    pstsg_h = hls.get("pstsg", [])
    
    if not pstsg_v and not pstsg_h:
        logger.debug(f"  Skip {gid_10}: no player stats")
        return False
    
    # Parse
    meta = parse_game_metadata(g, api_season)
    game_date = g.get("gdte")
    season_end = int(api_season) + 1
    
    # Player stats
    away_players = parse_player_stats(
        pstsg_v, gid_10, str(vls.get("tid", "")), vls.get("ta", ""), is_home=False
    )
    home_players = parse_player_stats(
        pstsg_h, gid_10, str(hls.get("tid", "")), hls.get("ta", ""), is_home=True
    )
    all_players = away_players + home_players
    
    # Starting lineups
    away_lineup = parse_starting_lineup(pstsg_v, gid_10, vls.get("ta", ""), game_date, season_end)
    home_lineup = parse_starting_lineup(pstsg_h, gid_10, hls.get("ta", ""), game_date, season_end)
    
    # Team stats
    away_team_stats = parse_team_stats(vls.get("tstsg", {}), is_home=False)
    home_team_stats = parse_team_stats(hls.get("tstsg", {}), is_home=True)
    
    if dry_run:
        logger.info(f"  [DRY RUN] {gid_10}: {vls.get('ta')}@{hls.get('ta')} "
                     f"{vls.get('s')}-{hls.get('s')} | {len(all_players)} players | "
                     f"arena={meta['arena_name']}")
        return True
    
    # Upsert
    upsert_game_metadata(conn, meta)
    upsert_player_stats(conn, all_players)
    if away_lineup:
        upsert_starting_lineup(conn, away_lineup)
    if home_lineup:
        upsert_starting_lineup(conn, home_lineup)
    update_games_table(conn, gid_10, home_team_stats, away_team_stats, meta)
    
    return True


def run_pipeline(season_end: int, limit: Optional[int] = None,
                 dry_run: bool = False, batch_commit: int = 50,
                 resume: bool = False, auto: bool = False):
    """运行爬取管道
    
    Args:
        season_end: DB赛季 (如 2025 = 2024-25赛季)，auto=True 时自动检测
        limit: 最多爬取场次
        dry_run: 只测试不写库
        batch_commit: 每多少场 commit 一次
        resume: True 时跳过已入库比赛（断点续传）
        auto: True 时自动检测下一个未完成赛季
    """
    # Auto-detect season if needed
    if auto:
        conn = psycopg2.connect(**DB_CONFIG)
        season_end = get_next_incomplete_season(conn)
        conn.close()
        if season_end is None:
            logger.info("All seasons complete! Nothing to do.")
            return
        logger.info(f"Auto-selected season: {season_end-1}-{season_end}")
    elif resume and limit == 3000:
        # Default limit for --resume mode: only process up to 500 games per run
        limit = 500
    
    conn = psycopg2.connect(**DB_CONFIG)
    
    # Run migration
    if not dry_run:
        run_migration(conn)
    
    # Get game list
    games = get_game_ids_from_db(conn, season_end, limit, resume=resume)
    api_season = str(season_end - 1)
    
    logger.info(f"Season {season_end}-{season_end} (API: {api_season}): "
                f"{len(games)} games to process")
    
    if not games:
        logger.warning("No games found.")
        conn.close()
        return
    
    success = 0
    skipped = 0
    failed = 0
    start_time = time.time()
    
    for i, (gid_8, season) in enumerate(games):
        try:
            result = process_game(conn, gid_8, season, dry_run)
            if result:
                success += 1
            else:
                skipped += 1
        except Exception as e:
            logger.error(f"Error processing {gid_8}: {e}")
            failed += 1
            conn.rollback()
        
        # Progress
        if (i + 1) % 50 == 0 or i == len(games) - 1:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(games) - i - 1) / rate if rate > 0 else 0
            logger.info(
                f"  Progress: {i+1}/{len(games)} "
                f"({(i+1)/len(games)*100:.0f}%) "
                f"| OK={success} skip={skipped} fail={failed} "
                f"| {rate:.1f} g/s | ETA={eta/60:.0f}min"
            )
    
    elapsed = time.time() - start_time
    logger.info(f"\n{'='*60}")
    logger.info(f"DONE: {success} success, {skipped} skipped, {failed} failed")
    logger.info(f"Time: {elapsed/60:.1f} min ({elapsed/success:.1f}s/game)" if success else "")
    logger.info(f"{'='*60}")
    
    conn.close()


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                          CLI                                              ║
# ╚══════════════════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NBA data.nba.com → PostgreSQL ingester")
    parser.add_argument("--season", type=int, default=0,
                        help="DB season end year (e.g., 2025 = 2024-25 season)")
    parser.add_argument("--limit", type=int, default=3000,
                        help="Max games to process (default: 3000/all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch only, don't write to DB")
    parser.add_argument("--batch", type=int, default=50,
                        help="Batch commit size (default: 50)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip games already in game_metadata (断点续传)")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-detect next incomplete season and crawl")
    
    args = parser.parse_args()
    
    if args.auto:
        # Auto mode: detect season, enable resume, limit to 500 per run
        run_pipeline(
            season_end=0,
            limit=500,
            dry_run=args.dry_run,
            batch_commit=args.batch,
            resume=True,
            auto=True,
        )
    elif args.resume:
        # Resume mode: skip already-processed, limit 500 per run
        run_pipeline(
            season_end=args.season,
            limit=args.limit if args.limit != 3000 else 500,
            dry_run=args.dry_run,
            batch_commit=args.batch,
            resume=True,
            auto=False,
        )
    else:
        # Full mode: process all (or up to limit)
        run_pipeline(
            season_end=args.season,
            limit=args.limit if args.limit != 3000 else None,
            dry_run=args.dry_run,
            batch_commit=args.batch,
            resume=False,
            auto=False,
        )
