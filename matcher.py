#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
matcher.py —— 跨源比赛身份匹配（纯函数，可单测）
================================================
输入锚点 (game_date, home_abbr, away_abbr, home_pts, away_pts)，
经 canon_abbr 归一化后：
  1. 先查 dim_games（锚点精确匹配）→ 得到 br_gid / nba_api_id（method='dim_games'）
  2. 孤儿(nba_api_id IS NULL) 再查 ESPN summary（date+主客队）→ 得到 espn_event
     （method 增 'anchor+espn'/ 仅 ESPN 命中为 'espn_only'）
  3. 输出 MatchResult；任一 leg 缺失则 status='partial'，全缺则 'unmatched'。

本模块不依赖脆弱的 PBP 解析器；只做键解析，绝不触碰 (x,y) 坐标。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

# 允许从任意工作目录以脚本/模块方式导入本文件与其依赖
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common.bridge_constants import canon_abbr  # noqa: E402


@dataclass
class MatchResult:
    """单场比赛的跨源键解析结果。"""
    br_gid: Optional[str]
    nba_api_id: Optional[str]
    espn_event: Optional[str]
    method: str            # 'dim_games' | 'anchor+espn' | 'espn_only' | 'unmatched'
    status: str            # 'matched' | 'partial' | 'unmatched'


def _to_ymd(gdate) -> str:
    """比赛日期 -> 'YYYYMMDD' 字符串（供 ESPN scoreboard 端点）。"""
    if isinstance(gdate, (date, datetime)):
        return gdate.strftime("%Y%m%d")
    return str(gdate).replace("-", "")[:8]


def resolve_espn_event(game_date, home_abbr: str, away_abbr: str,
                       session=None) -> Optional[str]:
    """按 (date, 主客队) 解析 ESPN event id（复用 espn_backfill 的端点与映射）。

    仅在传入 requests.Session 时尝试网络；否则返回 None（纯函数、离线安全）。
    """
    if session is None:
        return None
    # 复用既有脚本的端点 / 请求头 / 缩写映射（照 ARCH：复用现成逻辑）
    try:
        from external_crawler.crawler.espn_backfill_shot_coords import (
            SCOREBOARD, HDR, our_to_espn,
        )
    except Exception:  # noqa: BLE001
        return None

    ymd = _to_ymd(game_date)
    want = {our_to_espn(home_abbr), our_to_espn(away_abbr)}
    if None in want:
        return None
    try:
        r = session.get(SCOREBOARD.format(ymd=ymd), headers=HDR, timeout=25)
        if r.status_code != 200:
            return None
        sb = r.json()
    except Exception:  # noqa: BLE001
        return None
    events = (sb or {}).get("events", [])
    for e in events:
        comps = e.get("competitions", [{}])[0].get("competitors", [])
        got = {c.get("team", {}).get("abbreviation") for c in comps}
        if want.issubset(got) or got == want:
            return e.get("id")
    return None


def match_game(game_date, home_abbr: str, away_abbr: str,
               home_pts: int, away_pts: int, *,
               conn, espn_session=None, season: Optional[int] = None) -> MatchResult:
    """锚点匹配主函数（纯函数，conn 为只读 psycopg2 连接）。

    流程见模块 docstring。返回 MatchResult。
    """
    # 归一化三源队名（2023-26 实测一致；空安全网，仍为 passthrough）
    h = canon_abbr("nba_api", home_abbr)
    a = canon_abbr("nba_api", away_abbr)

    br_gid: Optional[str] = None
    nba_api_id: Optional[str] = None

    # ① 锚点精确匹配 dim_games
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT game_id, nba_api_id
            FROM dim_games
            WHERE game_date = %s
              AND home_team_abbr = %s
              AND away_team_abbr = %s
              AND (home_pts IS NOT DISTINCT FROM %s)
              AND (away_pts IS NOT DISTINCT FROM %s)
            LIMIT 1
            """,
            (game_date, h, a, home_pts, away_pts),
        )
        row = cur.fetchone()
    if row is not None:
        br_gid = row[0]
        nba_api_id = str(row[1]) if row[1] is not None else None

    # ② 孤儿（nba_api_id 为 NULL）再查 ESPN 解析 event id
    espn_event: Optional[str] = None
    if nba_api_id is None and espn_session is not None:
        espn_event = resolve_espn_event(game_date, home_abbr, away_abbr, espn_session)

    # ③ 判定 method / status
    if br_gid and nba_api_id and espn_event:
        method, status = "anchor+espn", "matched"
    elif br_gid and nba_api_id:
        method, status = "dim_games", "matched"
    elif br_gid and espn_event:
        method, status = "anchor+espn", "partial"
    elif br_gid:
        method, status = "dim_games", "partial"      # 孤儿，ESPN 暂未解析
    elif espn_event:
        method, status = "espn_only", "partial"
    else:
        method, status = "unmatched", "unmatched"

    return MatchResult(
        br_gid=br_gid,
        nba_api_id=nba_api_id,
        espn_event=espn_event,
        method=method,
        status=status,
    )
