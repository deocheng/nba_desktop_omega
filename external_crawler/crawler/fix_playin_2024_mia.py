#!/usr/bin/env python3
"""修正 2024-04-19 MIA@CHI 这场 Play-In: 之前仅从 player_game_details 转入 6 行(不完整),
CDN 补爬时被 NOT EXISTS 跳过。现用 cdn.nba.com boxscore(0052300201) 全量替换。
可回滚: 先备 6 行到 backup 表, 再 DELETE + INSERT 全量。"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.nba_paths import REPO_ROOT

sys.stdout.reconfigure(encoding="utf-8")
for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
import psycopg2
from curl_cffi import requests
from psycopg2.extras import execute_batch

ROOT = str(REPO_ROOT)
PW = "R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1"
DB = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres", password=PW)
CDN = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
HDR = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
       "Referer":"https://www.nba.com/"}
GID10 = "0052300201"   # 2024-04-19 MIA@CHI (round2)
OLD_GID = "52300201"   # 旧的不完整 8位键

def fetch(gid10):
    for a in range(3):
        try:
            time.sleep(1.0 + (a*0.3))
            r = requests.get(CDN.format(gid=gid10), headers=HDR, timeout=20, impersonate="chrome124")
            if r.status_code == 200: return r.json()
            if r.status_code == 404: return None
        except Exception as e:
            print(f"  fetch err {gid10}: {e}"); time.sleep(2**a)
    return None

def mins_to_str(s):
    if not s: return None
    if s.startswith("PT"):
        s = s[2:]; m=0; sec=0
        if "M" in s:
            p=s.split("M"); m=int(p[0]); sec=float(p[1].replace("S",""))
        else: sec=float(s.replace("S",""))
        return f"{m:02d}:{int(sec):02d}"
    return s

def parse(gid10, data, season):
    g = data.get("game", {})
    if g.get("gameStatus") != 3: return None, None, None
    gd = (g.get("gameEt") or "")[:10]
    at = g.get("awayTeam",{}).get("teamTricode"); ht = g.get("homeTeam",{}).get("teamTricode")
    rows = []
    for team, is_home in [(g.get("homeTeam",{}), True), (g.get("awayTeam",{}), False)]:
        abbr = team.get("teamTricode",""); tid=str(team.get("teamId",""))
        for p in team.get("players", []):
            st = p.get("statistics", {}); nm = p.get("name","")
            if not nm: continue
            pts = st.get("points")
            if pts is None: continue
            rows.append({"game_id_full": gid10, "gameid": gid10, "player": nm, "player_name": nm,
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
                "banned": False, "game_type": "play_in"})
    return rows, gd, (at, ht)

def main():
    conn = psycopg2.connect(**DB); cur = conn.cursor()
    # 0) 备份旧 6 行
    cur.execute("DROP TABLE IF EXISTS player_gamelog_playin_2024mia_bak_20260817")
    cur.execute(f"CREATE TABLE player_gamelog_playin_2024mia_bak_20260817 AS SELECT * FROM player_gamelog WHERE game_id_full='{OLD_GID}'")
    cur.execute(f"SELECT COUNT(*) FROM player_gamelog WHERE game_id_full='{OLD_GID}'")
    old_n = cur.fetchone()[0]
    print(f"备份旧行: {old_n} 行 -> player_gamelog_playin_2024mia_bak_20260817")

    # 1) 拉取 CDN
    data = fetch(GID10)
    if not data:
        print(f"FAIL: 无法获取 {GID10}"); conn.close(); return
    rows, gd, (at, ht) = parse(GID10, data, 2024)
    if not rows:
        print(f"FAIL: {GID10} 无终场/无球员"); conn.close(); return
    print(f"CDN {GID10}: date={gd} {at}@{ht} players={len(rows)}")

    # 2) 一致性校验: 应为 2024-04-19 MIA(home)@CHI(away)
    if gd != "2024-04-19":
        print(f"日期不符 {gd} != 2024-04-19, 中止"); conn.close(); return
    if (at, ht) not in (("CHI","MIA"), ("MIA","CHI")):
        print(f"球队不符 ({at}@{ht}), 中止"); conn.close(); return

    # 3) 删除旧 6 行 + 插入全量
    cur.execute(f"DELETE FROM player_gamelog WHERE game_id_full='{OLD_GID}'")
    cur.execute(f"DELETE FROM player_gamelog WHERE game_id_full='{GID10}'")  # 防御重复
    sql = """INSERT INTO player_gamelog (
        game_id_full, gameid, player, player_name, team, team_abbreviation, season,
        fg, fga, fg3, fga3, ft, fta, orb, drb, trb, ast, stl, blk, tov, pf, pts, plus_minus,
        fg_pct, ft_pct, fg3_pct, nba_player_id, team_id, start_position, minutes, jersey_num, position, player_status,
        banned, game_type) VALUES (
        %(game_id_full)s, %(gameid)s, %(player)s, %(player_name)s, %(team)s, %(team_abbreviation)s, %(season)s,
        %(fg)s, %(fga)s, %(fg3)s, %(fga3)s, %(ft)s, %(fta)s, %(orb)s, %(drb)s, %(trb)s, %(ast)s, %(stl)s, %(blk)s, %(tov)s, %(pf)s, %(pts)s, %(plus_minus)s,
        %(fg_pct)s, %(ft_pct)s, %(fg3_pct)s, %(nba_player_id)s, %(team_id)s, %(start_position)s, %(minutes)s, %(jersey_num)s, %(position)s, %(player_status)s,
        %(banned)s, %(game_type)s)"""
    execute_batch(cur, sql, rows, page_size=100)
    # 4) 更新 playin_game_dates 该场 (改 game_id_full 键)
    cur.execute("""UPDATE playin_game_dates SET game_id_full=%s, nba_api_id=%s, player_count=%s
                   WHERE br_game_id='202404190MIA'""", (GID10, 52300201, len(rows)))
    conn.commit()
    print(f"DELETE 旧 {old_n} 行, INSERT 全量 {len(rows)} 行, playin_game_dates 已更新")
    conn.close()

if __name__ == "__main__":
    main()
