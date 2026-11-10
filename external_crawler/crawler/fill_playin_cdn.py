#!/usr/bin/env python3
"""补齐 Play-In(附加赛) 球员数据到 player_gamelog (2023-2026 缺失场)。

数据源: cdn.nba.com boxscore JSON (无需 CDP/代理, NBA-API 10位ID)。
- 有 nba_api_id 的比赛: 直接用它。
- nba_api_id 为 NULL 的比赛(2023 全部 / 2024 PHI): 用 Play-In ID 规律猜解
  (005{YY}00101/00111/00121/00131/00201/00211) 并按 日期+主客队 匹配 games 行。
新行 game_id_full/gameid 用 NBA-API 8/10位 (与现有 349 行一致), game_type='play_in'。
回滚: 记录所有新 game_id_full, 如需回退 DELETE WHERE game_id_full IN (...)。
"""
import json
import os
import random
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
# 去掉可能干扰的代理
for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
from datetime import datetime
from pathlib import Path

import psycopg2
from curl_cffi import requests
from psycopg2.extras import execute_batch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.nba_paths import REPO_ROOT

ROOT = str(REPO_ROOT)
PW = "R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1"
DB = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres", password=PW)
CDN = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
HDR = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
       "Referer":"https://www.nba.com/"}
RATE = 1.2  # 秒
_last = 0.0

def wait():
    global _last
    e = time.time() - _last
    if e < RATE: time.sleep(RATE - e + random.uniform(0,0.2))
    _last = time.time()

def fetch(gid10):
    for a in range(3):
        try:
            wait()
            r = requests.get(CDN.format(gid=gid10), headers=HDR, timeout=20, impersonate="chrome124")
            if r.status_code == 200: return r.json()
            if r.status_code == 404: return None
            if r.status_code == 403 and a < 2:
                time.sleep(3*(2**a)+random.uniform(0,2)); continue
        except Exception as e:
            print(f"  fetch err {gid10}: {e}")
            if a < 2: time.sleep(2**a)
    return None

def mins_to_str(s):
    if not s: return None
    if s.startswith("PT"):
        s = s[2:]; m=0; sec=0
        if "M" in s:
            p = s.split("M"); m=int(p[0]); sec=float(p[1].replace("S",""))
        else:
            sec=float(s.replace("S",""))
        return f"{m:02d}:{int(sec):02d}"
    return s

def parse(gid10, data, br_gid, season):
    g = data.get("game", {})
    if g.get("gameStatus") != 3: return None
    rows = []
    for team, is_home in [(g.get("homeTeam",{}), True), (g.get("awayTeam",{}), False)]:
        abbr = team.get("teamTricode","")
        tid = str(team.get("teamId",""))
        for p in team.get("players", []):
            st = p.get("statistics", {})
            nm = p.get("name","")
            if not nm: continue
            pts = st.get("points")
            if pts is None: continue
            rows.append({
                "game_id_full": gid10, "gameid": gid10, "player": nm, "player_name": nm,
                "team": abbr, "team_abbreviation": abbr, "season": season,
                "fg": st.get("fieldGoalsMade"), "fga": st.get("fieldGoalsAttempted"),
                "fg3": st.get("threePointersMade"), "fga3": st.get("threePointersAttempted"),
                "ft": st.get("freeThrowsMade"), "fta": st.get("freeThrowsAttempted"),
                "orb": st.get("reboundsOffensive"), "drb": st.get("reboundsDefensive"),
                "trb": st.get("reboundsTotal"), "ast": st.get("assists"), "stl": st.get("steals"),
                "blk": st.get("blocks"), "tov": st.get("turnovers"), "pf": st.get("foulsPersonal"),
                "pts": pts, "plus_minus": st.get("plusMinusPoints"),
                "fg_pct": round(st["fieldGoalsMade"]/st["fieldGoalsAttempted"],3) if st.get("fieldGoalsAttempted") else 0.0,
                "ft_pct": round(st["freeThrowsMade"]/st["freeThrowsAttempted"],3) if st.get("freeThrowsAttempted") else 0.0,
                "fg3_pct": round(st["threePointersMade"]/st["threePointersAttempted"],3) if st.get("threePointersAttempted") else 0.0,
                "nba_player_id": int(p.get("personId",0)) or None, "team_id": tid,
                "start_position": p.get("position","") if p.get("starter")=="1" else "",
                "minutes": mins_to_str(st.get("minutes","")), "jersey_num": p.get("jerseyNum"),
                "position": p.get("position"), "player_status": (p.get("status","") or "")[:5],
                "banned": False, "game_type": "play_in",
            })
    return rows

def main():
    conn = psycopg2.connect(**DB); cur = conn.cursor()
    # 目标: 2023/2024/2026 Play-In, 且 player_gamelog 尚无 play_in 行
    cur.execute("""
        SELECT g.game_id, g.nba_api_id, g.season, g.game_date, g.home_team_abbr, g.away_team_abbr
        FROM games g
        WHERE g.season_type='Play-In' AND g.season IN (2023,2024,2026)
          AND NOT EXISTS (SELECT 1 FROM player_gamelog pl WHERE pl.game_id_full = COALESCE(g.nba_api_id::text, g.game_id) AND pl.game_type='play_in')
        ORDER BY g.season, g.game_id
    """)
    targets = cur.fetchall()
    print(f"目标缺失 Play-In 比赛: {len(targets)} 场")

    # 预取候选 ID (nba_api_id 为 NULL 的赛季)
    cand_cache = {}
    for br_gid, nba_id, season, gdate, ha, aa in targets:
        if nba_id is not None: continue
        yy = (season - 1) % 100
        for seq in ("00101","00111","00121","00131","00201","00211"):
            cid = f"005{yy}{seq}"
            if cid in cand_cache: continue
            d = fetch(cid)
            if not d: cand_cache[cid] = None; continue
            gg = d.get("game", {})
            if gg.get("gameStatus") != 3: cand_cache[cid] = None; continue
            gd = (gg.get("gameEt") or "")[:10]
            at = gg.get("awayTeam",{}).get("teamTricode")
            ht = gg.get("homeTeam",{}).get("teamTricode")
            cand_cache[cid] = (gd, at, ht)
            print(f"  candidate {cid}: {at}@{ht} {gd}")

    all_rows = []
    new_gids = []
    ok = skip = fail = 0
    for br_gid, nba_id, season, gdate, ha, aa in targets:
        # 决定 CDN 10位
        if nba_id is not None:
            gid10 = str(nba_id).zfill(10)
        else:
            gid10 = None
            for cid, info in cand_cache.items():
                if info and info[0] == str(gdate) and info[1] == aa and info[2] == ha:
                    gid10 = cid; break
            if gid10 is None:
                print(f"  SKIP {br_gid}: 无匹配候选 ID"); skip += 1; continue
        data = fetch(gid10)
        if not data:
            print(f"  FAIL {gid10} ({br_gid}): 无数据"); fail += 1; continue
        rows = parse(gid10, data, br_gid, season)
        if not rows:
            print(f"  SKIP {gid10}: 非终场/无球员"); skip += 1; continue
        # 校验赛季/球队一致性
        all_rows.extend(rows)
        new_gids.append(gid10)
        ok += 1
        print(f"  OK {gid10} ({br_gid}) season={season}: {len(rows)} 球员")

    if all_rows:
        sql = """INSERT INTO player_gamelog (
            game_id_full, gameid, player, player_name, team, team_abbreviation, season,
            fg, fga, fg3, fga3, ft, fta, orb, drb, trb, ast, stl, blk, tov, pf, pts, plus_minus,
            fg_pct, ft_pct, fg3_pct, nba_player_id, team_id, start_position, minutes, jersey_num, position, player_status,
            banned, game_type) VALUES (
            %(game_id_full)s, %(gameid)s, %(player)s, %(player_name)s, %(team)s, %(team_abbreviation)s, %(season)s,
            %(fg)s, %(fga)s, %(fg3)s, %(fga3)s, %(ft)s, %(fta)s, %(orb)s, %(drb)s, %(trb)s, %(ast)s, %(stl)s, %(blk)s, %(tov)s, %(pf)s, %(pts)s, %(plus_minus)s,
            %(fg_pct)s, %(ft_pct)s, %(fg3_pct)s, %(nba_player_id)s, %(team_id)s, %(start_position)s, %(minutes)s, %(jersey_num)s, %(position)s, %(player_status)s,
            %(banned)s, %(game_type)s)"""
        execute_batch(cur, sql, all_rows, page_size=100)
        conn.commit()
        # 记录回滚清单
        with open(os.path.join(ROOT, "external_crawler/crawler/playin_cdn_new_gids_20260817.txt"), "w") as f:
            f.write("\n".join(sorted(set(new_gids))))
        print(f"\nINSERT {len(all_rows)} 行 / {len(set(new_gids))} 场比赛")
        print(f"OK={ok} SKIP={skip} FAIL={fail}")
        print("回滚清单: playin_cdn_new_gids_20260817.txt")
    else:
        print("无新数据写入")
    conn.close()

if __name__ == "__main__":
    main()
