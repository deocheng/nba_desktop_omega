#!/usr/bin/env python3
"""
投篮坐标补爬 —— 探针 / 入库 脚本
=====================================
背景:
  play_by_play 中真实坐标 (x,y) 来自 cdn.nba.com 的逐回合 JSON
  (https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{10位id}.json)。
  basketball-reference 的文字 PBP 不含坐标,那些场次目前靠引擎"重建"近似坐标。
  本脚本用于把"完全无真实坐标"的场次,尝试从 cdn 重新抓取并补 x/y。

两种模式:
  --probe   只探测可达性,不写库。报告每场 HTTP 状态 + actions 数。
  --apply   探测成功(200 且 actions>0)的场次,把 cdn 的 x/y 写回 play_by_play。
             apply 采用 REPLACE 策略:DELETE 该场现有行,INSERT cdn 版本(含真实 x/y)。
             仅对"完全无坐标"的场次执行;执行前会在 pbp_backup/ 留一份 CSV 备份。

10位 cdn id 推导:
  - gameid 纯数字 (如 "22500001","11300001") -> "00" + zfill(8)
  - BR 格式且有 dim_games.nba_api_id -> "00" + str(nba_api_id).zfill(8)
  - 其余(无映射)跳过。

限速: 默认 1.2s/请求(cdn 有 Akamai,需 curl_cffi 伪装 Chrome TLS 指纹)。
"""
from __future__ import annotations
import os
import argparse, csv, os, re, sys, time, random
from datetime import datetime
from pathlib import Path

import psycopg2

DB_CONFIG = dict(host="localhost", port=5433, dbname="nba", user="postgres", password=os.environ.get("DB_PASSWORD"))
CDN = "https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{gid}.json"
# 完整浏览器头 —— 实测仅用 UA+Referer 会被 cdn 返回 403，
# 必须带 sec-ch-ua / sec-fetch-* / accept-encoding 才能拿到 200（无需 curl_cffi TLS 指纹）。
HDR = {
    "accept": "application/json, text/plain, */*",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-US,en;q=0.9",
    "origin": "https://www.nba.com",
    "referer": "https://www.nba.com/",
    "sec-ch-ua": '"Not:A-Brand";v="99", "Chromium";v="124"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}
RATE_LIMIT = 1.2
_PROJ = Path(__file__).resolve().parent
_BACKUP = _PROJ.parent.parent / "pbp_backup"   # external_crawler/pbp_backup


def cdn_id_of(conn, gameid: str, nba_api_id) -> str | None:
    if re.fullmatch(r"\d+", gameid or ""):
        return "00" + gameid.zfill(8)
    if nba_api_id:
        return "00" + str(nba_api_id).zfill(8)
    # BR 格式(如 202311010DAL): 按 日期+球队 在 dim_games 反查 nba_api_id
    # （近季 play_by_play.gameid 用 BR 格式，而 dim_games.game_id 用 cdn 数字 id，直接 JOIN 不上）
    m = re.fullmatch(r"(\d{8})0([A-Z]{3})", gameid or "")
    if not m:
        return None
    gdate, away = m.group(1), m.group(2)
    cur = conn.cursor()
    cur.execute(
        "SELECT nba_api_id FROM dim_games "
        "WHERE game_date=%s AND (%s IN (home_team_abbr, away_team_abbr)) "
        "AND nba_api_id IS NOT NULL LIMIT 1",
        (gdate, away),
    )
    r = cur.fetchone()
    return ("00" + str(r[0]).zfill(8)) if r else None


def missing_games(conn, limit=None, seasons=None):
    """返回 (gameid, nba_api_id, season) 完全无坐标的场次。"""
    cur = conn.cursor()
    sql = """
    WITH miss AS (
      SELECT gameid FROM play_by_play
      GROUP BY gameid
      HAVING bool_and(NOT (x IS NOT NULL AND y IS NOT NULL AND (x<>0 OR y<>0)))
    )
    SELECT m.gameid, d.nba_api_id, MAX(p.season)
    FROM miss m
    LEFT JOIN dim_games d ON d.game_id = m.gameid
    JOIN play_by_play p ON p.gameid = m.gameid
    GROUP BY m.gameid, d.nba_api_id
    """
    if seasons:
        sql += " HAVING MAX(p.season) = ANY(%s)" % ("%s",)
    sql += " ORDER BY 3 NULLS LAST, 1"
    cur.execute(sql, (list(seasons),) if seasons else None)
    rows = cur.fetchall()
    if limit:
        rows = rows[:limit]
    return rows


def _wait(last):
    el = time.time() - last
    if el < RATE_LIMIT:
        time.sleep(RATE_LIMIT - el + random.uniform(0, 0.2))
    return time.time()


def fetch(gid10: str, sess):
    import requests
    url = CDN.format(gid=gid10)
    r = sess.get(url, headers=HDR, timeout=25)
    if r.status_code != 200:
        return r.status_code, 0, None
    try:
        d = r.json()
    except Exception:
        return 200, 0, None
    acts = d.get("game", {}).get("actions", [])
    return 200, len(acts), d


def probe(conn, rows):
    import requests as cffi
    last = 0.0
    ok = noid = blocked = notfound = 0
    print(f"{'gameid':14} {'season':8} {'cdn_id':12} {'HTTP':5} {'acts':5}")
    for gameid, api_id, season in rows:
        cid = cdn_id_of(conn, gameid, api_id)
        if not cid:
            print(f"{gameid:14} {str(season):8} {'--':12} SKIP  no-cdn-id")
            noid += 1
            continue
        last = _wait(last)
        sc, na, _ = fetch(cid, cffi)
        tag = "OK" if (sc == 200 and na > 0) else ("404" if sc == 404 else ("403" if sc == 403 else str(sc)))
        if sc == 200 and na > 0: ok += 1
        elif sc == 404: notfound += 1
        elif sc == 403: blocked += 1
        print(f"{gameid:14} {str(season):8} {cid:12} {sc:<5} {na:<5}")
    print(f"\n探针汇总: 可抓(200+acts)={ok}  404={notfound}  403封禁={blocked}  无cdn-id={noid}")


def apply(conn, rows):
    import requests as cffi
    _BACKUP.mkdir(parents=True, exist_ok=True)
    cur = conn.cursor()
    last = 0.0
    done = skip = fail = 0
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for gameid, api_id, season in rows:
        cid = cdn_id_of(conn, gameid, api_id)
        if not cid:
            skip += 1
            continue
        last = _wait(last)
        sc, na, data = fetch(cid, cffi)
        if sc != 200 or na == 0:
            skip += 1
            continue
        # 备份现有行
        cur.execute("SELECT * FROM play_by_play WHERE gameid=%s", (gameid,))
        cols = [d[0] for d in cur.description]
        exist = cur.fetchall()
        bk = _BACKUP / f"{gameid}_{ts}.csv"
        with bk.open("w", newline="") as f:
            w = csv.writer(f); w.writerow(cols)
            for row in exist: w.writerow(row)
        # REPLACE: 删除后插入 cdn 版本
        cur.execute("DELETE FROM play_by_play WHERE gameid=%s", (gameid,))
        ins = []
        for a in data["game"]["actions"]:
            at = a.get("actionType", "")
            if at == "period" and a.get("subType", "") in ("start", "end"):
                continue
            ins.append({
                "gameid": gameid, "season": season,
                "eventnum": a.get("actionNumber"),
                "period": a.get("period"),
                "clock": _pt_to_clock(a.get("clock", "")),
                "clock_seconds": _pt_to_seconds(a.get("clock", "")),
                "h_pts": _i(a.get("scoreHome")), "a_pts": _i(a.get("scoreAway")),
                "team": a.get("teamTricode"),
                "playerid": a.get("personId") if a.get("personId") not in (0, None) else None,
                "player": a.get("playerNameI") or a.get("playerName"),
                "event_type": at, "subtype": a.get("subType"),
                "result": (a.get("descriptor") or "")[:20],
                "x": _i(a.get("x")), "y": _i(a.get("y")), "dist": None,
                "description": a.get("description"),
                "current_team": a.get("teamTricode"),
                "source": "BBRef",   # 标 BBRef 保持动画下拉可见（过滤 IN ('br_crawler','BBRef')）
            })
        if ins:
            from psycopg2.extras import execute_batch
            execute_batch(
                cur,
                "INSERT INTO play_by_play "
                "(gameid,season,eventnum,period,clock,clock_seconds,h_pts,a_pts,team,playerid,player,"
                "event_type,subtype,result,x,y,dist,description,current_team,source) "
                "VALUES (%(gameid)s,%(season)s,%(eventnum)s,%(period)s,%(clock)s,%(clock_seconds)s,"
                "%(h_pts)s,%(a_pts)s,%(team)s,%(playerid)s,%(player)s,%(event_type)s,%(subtype)s,"
                "%(result)s,%(x)s,%(y)s,%(dist)s,%(description)s,%(current_team)s,%(source)s)", ins, page_size=100)
            conn.commit()
            done += 1
            print(f"  {gameid}: 补 {len(ins)} 行 (备份 {bk.name})")
        else:
            conn.rollback(); fail += 1
    print(f"\n入库汇总: 补坐标={done}  跳过={skip}  失败={fail}")


def _i(v):
    if v in (None, ""): return None
    try: return int(float(v))
    except: return None


def _pt_to_seconds(pt_str: str):
    if not pt_str:
        return None
    m = re.match(r"PT(\d+)M([\d.]+)S", pt_str)
    if m:
        return int(m.group(1)) * 60 + int(float(m.group(2)))
    return None


def _pt_to_clock(pt_str: str):
    if not pt_str:
        return None
    m = re.match(r"PT(\d+)M([\d.]+)S", pt_str)
    if m:
        return f"{int(m.group(1)):02d}:{int(float(m.group(2))):02d}"
    return pt_str


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="只探测可达性,不写库")
    ap.add_argument("--apply", action="store_true", help="探测成功则写回 x/y")
    ap.add_argument("--limit", type=int, default=None, help="最多处理多少场(默认不限制)")
    ap.add_argument("--seasons", type=int, nargs="*", help="限定赛季,如 --seasons 2024 2026")
    args = ap.parse_args()
    if not (args.probe or args.apply):
        ap.error("需指定 --probe 或 --apply")
    conn = psycopg2.connect(**DB_CONFIG)
    rows = missing_games(conn, limit=args.limit, seasons=args.seasons)
    print(f"待处理(完全无坐标)场次: {len(rows)}")
    if args.probe:
        probe(conn, rows)
    else:
        apply(conn, rows)
    conn.close()


if __name__ == "__main__":
    main()
