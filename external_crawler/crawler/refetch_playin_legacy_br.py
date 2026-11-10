#!/usr/bin/env python3
"""用 BR boxscore (CDP, 已带 cf_clearance) 重抓 2020-2022 共13场 Play-In, 替换 player_gamelog 中
349 行统计全零的占位壳(legacy 8位 key)。

步骤(可回滚):
 0) 备 player_gamelog_playin_legacy_bak_20260817 (349 行)
 1) 逐场抓 BR boxscore, 解析完整统计(fg/fga/pts/.../minutes)
 2) DELETE 旧 2020-2022 play_in 行 + INSERT BR 全量
 3) 归一 playin_game_dates 主客队缩写为 NBA 三位码(CHO->CHA, BRK->BKN) 保持一致
team 缩写 BR->NBA: CHO=CHA, BRK=BKN; 其余相同。
"""
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
import psycopg2
from psycopg2.extras import execute_batch

sys.path.insert(0, os.path.dirname(__file__))
from xcheck_playin_br import CDPClient

ROOT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
PW = "R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1"
DB = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres", password=PW)
RATE = 1.5
BR2NBA = {"CHO": "CHA", "BRK": "BKN"}

STATS = ["mp","fg","fga","fg3","fg3a","ft","fta","orb","drb","trb","ast","stl","blk","tov","pf","pts","plus_minus","fg_pct","ft_pct","fg3_pct"]

def to_int(v):
    v = (v or "").strip()
    if v in ("", "-", None): return None
    try: return int(v)
    except: return None

def to_pct(v):
    v = (v or "").strip()
    if v in ("", "-", None): return None
    try: return round(float(v), 3)
    except: return None

def parse_full(html, season, game_id_full):
    out = []
    for m in re.finditer(r'<table[^>]*id="box-([A-Za-z]+)-game-basic"[^>]*>.*?</table>', html, re.S):
        abbr = m.group(1).upper()
        team = BR2NBA.get(abbr, abbr)
        t = m.group(0)
        for row in re.finditer(r'<tr[^>]*data-row="\d+"[^>]*>.*?</tr>', t, re.S):
            r = row.group(0)
            if "Team Totals" in r: continue
            if not re.search(r'data-stat="pts"', r): continue  # DNP/Inactive
            d = {}
            for s in STATS:
                mm = re.search(r'data-stat="%s"[^>]*>([^<]*)<' % s, r)
                d[s] = mm.group(1).strip() if mm else ""
            nm = re.search(r'data-stat="player"[^>]*>(?:<a[^>]*>)?([^<]+)', r)
            name = nm.group(1).strip() if nm else ""
            if not name: continue
            out.append({
                "game_id_full": game_id_full, "gameid": game_id_full,
                "player": name, "player_name": name,
                "team": team, "team_abbreviation": team, "season": season,
                "fg": to_int(d["fg"]), "fga": to_int(d["fga"]),
                "fg3": to_int(d["fg3"]), "fga3": to_int(d["fg3a"]),
                "ft": to_int(d["ft"]), "fta": to_int(d["fta"]),
                "orb": to_int(d["orb"]), "drb": to_int(d["drb"]), "trb": to_int(d["trb"]),
                "ast": to_int(d["ast"]), "stl": to_int(d["stl"]), "blk": to_int(d["blk"]),
                "tov": to_int(d["tov"]), "pf": to_int(d["pf"]), "pts": to_int(d["pts"]),
                "plus_minus": to_int(d["plus_minus"].replace("+","")) if d["plus_minus"] else None,
                "fg_pct": to_pct(d["fg_pct"]), "ft_pct": to_pct(d["ft_pct"]), "fg3_pct": to_pct(d["fg3_pct"]),
                "nba_player_id": None, "team_id": None,
                "start_position": "", "minutes": d["mp"] or None, "jersey_num": None,
                "position": None, "player_status": "", "banned": False, "game_type": "play_in",
            })
    return out

def main():
    conn = psycopg2.connect(**DB); cur = conn.cursor()
    cur.execute("SELECT game_id_full, br_game_id, season FROM playin_game_dates WHERE season IN (2020,2021,2022) ORDER BY season, br_game_id")
    games = cur.fetchall()

    # 0) 备份
    cur.execute("DROP TABLE IF EXISTS player_gamelog_playin_legacy_bak_20260817")
    cur.execute("CREATE TABLE player_gamelog_playin_legacy_bak_20260817 AS SELECT * FROM player_gamelog WHERE game_type='play_in' AND season IN (2020,2021,2022)")
    cur.execute("SELECT COUNT(*) FROM player_gamelog_playin_legacy_bak_20260817")
    bak_n = cur.fetchone()[0]
    print(f"备份旧 2020-2022 行: {bak_n} -> player_gamelog_playin_legacy_bak_20260817")

    cli = CDPClient()
    all_rows = []
    ok = fail = 0
    for gid_full, br_gid, season in games:
        url = f"https://www.basketball-reference.com/boxscores/{br_gid}.html"
        html = cli.fetch(url)
        rows = parse_full(html, season, gid_full)
        if not rows:
            print(f"  FAIL {br_gid}: 无球员"); fail += 1; continue
        all_rows.extend(rows); ok += 1
        print(f"  OK {br_gid} ({gid_full}) season={season}: {len(rows)} 球员")
        time.sleep(RATE)
    cli.close()

    if not all_rows:
        print("无新数据"); conn.close(); return

    # 2) 删旧 + 写新
    cur.execute("DELETE FROM player_gamelog WHERE game_type='play_in' AND season IN (2020,2021,2022)")
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
    # 3) 归一 playin_game_dates 缩写
    for br, nba in BR2NBA.items():
        cur.execute(f"UPDATE playin_game_dates SET home_team_abbr='{nba}' WHERE home_team_abbr='{br}'")
        cur.execute(f"UPDATE playin_game_dates SET away_team_abbr='{nba}' WHERE away_team_abbr='{br}'")
    conn.commit()
    print(f"\nDELETE 旧 {bak_n} 行, INSERT 新 {len(all_rows)} 行; OK={ok} FAIL={fail}")
    print("playin_game_dates 缩写已归一(CHO->CHA, BRK->BKN)")
    conn.close()

if __name__ == "__main__":
    main()
