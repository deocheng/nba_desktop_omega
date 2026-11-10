#!/usr/bin/env python3
"""交叉校验: 用 BR boxscore (CDP, 已带 cf_clearance) 校验 player_gamelog 现有 Play-In(CDN) 数据。
对每个 Play-In 场:
  - BR: 解析 basic box score 两队的 Team Totals PTS + 球员行数
  - DB: player_gamelog(game_type='play_in') 该场各队 SUM(pts) + COUNT(*)
输出差异报告 backups/playin_br_xcheck_20260817.csv + 汇总。
复用单个 CDP 标签页(导航式), BR 间隔 1.5s。"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import websocket

sys.stdout.reconfigure(encoding="utf-8")
import psycopg2

ROOT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
PW = "R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1"
DB = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres", password=PW)
CDP = "http://127.0.0.1:9223"
RATE = 3.5
BR2NBA = {"CHO": "CHA", "BRK": "BKN"}
NBA2BR = {"CHA": "CHO", "BKN": "BRK"}  # URL 用 BR 缩写

def ws_of_first_page():
    with urllib.request.urlopen(f"{CDP}/json/list", timeout=5) as r:
        tabs = [t for t in json.load(r) if t.get("type") == "page"]
    return tabs[0]["webSocketDebuggerUrl"]

class CDPClient:
    def __init__(self):
        self.sock = websocket.create_connection(ws_of_first_page(), timeout=40)
        self._id = 0
        self.send("Page.enable"); self.send("Runtime.enable")
    def send(self, method, params=None):
        self._id += 1
        self.sock.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        return self._id
    def recv_id(self, want):
        while True:
            msg = json.loads(self.sock.recv())
            if msg.get("id") == want:
                return msg
    def fetch(self, url, wait=4.0):
        for attempt in range(2):
            nid = self.send("Page.navigate", {"url": url}); self.recv_id(nid)
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    self.sock.settimeout(2)
                    m = json.loads(self.sock.recv())
                    if m.get("method") == "Page.loadEventFired":
                        break
                except Exception:
                    continue
            time.sleep(wait)
            eid = self.send("Runtime.evaluate",
                            {"expression": "document.documentElement.outerHTML", "returnByValue": True})
            res = self.recv_id(eid)
            html = res.get("result", {}).get("result", {}).get("value", "")
            low = html.lower()
            if "just a moment" in low or "attention required" in low or len(html) < 5000:
                if attempt == 0:
                    time.sleep(3); continue   # CF 瞬时挑战, 重试一次
            return html
        return html
    def close(self):
        try: self.sock.close()
        except: pass

def parse_boxscore(html):
    """返回 {team_abbr: {'pts': int, 'players': int}} 来自 basic box score。
    只取 box-(ABBR)-game-basic 全场比赛表(排除 q1/q2/h1... 分段表)。"""
    out = {}
    for m in re.finditer(r'<table[^>]*id="box-([A-Za-z]+)-game-basic"[^>]*>.*?</table>', html, re.S):
        abbr = BR2NBA.get(m.group(1).upper(), m.group(1).upper())
        if abbr in out: continue
        t = m.group(0)
        # Team Totals PTS (data-stat=pts)
        tt = re.search(r'Team Totals.*?</tr>', t, re.S)
        pts = None
        if tt:
            pm = re.search(r'data-stat="pts"[^>]*>([^<]*)<', tt.group(0))
            if pm and pm.group(1).strip().lstrip('-').isdigit():
                pts = int(pm.group(1))
        # 球员行: 含 data-stat=pts 且非 Team Totals (DNP 行无 pts)
        cnt = 0
        for row in re.finditer(r'<tr[^>]*data-row="\d+"[^>]*>.*?</tr>', t, re.S):
            r = row.group(0)
            if "Team Totals" in r: continue
            if re.search(r'data-stat="pts"', r): cnt += 1
        out[abbr] = {"pts": pts, "players": cnt}
    return out

def main():
    conn = psycopg2.connect(**DB); cur = conn.cursor()
    cur.execute("SELECT game_id_full, br_game_id, home_team_abbr, away_team_abbr FROM playin_game_dates ORDER BY season, game_date, br_game_id")
    games = cur.fetchall()
    # DB 现有 play_in 合计
    gids = tuple(g[0] for g in games)
    cur.execute("""SELECT game_id_full, team_abbreviation, SUM(pts), COUNT(*)
                   FROM player_gamelog WHERE game_type='play_in' AND game_id_full IN %s
                   GROUP BY game_id_full, team_abbreviation""", (gids,))
    db = {}
    for gid, ab, spts, cnt in cur.fetchall():
        db.setdefault(gid, {})[ab] = {"pts": int(spts), "players": int(cnt)}

    cli = CDPClient()
    rows = []
    mism_pt = mism_pl = br_na = 0
    for gid_full, br_gid, ha, aa in games:
        # URL 用 BR 缩写(主队): 202604140CHA -> 202604140CHO
        url_bid = br_gid[:8] + NBA2BR.get(br_gid[8:11], br_gid[8:11])
        url = f"https://www.basketball-reference.com/boxscores/{url_bid}.html"
        html = cli.fetch(url)
        br = parse_boxscore(html)
        if not br:   # BR 404 / 无数据
            br_na += 1
            rows.append((br_gid, ha, None, None, "N", None, None, "N", "BR_NA"))
            rows.append((br_gid, aa, None, None, "N", None, None, "N", "BR_NA"))
            time.sleep(RATE); continue
        d = db.get(gid_full, {})
        for team in (BR2NBA.get(ha, ha), BR2NBA.get(aa, aa)):
            b = br.get(team, {})
            dd = d.get(team, {})
            bpts = b.get("pts"); dpts = dd.get("pts")
            bpl = b.get("players"); dpl = dd.get("players")
            pt_ok = (bpts is not None and dpts is not None and bpts == dpts)
            # 球员数: BR 含 DNP 可能多于 DB; 仅当 DB 明显少于 BR(>2)才标
            pl_flag = (bpl is not None and dpl is not None and (bpl - dpl) > 2)
            status = "OK" if (pt_ok and not pl_flag) else "DIFF"
            if not pt_ok and bpts is not None and dpts is not None: mism_pt += 1
            if pl_flag: mism_pl += 1
            rows.append((br_gid, team, bpts, dpts, "Y" if pt_ok else "N",
                         bpl, dpl, "Y" if pl_flag else "N", status))
        time.sleep(RATE)
    cli.close()

    csv_path = os.path.join(ROOT, "backups/playin_br_xcheck_20260817.csv")
    import csv
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["br_game_id","team","br_pts","db_pts","pts_match","br_players","db_players","players_gt2_diff","status"])
        for r in rows: w.writerow(r)
    print(f"校验 {len(games)} 场 / {len(rows)} 队行")
    print(f"PTS 不符(BR!=DB): {mism_pt}  球员数 DB 明显偏少(>2): {mism_pl}  BR无页面(BR_NA): {br_na}")
    print(f"CSV -> {csv_path}")
    conn.close()

if __name__ == "__main__":
    main()
