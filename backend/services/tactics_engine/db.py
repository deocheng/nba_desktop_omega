"""NBACore v8 — Tactics Engine 数据接入层（Layer 1 只读）。

严格走 backend.core.db.batch_query（SELECT + 参数化），禁止动态 SQL、
禁止 per-row 循环、无 DML。所有 SQL 可 trace（带 query_id）。
"""
from __future__ import annotations

from typing import List, Optional

from backend.core import db as core_db
from backend.services.tactics_engine.schemas import GameMeta, PbPEvent


def _season_int(season) -> int:
    """统一将 season（str/int）转为 int 用于参数化查询。"""
    return int(season)


def load_pbp_events(game_id: str, season) -> List[PbPEvent]:
    """批量读取某场全部 br_crawler PBP 事件（按 period ASC, clock DESC, id ASC 时间序）。"""
    sql = """
        SELECT gameid, season, period, clock_seconds,
               event_type, subtype, action_verb, player, player2_name, team, x, y, dist
        FROM play_by_play
        WHERE gameid = %s
          AND season = %s::integer
          AND source = 'br_crawler'
        ORDER BY period ASC, clock_seconds DESC, id ASC
    """
    rows = core_db.batch_query(sql, (str(game_id), _season_int(season)))
    events: List[PbPEvent] = []
    for i, r in enumerate(rows):
        events.append(PbPEvent(
            event_index=i,
            game_id=str(r["gameid"]),
            season=str(r["season"]),
            period=int(r["period"]),
            clock_seconds=float(r["clock_seconds"]),
            event_type=r["event_type"] or "",
            subtype=r["subtype"] or "",
            action_verb=r["action_verb"] or "",
            player=r["player"] or "",
            player2=r["player2_name"] or "",
            team=r["team"] or "",
            x=int(r["x"] or 0),
            y=int(r["y"] or 0),
            dist=int(r["dist"] or 0),
        ))
    return events


def list_replay_games(season) -> List[dict]:
    """列出该赛季可回放比赛（仅 br_crawler 有 xy 的），含两队与事件/xy 计数。"""
    sql = """
        SELECT gameid,
               COUNT(*) AS event_count,
               COUNT(*) FILTER (WHERE x <> 0 AND y <> 0) AS xy_count,
               ARRAY_AGG(DISTINCT team) FILTER (WHERE team IS NOT NULL) AS teams
        FROM play_by_play
        WHERE season = %s::integer
          AND source = 'br_crawler'
        GROUP BY gameid
        HAVING COUNT(*) FILTER (WHERE x <> 0 AND y <> 0) > 0
        ORDER BY gameid
    """
    rows = core_db.batch_query(sql, (_season_int(season),))
    out: List[dict] = []
    for r in rows:
        teams = r["teams"] or []
        out.append({
            "game_id": str(r["gameid"]),
            "teams": list(teams),
            "event_count": int(r["event_count"]),
            "xy_count": int(r["xy_count"]),
        })
    return out


def load_game_meta(game_id: str, season) -> Optional[GameMeta]:
    """读取单场比赛元数据（队、节范围、事件数、xy 覆盖数）。"""
    sql = """
        SELECT gameid, season,
               MIN(period) AS period_min,
               MAX(period) AS period_max,
               COUNT(*) AS event_count,
               COUNT(*) FILTER (WHERE x <> 0 AND y <> 0) AS xy_count,
               ARRAY_AGG(DISTINCT team) FILTER (WHERE team IS NOT NULL) AS teams
        FROM play_by_play
        WHERE gameid = %s
          AND season = %s::integer
          AND source = 'br_crawler'
        GROUP BY gameid, season
    """
    rows = core_db.batch_query(sql, (str(game_id), _season_int(season)))
    if not rows:
        return None
    r = rows[0]
    return GameMeta(
        game_id=str(r["gameid"]),
        season=str(r["season"]),
        teams=list(r["teams"] or []),
        period_min=int(r["period_min"]),
        period_max=int(r["period_max"]),
        event_count=int(r["event_count"]),
        xy_count=int(r["xy_count"]),
    )
