#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
espn_broad_crawler.py —— ESPN 宽数据集爬虫（G3 核心）
=====================================================
抓 ESPN Site API v2 summary → 解析盒式(球队/球员) + 投篮坐标 →
原始 JSON 落盘 raw_archive/espn/{date}/{event}.json → 解析结果 upsert 进 espn_boxscore。
同步更新 game_id_map.espn_have / espn_event。

复用（绝不重写脆弱解析器）:
- external_crawler/crawler/espn_backfill_shot_coords.py 的 SCOREBOARD / HDR /
  our_to_espn / espn_to_our（summary 抓取 + 按 (date, 主客队) 映射 event id 逻辑,
  直接 import 复用）。
- raw_archiver.save_espn_json 落盘原始 JSON（与 espn_backfill 共享归档逻辑，原子写+去重）。

铁律（ARCH §8）:
- 原始 JSON 必落盘（呼应 P0-3），路径严格 raw_archive/espn/{date}/{event}.json。
- upsert 走 ON CONFLICT(espn_event) DO UPDATE（幂等）；重跑安全。
- 绝不触碰 play_by_play 的 (x,y) 坐标（本脚本只写 espn_boxscore，与坐标热表无关）。

支持:
  --dry-run   只打印将抓取的场，不落库/不落盘
  --season N  仅处理 game_id_map 中指定赛季（默认 >=2023）
  --limit  N  最多处理 N 场
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import requests  # noqa: E402
from common.bridge_constants import get_pg_conn  # noqa: E402
import raw_archiver  # noqa: E402

# 复用既有脚本的端点 / 请求头 / 缩写映射（ARCH: 直接 import 复用，不重写）
from external_crawler.crawler.espn_backfill_shot_coords import (  # noqa: E402
    SCOREBOARD,
    HDR,
    our_to_espn,
    espn_to_our,
)

SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={eid}"
RATE_LIMIT = 1.0  # ESPN 非 Akamai，普通 requests + UA/Referer 即可 200


# ---------------------------------------------------------------------------
# event id 解析（复用 espn_backfill 的映射逻辑）
# ---------------------------------------------------------------------------
def resolve_event_id(gdate, home_abbr: str, away_abbr: str, session) -> "Optional[str]":
    """按 (date, 主客队) 解析 ESPN event id（与 espn_backfill.espn_event_id 同源）。"""
    if isinstance(gdate, (date,)):
        ymd = gdate.strftime("%Y%m%d")
    else:
        ymd = str(gdate).replace("-", "")[:8]
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


# ---------------------------------------------------------------------------
# 目标获取
# ---------------------------------------------------------------------------
def get_targets(conn, season: "Optional[int]", limit: int):
    """取 game_id_map 中 espn_have=false 且 season 在范围内（默认 >=2023）的场。"""
    where = "m.season >= 2023" if season is None else "m.season = %s"
    params = [] if season is None else [int(season)]
    limit_clause = "" if not limit else f"LIMIT {int(limit)}"
    sql = f"""
        SELECT m.br_gid, m.espn_event, m.game_date, m.season,
               m.nba_api_id, m.home_abbr, m.away_abbr
        FROM game_id_map m
        WHERE m.espn_have = false AND {where}
        ORDER BY m.game_date
        {limit_clause}
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# 抓取 + 解析
# ---------------------------------------------------------------------------
def fetch_summary_text(eid: str, session) -> "Optional[str]":
    try:
        r = session.get(SUMMARY.format(eid=eid), headers=HDR, timeout=25)
    except Exception:  # noqa: BLE001
        return None
    if r.status_code != 200:
        return None
    return r.text


def parse_boxscore(summary: dict) -> dict:
    """从 summary 解析 球队盒式 / 球员盒式 / 投篮坐标。返回结构化 dict。"""
    box = summary.get("boxscore", {}) or {}

    # 主客队区分：优先 summary.teams 的 homeAway 标志，取缩写与比分
    comps = summary.get("teams", []) or []
    home_abbr = away_abbr = None
    home_pts = away_pts = None
    for c in comps:
        t = c.get("team", {}) or {}
        abbr = espn_to_our(t.get("abbreviation"))
        try:
            pts = int(c.get("score") or 0)
        except (ValueError, TypeError):
            pts = None
        if c.get("homeAway") == "home":
            home_abbr, home_pts = abbr, pts
        else:
            away_abbr, away_pts = abbr, pts

    # 球队盒式（boxscore.teams，含 team 信息与 statistics 数组）
    teams_raw = box.get("teams", []) or []
    home_box = away_box = None
    for t in teams_raw:
        tinfo = t.get("team", {}) or {}
        abbr = espn_to_our(tinfo.get("abbreviation"))
        if abbr == home_abbr:
            home_box = t
        elif abbr == away_abbr:
            away_box = t

    # 球员盒式（boxscore.players，全量数组，按球队分组 + statistics）
    player_boxes = box.get("players", []) or []

    # 投篮坐标（summary.plays 中 shootingPlay 且带真实 coordinate）
    shots = []
    for p in summary.get("plays", []) or []:
        if not isinstance(p, dict):
            continue
        if not p.get("shootingPlay"):
            continue
        coord = p.get("coordinate") or {}
        if coord.get("x") is None or coord.get("y") is None:
            continue
        ath = (p.get("athletes") or [])
        player_name = ath[0].get("athlete", {}).get("displayName") if ath else None
        player_id = ath[0].get("athlete", {}).get("id") if ath else None
        team_abbr = espn_to_our((p.get("team") or {}).get("abbreviation"))
        period = (p.get("period") or {}).get("number")
        clock = (p.get("clock") or {}).get("displayValue")
        low = (p.get("text") or "").lower()
        # ESPN plays[].text 以球员名开头(如 "Chet Holmgren makes 1-foot layup"),
        # 故不能用 startswith；用子串 "makes" in low 正确区分命中/未中
        # ("misses" 不含 "makes"，不会误判；也不用 "make" in low 以免命中 "makeup" 之类)。
        made = "makes" in low
        shots.append({
            "player_id": player_id,
            "player_name": player_name,
            "team": team_abbr,
            "period": period,
            "clock": clock,
            "x": coord.get("x"),
            "y": coord.get("y"),
            "made": made,
        })

    # season_type：优先 summary.season.type，退路取 header competitions type
    season_type = (summary.get("season", {}) or {}).get("type")
    if season_type is None:
        hdr = summary.get("header", {}) or {}
        comps0 = (hdr.get("competitions", []) or [{}])[0]
        season_type = (comps0.get("type") or {}).get("type")

    return {
        "home_team_box": home_box,
        "away_team_box": away_box,
        "player_boxes": player_boxes,
        "shot_coords": shots,
        "home_abbr": home_abbr,
        "away_abbr": away_abbr,
        "home_pts": home_pts,
        "away_pts": away_pts,
        "season_type": season_type,
    }


UPSERT_BOX = """
    INSERT INTO espn_boxscore (
        espn_event, br_gid, nba_api_id, game_date, season, season_type,
        home_abbr, away_abbr, home_pts, away_pts,
        home_team_box, away_team_box, player_boxes, shot_coords, raw_json_path
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (espn_event) DO UPDATE SET
        br_gid        = EXCLUDED.br_gid,
        nba_api_id    = EXCLUDED.nba_api_id,
        game_date     = EXCLUDED.game_date,
        season        = EXCLUDED.season,
        season_type   = EXCLUDED.season_type,
        home_abbr     = EXCLUDED.home_abbr,
        away_abbr     = EXCLUDED.away_abbr,
        home_pts      = EXCLUDED.home_pts,
        away_pts      = EXCLUDED.away_pts,
        home_team_box = EXCLUDED.home_team_box,
        away_team_box = EXCLUDED.away_team_box,
        player_boxes  = EXCLUDED.player_boxes,
        shot_coords   = EXCLUDED.shot_coords,
        raw_json_path = EXCLUDED.raw_json_path,
        archived_at   = now()
"""

SET_ESPN_HAVE = """
    UPDATE game_id_map
    SET espn_have = true,
        espn_event = %s,
        matched_at = now(),
        match_method = COALESCE(match_method, 'espn_only')
    WHERE br_gid = %s
"""


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(conn, dry_run: bool, season: "Optional[int]", limit: int):
    rows = get_targets(conn, season, limit)
    print(f"[i] 待抓 ESPN 宽数据场: {len(rows)}  dry_run={dry_run}", flush=True)
    if not rows:
        return 0, 0

    session = requests.Session()
    ok = fail = 0
    last = 0.0
    for (br_gid, espn_event, gdate, gseason, nba_api, h_abbr, a_abbr) in rows:
        date_str = gdate.isoformat() if isinstance(gdate, (date,)) else str(gdate)
        # 解析/补全 espn_event（桥接已填则复用，孤儿则按 date+主客队解析）
        eid = espn_event or resolve_event_id(gdate, h_abbr, a_abbr, session)
        if not eid:
            print(f"  ! 无法解析 ESPN event {br_gid} {date_str}", flush=True)
            fail += 1
            continue

        if dry_run:
            print(f"  [dry] br={br_gid} espn={eid} {date_str} S{gseason}", flush=True)
            ok += 1
            continue

        # 限速（避免触发 ESPN 风控）
        el = time.time() - last
        if el < RATE_LIMIT:
            time.sleep(RATE_LIMIT - el)
        last = time.time()

        text = fetch_summary_text(eid, session)
        if not text:
            print(f"  ! ESPN 抓取失败 {eid}", flush=True)
            fail += 1
            continue

        # 落盘原始 JSON（原子写 + 去重；与 espn_backfill 共享归档逻辑）
        raw_archiver.save_espn_json(date_str, eid, text, write_sha256=False)
        rel_path = f"raw_archive/espn/{date_str}/{eid}.json"

        try:
            summary = json.loads(text)
            parsed = parse_boxscore(summary)
        except Exception as e:  # noqa: BLE001
            print(f"  ! 解析失败 {eid}: {e}", flush=True)
            fail += 1
            continue

        with conn.cursor() as cur:
            cur.execute(UPSERT_BOX, (
                eid, br_gid, nba_api, gdate, gseason, parsed["season_type"],
                parsed["home_abbr"], parsed["away_abbr"],
                parsed["home_pts"], parsed["away_pts"],
                json.dumps(parsed["home_team_box"], ensure_ascii=False),
                json.dumps(parsed["away_team_box"], ensure_ascii=False),
                json.dumps(parsed["player_boxes"], ensure_ascii=False),
                json.dumps(parsed["shot_coords"], ensure_ascii=False),
                rel_path,
            ))
            cur.execute(SET_ESPN_HAVE, (eid, br_gid))
        conn.commit()
        print(f"  [ok] br={br_gid} espn={eid} {date_str} "
              f"shots={len(parsed['shot_coords'])}", flush=True)
        ok += 1

    print(f"\n[done] 成功 {ok}  失败 {fail}", flush=True)
    return ok, fail


def main():
    ap = argparse.ArgumentParser(description="ESPN 宽数据集爬虫（盒式+坐标+落盘）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将抓取的场，不落库/不落盘")
    ap.add_argument("--season", type=int, default=None, help="仅处理指定赛季（默认 >=2023）")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 场（默认 0=全部）")
    args = ap.parse_args()

    conn = get_pg_conn()
    try:
        run(conn, args.dry_run, args.season, args.limit)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
