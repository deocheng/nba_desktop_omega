#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
game_id_bridge.py —— 跨源身份对账编排（G1 核心）
================================================
扫 dim_games（season >= 2023，或 --season 指定），逐行调 matcher.match_game
解析 (br_gid, nba_api_id, espn_event)，幂等 upsert 进 game_id_map
（ON CONFLICT(br_gid) DO UPDATE），并置 pbp_under_api / pbp_under_br
（由 EXISTS play_by_play 探测）。

支持：
  --dry-run   只打印将写入的映射，不落库（铁律：不碰坐标）
  --season N  仅处理指定赛季（默认 >=2023）
  --limit  N  最多处理 N 行
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common.bridge_constants import get_pg_conn  # noqa: E402
from matcher import match_game                    # noqa: E402


UPSERT_SQL = """
    INSERT INTO game_id_map (
        br_gid, nba_api_id, espn_event, season, game_date,
        home_abbr, away_abbr, home_pts, away_pts,
        pbp_under_api, pbp_under_br, match_method
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (br_gid) DO UPDATE SET
        nba_api_id    = EXCLUDED.nba_api_id,
        espn_event    = COALESCE(EXCLUDED.espn_event, game_id_map.espn_event),
        season        = EXCLUDED.season,
        game_date     = EXCLUDED.game_date,
        home_abbr     = EXCLUDED.home_abbr,
        away_abbr     = EXCLUDED.away_abbr,
        home_pts      = EXCLUDED.home_pts,
        away_pts      = EXCLUDED.away_pts,
        pbp_under_api = EXCLUDED.pbp_under_api,
        pbp_under_br  = EXCLUDED.pbp_under_br,
        match_method  = EXCLUDED.match_method,
        matched_at    = now()
"""

PBP_FLAGS_SQL = """
    SELECT
        EXISTS (SELECT 1 FROM play_by_play p
                WHERE %s IS NOT NULL AND p.gameid = %s::text),
        EXISTS (SELECT 1 FROM play_by_play p
                WHERE p.gameid = %s)
"""

SELECT_SQL = """
    SELECT game_id, nba_api_id, game_date,
           home_team_abbr, away_team_abbr, home_pts, away_pts, season
    FROM dim_games
    WHERE {where}
    ORDER BY game_date
    {limit}
"""


def fetch_targets(conn, season: "Optional[int]", limit: int):
    """返回待对账的 dim_games 行列表。"""
    where = "season >= 2023" if season is None else "season = %s"
    params = [] if season is None else [int(season)]
    limit_clause = "" if not limit else f"LIMIT {int(limit)}"
    sql = SELECT_SQL.format(where=where, limit=limit_clause)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _pbp_flags(conn, br_gid: str, nba_api_id: "Optional[str]"):
    """探测 PBP 是否挂在 nba_api_id 键下 / br_gid 键下。"""
    with conn.cursor() as cur:
        cur.execute(PBP_FLAGS_SQL, (nba_api_id, nba_api_id, br_gid))
        under_api, under_br = cur.fetchone()
    return bool(under_api), bool(under_br)


def reconcile(conn, dry_run: bool, season: "Optional[int]", limit: int):
    """执行对账。返回 (处理数, 写入/将写数, 跳过/未匹配数)。"""
    rows = fetch_targets(conn, season, limit)
    print(f"[i] 待对账 dim_games 行: {len(rows)}  dry_run={dry_run}", flush=True)
    if not rows:
        return 0, 0, 0

    # ESPN 会话（仅孤儿需要；离线/无网络时 resolve 返回 None，不影响主流程）
    espn_session = None
    try:
        import requests
        espn_session = requests.Session()
    except Exception:  # noqa: BLE001
        espn_session = None

    processed = written = unmatched = 0
    for (gid, nba_api, gdate, h_abbr, a_abbr, h_pts, a_pts, gseason) in rows:
        mr = match_game(
            gdate, h_abbr, a_abbr, h_pts, a_pts,
            conn=conn, espn_session=espn_session, season=gseason,
        )
        processed += 1
        if mr.status == "unmatched":
            unmatched += 1
            print(f"  [未匹配] {gid} {gdate} {a_abbr}@{h_abbr} "
                  f"pts={h_pts}-{a_pts}", flush=True)
            continue

        # PBP 覆盖标志（EXISTS play_by_play）
        under_api, under_br = _pbp_flags(conn, mr.br_gid, mr.nba_api_id)
        nba_api_str = mr.nba_api_id
        print(f"  [{mr.method}/{mr.status}] br={mr.br_gid} api={nba_api_str} "
              f"espn={mr.espn_event} pbp_api={under_api} pbp_br={under_br}",
              flush=True)

        if dry_run:
            written += 1
            continue

        with conn.cursor() as cur:
            cur.execute(UPSERT_SQL, (
                mr.br_gid, nba_api_str, mr.espn_event, gseason, gdate,
                h_abbr, a_abbr, h_pts, a_pts,
                under_api, under_br, mr.method,
            ))
        conn.commit()
        written += 1

    return processed, written, unmatched


def main():
    ap = argparse.ArgumentParser(description="跨源 game_id 桥接对账")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印将写入的映射，不落库")
    ap.add_argument("--season", type=int, default=None,
                    help="仅处理指定赛季（默认 >=2023）")
    ap.add_argument("--limit", type=int, default=0,
                    help="最多处理 N 行（默认 0=全部）")
    args = ap.parse_args()

    conn = get_pg_conn()
    try:
        processed, written, unmatched = reconcile(
            conn, args.dry_run, args.season, args.limit)
    finally:
        conn.close()
    print(f"\n[done] 处理={processed}  写入/将写={written}  未匹配={unmatched}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
