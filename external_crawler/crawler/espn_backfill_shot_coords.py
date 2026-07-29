#!/usr/bin/env python3
"""
投篮坐标补爬（ESPN 第三数据源）—— 探针 / 入库 脚本
====================================================

背景:
  play_by_play 中真实坐标 (x,y) 来自 cdn.nba.com 的逐回合 JSON(仅近期场)。
  basketball-reference 文字 PBP 天生无坐标;本脚本引入 **ESPN Site API v2** 作为
  第三数据源,专门补 cdn.nba.com 补不到的老场坐标缺口(2003 至今,season=None 等)。

  实测结论(2026-07-13):
   - ESPN CDN 端点(cdn.espn.com/.../playbyplay)已失效,返回 HTML 反爬页。
   - ESPN Site API v2 summary 可用且**每个 play 带 coordinate**,投篮事件坐标为真值。
   - 历史回溯:2003 / 2010 全有坐标;2001 个别场空;1999 经 scoreboard 无数据。
   - 坐标系(本版返回): x∈[0,50](边线→边线,中线=25), y∈[0,47](底线→半场线),
     单位为**英尺**。引擎期望 raw 空间 x∈[-250,250]、y∈[0,940](全场,英尺×10)。
     转换: x=(espn_x-25)*10 ; y=espn_y*10 (引擎 _fold_half 会按就近底线折叠,篮筐恒在底部)。

两种模式:
  --probe   只探测可达性,不写库。报告每场 ESPN 映射 / HTTP / 投篮坐标覆盖。
  --apply   映射成功且 summary 含真实投篮坐标的场次,REPLACE 写回 play_by_play。
             执行前在 pbp_backup_espn/ 留 CSV 备份,再 DELETE 该场旧行→INSERT ESPN 版本。
             source 标 'ESPN'（需同步把动画下拉过滤加上 'ESPN',见 backend/.../db.py）。

gameId 映射(无现成 ESPN id):
  dim_games(game_date, home_team_abbr, away_team_abbr)
   → scoreboard ?dates=YYYYMMDD → 按 {主,客} ESPN 缩写 pair(无序)匹配 event id。
  ESPN 缩写与我们 tricode 不完全一致(NY≠NYK, GS≠GSW, SA≠SAS, NO≠NOP,
  PHX≠PHO, WSH≠WAS, CHA≠CHO),故建 OUR_TO_ESPN / ESPN_TO_OUR 双向静态映射。

限速: 默认 1.0s/请求(ESPN 非 Akamai,普通 requests + UA/Referer 即可 200)。
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import psycopg2

DB_CONFIG = dict(host="localhost", port=5433, dbname="nba", user="postgres", password=os.environ.get("DB_PASSWORD"))

# ── ESPN 端点 ───────────────────────────────────────────────────────────────
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={eid}"
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={ymd}"
HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.espn.com/",
    "Accept": "application/json, text/plain, */*",
}

RATE_LIMIT = 1.0
_SENTINEL = 2_000_000_000  # ESPN 哨兵坐标阈值(|x|/|y| 超此即无效占位)

_PROJ = Path(__file__).resolve().parent
# 确保项目根在 sys.path（脚本直跑时 sys.path[0]=本目录, 需把根目录加回,
# 才能 import raw_archiver / common.bridge_constants 复用归档逻辑）
_PROJROOT = str(_PROJ.parent.parent)
if _PROJROOT not in sys.path:
    sys.path.insert(0, _PROJROOT)
_BACKUP = _PROJ.parent.parent / "pbp_backup_espn"  # external_crawler/pbp_backup_espn

# ── 球队缩写双向映射(我们的 tricode <-> ESPN abbr) ──────────────────────────
# 仅列"不一致"的;其余 1:1 的走默认(原样)。
_OUR_TO_ESPN_MAP = {
    "NYK": "NY", "GSW": "GS", "NOP": "NO", "SAS": "SA",
    "PHO": "PHX", "WAS": "WSH", "CHO": "CHA", "BRK": "BKN", "UTA": "UTAH",
}
_ESPN_TO_OUR_MAP = {v: k for k, v in _OUR_TO_ESPN_MAP.items()}


def our_to_espn(abbr: str | None) -> str | None:
    if not abbr:
        return None
    return _OUR_TO_ESPN_MAP.get(abbr, abbr)


def espn_to_our(abbr: str | None) -> str | None:
    if not abbr:
        return None
    return _ESPN_TO_OUR_MAP.get(abbr, abbr)


def espn_to_raw(epx, epy):
    """ESPN 英尺坐标 → 引擎 raw 空间(x∈[-250,250], y∈[0,470])。"""
    try:
        x = (float(epx) - 25.0) * 10.0
        y = float(epy) * 10.0
    except (TypeError, ValueError):
        return None, None
    # 防御: 任何越 int32 范围的值都作废(哨兵坐标 ≈2e9 经 ×10 后会爆)
    if abs(x) > 2_000_000_000 or abs(y) > 2_000_000_000:
        return None, None
    return x, y


def _is_real_coord(c) -> bool:
    if not isinstance(c, dict):
        return False
    x, y = c.get("x"), c.get("y")
    if x is None or y is None:
        return False
    try:
        fx, fy = float(x), float(y)
    except (TypeError, ValueError):
        return False
    # ESPN 真实坐标单位为英尺: x∈[0,50] y∈[0,47]。占位哨兵常≈2e9,
    # 用宽松上限 200 一并剔除(避免 ×10 后撑爆 int32)。
    if abs(fx) > 200 or abs(fy) > 200:
        return False
    return True


# ── DB: 待补场次(完全无真实坐标) ─────────────────────────────────────────
def missing_games(conn, limit=None, seasons=None, none_only=False):
    cur = conn.cursor()
    sql = """
    WITH miss AS (
      SELECT gameid FROM play_by_play
      GROUP BY gameid
      HAVING bool_and(NOT (x IS NOT NULL AND y IS NOT NULL AND (x<>0 OR y<>0)))
    )
    SELECT m.gameid, MAX(p.season),
           MAX(d.game_date), MAX(d.home_team_abbr), MAX(d.away_team_abbr)
    FROM miss m
    JOIN play_by_play p ON p.gameid = m.gameid
    LEFT JOIN dim_games d ON d.game_id = m.gameid
    GROUP BY m.gameid
    """
    if seasons:
        sql += " HAVING MAX(p.season) = ANY(%s)" % ("%s",)
    elif none_only:
        sql += " HAVING MAX(p.season) IS NULL"
    sql += " ORDER BY 3 NULLS LAST, 1"
    cur.execute(sql, (list(seasons),) if seasons else None)
    rows = cur.fetchall()
    if limit:
        rows = rows[:limit]
    return rows


# ── ESPN event id 映射(按日期+主客队) ──────────────────────────────────
_scoreboard_cache: dict = {}


def espn_event_id(conn, gameid, gdate, home, away):
    if not gdate:
        return None
    ymd = gdate.strftime("%Y%m%d")
    if ymd not in _scoreboard_cache:
        try:
            import requests
            r = requests.get(SCOREBOARD.format(ymd=ymd), headers=HDR, timeout=25)
            _scoreboard_cache[ymd] = r.json() if r.status_code == 200 else {}
        except Exception:
            _scoreboard_cache[ymd] = {}
    sb = _scoreboard_cache[ymd]
    events = (sb or {}).get("events", [])
    want = {our_to_espn(home), our_to_espn(away)}
    if None in want:
        return None
    for e in events:
        comps = e.get("competitions", [{}])[0].get("competitors", [])
        got = {c.get("team", {}).get("abbreviation") for c in comps}
        if want.issubset(got) or got == want:
            return e.get("id")
    return None


def _wait(last):
    el = time.time() - last
    if el < RATE_LIMIT:
        time.sleep(RATE_LIMIT - el + random.uniform(0, 0.2))
    return time.time()


def fetch_summary(eid: str, gdate=None):
    import requests
    r = requests.get(SUMMARY.format(eid=eid), headers=HDR, timeout=25)
    if r.status_code != 200:
        return r.status_code, 0, None
    try:
        d = r.json()
    except Exception:
        return 200, 0, None
    # 落盘原始 summary JSON（与 espn_broad_crawler 共享 raw_archiver 归档逻辑;
    # 原子写 + 去重, 路径严格 raw_archive/espn/{date}/{event}.json）。
    if gdate is not None:
        try:
            import raw_archiver
            date_str = gdate.isoformat() if hasattr(gdate, "isoformat") else str(gdate)
            raw_archiver.save_espn_json(date_str, eid, r.text)
        except Exception as _e:  # 归档失败不阻断坐标回填
            print(f"  ! 归档 ESPN JSON 失败 {eid}: {_e}")
    plays = d.get("plays") or []
    return 200, len(plays), plays


def build_rows(gameid, season, plays):
    """从 ESPN plays 构造 play_by_play 行(仅投篮带真实坐标,其余 x/y=NULL)。"""
    ins = []
    for i, p in enumerate(plays, start=1):
        if not isinstance(p, dict):
            continue
        c = p.get("coordinate")
        real = _is_real_coord(c)
        if real:
            x, y = espn_to_raw(c.get("x"), c.get("y"))
        else:
            x = y = None
        # 球队缩写统一回我们的 tricode,保持与全表一致(动画队色 lookup)
        tm_abbr = espn_to_our((p.get("team") or {}).get("abbreviation")) if p.get("team") else None
        # 球员
        ath = (p.get("athletes") or [])
        player_name = None
        if ath:
            player_name = ath[0].get("athlete", {}).get("displayName")
        # 时钟
        clk = (p.get("clock") or {}).get("displayValue")
        period = (p.get("period") or {}).get("number")
        ins.append({
            "gameid": gameid, "season": season,
            "eventnum": i,
            "period": period,
            "clock": clk,
            "clock_seconds": _clock_seconds(period, clk),
            "h_pts": _i(p.get("homeScore")), "a_pts": _i(p.get("awayScore")),
            "team": tm_abbr,
            "playerid": None,  # ESPN 数字 athlete id 与本项目 personId 不同源,不混入
            "player": player_name,
            "event_type": (p.get("type") or {}).get("text"),
            "subtype": None,
            "result": _make_miss(p.get("text")),
            "x": x, "y": y, "dist": None,
            "description": p.get("text"),
            "current_team": tm_abbr,
            "source": "ESPN",
        })
    return ins


def _make_miss(text):
    t = (text or "").lower()
    # ESPN plays[].text 以球员名开头(如 "Chet Holmgren makes 1-foot layup"),
    # 故不能用 startswith；用子串 "makes" in t 正确区分命中/未中
    # ("misses" 不含 "makes"；不用 "make" in t 以免误命中 "makeup" 之类)。
    if "makes" in t:
        return "make"
    if t.startswith("misses") or t.startswith("miss"):
        return "miss"
    return ""


def _clock_seconds(period, clk):
    if not clk or not isinstance(clk, str):
        return None
    m = re.match(r"(\d+):(\d+)", clk)
    if not m:
        return None
    rem = int(m.group(1)) * 60 + int(m.group(2))
    plen = 300 if (period or 0) > 4 else 720
    return (period - 1) * 720 + (plen - rem)


def probe(conn, rows):
    last = 0.0
    mapped = nomap = ok = nocoord = fail = 0
    print(f"{'gameid':14} {'season':8} {'date':12} {'ESPN_id':12} {'HTTP':5} {'plays':6} {'shots':6}")
    for gameid, season, gdate, home, away in rows:
        eid = espn_event_id(conn, gameid, gdate, home, away)
        if not eid:
            print(f"{gameid:14} {str(season):8} {str(gdate):12} {'--':12} SKIP  no-espn-id")
            nomap += 1
            continue
        last = _wait(last)
        sc, na, plays = fetch_summary(eid, gdate)
        if sc != 200 or not plays:
            print(f"{gameid:14} {str(season):8} {str(gdate):12} {str(eid):12} {sc:<5} {na:<6} -")
            fail += 1
            continue
        shots = [p for p in plays if isinstance(p, dict) and p.get("shootingPlay")
                 and _is_real_coord(p.get("coordinate"))]
        tag = "OK" if shots else "no-coord"
        if shots:
            ok += 1
        else:
            nocoord += 1
        print(f"{gameid:14} {str(season):8} {str(gdate):12} {str(eid):12} {sc:<5} {na:<6} {len(shots):<6}")
    print(f"\n探针汇总: 映射成功={mapped+ok}  无映射={nomap}  "
          f"可补(真实坐标)={ok}  无坐标={nocoord}  抓取失败={fail}")


def apply(conn, rows):
    _BACKUP.mkdir(parents=True, exist_ok=True)
    cur = conn.cursor()
    last = 0.0
    done = skip = fail = 0
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for gameid, season, gdate, home, away in rows:
        eid = espn_event_id(conn, gameid, gdate, home, away)
        if not eid:
            skip += 1
            continue
        last = _wait(last)
        sc, na, plays = fetch_summary(eid, gdate)
        if sc != 200 or not plays:
            skip += 1
            continue
        try:
            ins = build_rows(gameid, season, plays)
            real = sum(1 for r in ins if r["x"] is not None)
            if not ins or real == 0:
                skip += 1
                continue
            # 备份现有行
            cur.execute("SELECT * FROM play_by_play WHERE gameid=%s", (gameid,))
            cols = [d[0] for d in cur.description]
            exist = cur.fetchall()
            bk = _BACKUP / f"{gameid}_{ts}.csv"
            with bk.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(cols)
                for row in exist:
                    w.writerow(row)
            # REPLACE
            cur.execute("DELETE FROM play_by_play WHERE gameid=%s", (gameid,))
            from psycopg2.extras import execute_batch
            execute_batch(
                cur,
                "INSERT INTO play_by_play "
                "(gameid,season,eventnum,period,clock,clock_seconds,h_pts,a_pts,team,playerid,player,"
                "event_type,subtype,result,x,y,dist,description,current_team,source) "
                "VALUES (%(gameid)s,%(season)s,%(eventnum)s,%(period)s,%(clock)s,%(clock_seconds)s,"
                "%(h_pts)s,%(a_pts)s,%(team)s,%(playerid)s,%(player)s,%(event_type)s,%(subtype)s,"
                "%(result)s,%(x)s,%(y)s,%(dist)s,%(description)s,%(current_team)s,%(source)s)",
                ins, page_size=200,
            )
            conn.commit()
            done += 1
            print(f"  {gameid}: 补 {len(ins)} 行(真实坐标 {real}) 备份 {bk.name}")
        except Exception as e:
            conn.rollback()
            fail += 1
            print(f"  {gameid}: ERROR {e!r} 已回滚,跳过")
            continue
    print(f"\n入库汇总: 补坐标={done}  跳过={skip}  失败={fail}")


def _i(v):
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="只探测可达性,不写库")
    ap.add_argument("--apply", action="store_true", help="映射成功且含真实坐标则写回")
    ap.add_argument("--limit", type=int, default=None, help="最多处理多少场(默认不限)")
    ap.add_argument("--seasons", type=int, nargs="*", help="限定赛季,如 --seasons 2024 2026")
    ap.add_argument("--season-none", action="store_true", help="仅处理 season=NULL 的缺口场(主力:5,882 场 2011 时代)")
    args = ap.parse_args()
    if not (args.probe or args.apply):
        ap.error("需指定 --probe 或 --apply")
    conn = psycopg2.connect(**DB_CONFIG)
    rows = missing_games(conn, limit=args.limit, seasons=args.seasons, none_only=args.season_none)
    print(f"待处理(完全无坐标)场次: {len(rows)}")
    if args.probe:
        probe(conn, rows)
    else:
        apply(conn, rows)
    conn.close()


if __name__ == "__main__":
    main()
