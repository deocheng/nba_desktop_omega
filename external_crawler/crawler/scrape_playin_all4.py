#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scrape_playin_all4.py — Play-In 37 场四维补齐（PBP / 投篮图 / 正负值）。

背景（2026-08-17 Phase 0 已完成）：
  * Box Score 已完整（player_gamelog 1071 行 / 37 场）。
  * PBP：play_by_play 0 行 → 全 37 场需爬。
  * 投篮图：player_shot_chart 已有 31 场 season_type='Play-In'（5486 行），
    仅 2026 缺 4 场（202604140PHX/202604140CHA/202604150PHI/202604170PHX）。
  * 正负值：season 聚合表不可用 → 独立表 player_playin_plus_minus 全 37 场。

铁律对齐：
  * 备份：player_gamelog_playin_pm_bak_20260817（1071 行，plus_minus 旧值）。
  * 回滚：scripts/rollback/playin_all4_20260817.json（含全部 DELETE/UPDATE）。
  * 幂等：每场每产品先 DELETE 本场行再 INSERT，可安全重跑。
  * 连接键：play_by_play.gameid = player_gamelog.game_id_full（10/8 位孤儿键）；
    player_shot_chart.game_id = BR 12 位 URL id（与既有 31 场一致）；
    pppm.game_id_full = game_id_full，player_name 连接 player_gamelog。

BR 缩写归一化（URL/BR 侧）：PHX→PHO、CHA→CHO、BKN→BRK。
用法：
  .venv/bin/python external_crawler/crawler/scrape_playin_all4.py --dry-run --game 202404190MIA
  .venv/bin/python external_crawler/crawler/scrape_playin_all4.py --dry-run          # 全部干跑
  .venv/bin/python external_crawler/crawler/scrape_playin_all4.py                    # 全量落库
  ... --only pbp|shots|pm   # 只跑某一产品
"""
import sys, os, re, json, time, csv, urllib.request, urllib.parse, argparse, logging
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
import psycopg2
import br_pbp_parse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("playin_all4")

CDP = "http://127.0.0.1:9223"
CACHE = Path("/tmp/playin_all4_cache")
CACHE.mkdir(parents=True, exist_ok=True)
BASE = "https://www.basketball-reference.com/boxscores"
BR_ABBR = {"PHX": "PHO", "CHA": "CHO", "BKN": "BRK"}  # NBA→BR
NBA_ABBR = {v: k for k, v in BR_ABBR.items()}        # BR→NBA（home_team_abbr 惯例不统一，先归一）
FETCH_SLEEP = 4.6  # ~13 req/min，低于 BR 15/min 上限

# ── CDP 抓取（新 tab 模式，已验证）────────────────────────────────────────
def fetch(url, wait=4.0, retries=2):
    for att in range(retries + 1):
        try:
            req = urllib.request.Request(f"{CDP}/json/new?{urllib.parse.quote(url, safe='')}",
                                         data=b"", method="PUT")
            with urllib.request.urlopen(req, timeout=8) as r:
                tab = json.load(r)
            tab_id = tab["id"]
            import websocket
            ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30)
            _id = 0
            def send(m, p=None):
                nonlocal _id; _id += 1
                ws.send(json.dumps({"id": _id, "method": m, "params": p or {}})); return _id
            def recv_id(w):
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("id") == w: return msg
            send("Page.enable"); send("Runtime.enable"); send("Page.navigate", {"url": url})
            dl = time.time() + 25
            while time.time() < dl:
                try:
                    ws.settimeout(2); msg = json.loads(ws.recv())
                    if msg.get("method") == "Page.loadEventFired": break
                except Exception:
                    continue
            time.sleep(wait)
            eid = send("Runtime.evaluate", {"expression": "document.documentElement.outerHTML",
                                            "returnByValue": True})
            html = recv_id(eid).get("result", {}).get("result", {}).get("value", "")
            ws.close()
            try: urllib.request.urlopen(f"{CDP}/json/close/{tab_id}", timeout=5)
            except Exception: pass
            if len(html) > 5000:
                return html  # 404 页解析器自然得 0 行，由后续校验兜底
        except Exception as e:
            log.warning("  fetch retry %d: %s", att, e); time.sleep(2)
    return ""

def cached_fetch(kind, br_url_id, force=False):
    """kind ∈ {pbp, shot, pm}；磁盘缓存优先，避免重试重复请求。"""
    path = CACHE / f"{kind}_{br_url_id}.html"
    if path.exists() and not force and path.stat().st_size > 50000:
        return path.read_text(encoding="utf-8")
    html = fetch(f"{BASE}/{ {'pbp':'pbp','shot':'shot-chart','pm':'plus-minus','box':''}[kind] }/{br_url_id}.html")
    if html:
        path.write_text(html, encoding="utf-8")
        time.sleep(FETCH_SLEEP)
    return html

# ── 解析器 1：PBP（复用 br_pbp_parse.parse_pbp，覆写 gameid/season）────────
def parse_pbp_game(html, game):
    soup = BeautifulSoup(html, "lxml")
    away_br = BR_ABBR.get(game["away"], game["away"])
    home_br = BR_ABBR.get(game["home"], game["home"])
    rows = br_pbp_parse.parse_pbp(soup, away_br, home_br, game["br_url_id"])
    for r in rows:
        r["gameid"] = game["game_id_full"]   # 连接 player_gamelog
        r["season"] = game["season"]
    return rows

# ── 解析器 2：game 级投篮图（div.tooltip in #shots-{ABBR}）───────────────
TIP_Q = re.compile(r"^(1st|2nd|3rd|4th|5th|6th|7th|8th)?\s*quarter", re.I)
def parse_shot_chart(html, game):
    soup = BeautifulSoup(html, "lxml")
    away_br = BR_ABBR.get(game["away"], game["away"])
    home_br = BR_ABBR.get(game["home"], game["home"])
    rows = []
    for wrap in soup.find_all("div", id=lambda x: x and x.startswith("shots-")):
        abbr_br = wrap["id"].split("-", 1)[1]
        is_home = (abbr_br == home_br)
        opp_br = away_br if is_home else home_br
        for tip in wrap.find_all("div", class_="tooltip"):
            cls = tip.get("class") or []
            qs = [c for c in cls if c.startswith("q-")]
            ps = [c for c in cls if c.startswith("p-")]
            if not qs or not ps:
                continue
            period = int(qs[0][2:])
            slug = ps[0][2:]
            made = "make" in cls
            style = tip.get("style") or ""
            mt = re.search(r"top:\s*([\d.]+)px", style)
            ml = re.search(r"left:\s*([\d.]+)px", style)
            if not mt or not ml:
                continue
            x_px, y_px = float(ml.group(1)), float(mt.group(1))
            raw = tip.get("data-tip") or tip.get("tip") or ""
            parts = [p.strip() for p in re.split(r"<br\s*/?>", raw) if p.strip()]
            time_rem, shot_value, dist_ft = None, None, None
            if parts:
                m = re.match(r"\S+\s+quarter,\s*([\d:.]+)\s+remaining", parts[0], re.I)
                if m: time_rem = m.group(1)
            if len(parts) > 1:
                m = re.search(r"(\d)-pointer", parts[1])
                if m: shot_value = int(m.group(1))
                m = re.search(r"from\s+([\d.]+)\s+ft", parts[1])
                if m: dist_ft = float(m.group(1))
            rows.append({
                "player_id": slug, "season": game["season"],
                "game_date": game["game_date"], "game_id": game["br_url_id"],
                "season_type": "Play-In", "opponent_abbr": opp_br, "is_home": is_home,
                "period": period, "time_remaining": time_rem, "made": made,
                "shot_value": shot_value, "dist_ft": dist_ft,
                "x_px": x_px, "y_px": y_px,
                "x_norm": round((x_px - 250.0) / 250.0, 4),
                "y_norm": round(y_px / 500.0, 4),
                "src": "BR",
            })
    return rows

# ── 解析器 3：正负值（div.plusminus，段宽按节分桶）───────────────────────
TEAM_FULL = {
    "Portland Trail Blazers": "POR", "Memphis Grizzlies": "MEM", "Boston Celtics": "BOS",
    "Washington Wizards": "WAS", "Indiana Pacers": "IND", "Charlotte Hornets": "CHA",
    "Charlotte Bobcats": "CHA", "San Antonio Spurs": "SAS", "Los Angeles Lakers": "LAL",
    "Golden State Warriors": "GSW", "Brooklyn Nets": "BKN", "Cleveland Cavaliers": "CLE",
    "Atlanta Hawks": "ATL", "New Orleans Pelicans": "NOP", "New Orleans Hornets": "NOP",
    "Minnesota Timberwolves": "MIN", "Sacramento Kings": "SAC", "Philadelphia 76ers": "PHI",
    "Chicago Bulls": "CHI", "Miami Heat": "MIA", "Toronto Raptors": "TOR",
    "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL", "Dallas Mavericks": "DAL",
    "Phoenix Suns": "PHX",
}
PM_ONOFF = re.compile(r"On:\s*([+-]?\d+).*?Off:\s*([+-]?\d+).*?Net:\s*([+-]?\d+)")
WIDTH = re.compile(r"width:\s*([\d.]+)px")

def parse_plus_minus(html, game):
    soup = BeautifulSoup(html, "lxml")
    pm = soup.find("div", class_="plusminus")
    if pm is None:
        return []
    hdr = pm.find("div", class_="header")
    n_periods = len(hdr.find_all(recursive=False)) if hdr else 4
    if n_periods < 4: n_periods = 4
    rows, team_abbr = [], None
    for el in pm.find_all(["h3", "div"]):
        if el.name == "h3":
            team_abbr = TEAM_FULL.get(el.get_text(strip=True))
            continue
        if "player" not in (el.get("class") or []):
            continue
        name_el = el.find("span")
        if name_el is None: continue
        name = name_el.get_text(strip=True)
        m = PM_ONOFF.search(el.get_text(" ", strip=True))
        if not m: continue
        on_v, off_v, net_v = int(m.group(1)), int(m.group(2)), int(m.group(3))
        ppm = el.find_next_sibling("div", class_="player-plusminus")
        row = {
            "game_id_full": game["game_id_full"], "br_game_id": game["br_url_id"],
            "season": game["season"], "game_date": game["game_date"],
            "player_name": name, "team_abbr": team_abbr,
            "is_home": (team_abbr == NBA_ABBR.get(game["home"], game["home"])),
            "plus_minus_total": on_v, "off_court_value": off_v, "net_value": net_v,
        }
        for col in ("q1", "q2", "q3", "q4", "ot1", "ot2", "ot3", "ot4"):
            row[col] = None
        if ppm is not None:
            segs = []
            cursor = 0.0
            for d in ppm.find_all(recursive=False):
                w = WIDTH.search(d.get("style") or "")
                wv = float(w.group(1)) if w else 0.0
                cls = (d.get("class") or [""])[0]
                val = None
                if cls in ("plus", "minus", "even"):
                    tv = d.get_text(strip=True).replace("+", "")
                    try: val = int(tv)
                    except ValueError: val = None
                segs.append((cursor, wv, val))
                cursor += wv
            pw = cursor / n_periods if cursor > 0 else 250.0
            # 比例分割：跨节边界的段按重叠宽度比例分摊到相邻节（比中点法更准）
            fracs = [0.0] * n_periods
            for pos, wv, val in segs:
                if val is None or wv <= 0:
                    continue
                k = 0
                while k < n_periods and pos < cursor:
                    b0, b1 = k * pw, (k + 1) * pw
                    ov = min(pos + wv, b1) - max(pos, b0)
                    if ov > 0:
                        fracs[k] += val * ov / wv
                    if pos + wv <= b1:
                        break
                    k += 1
            for i in range(min(n_periods, 8)):
                col = ("q1", "q2", "q3", "q4", "ot1", "ot2", "ot3", "ot4")[i]
                row[col] = int(round(fracs[i]))
        # 注：q 列为 BR 段值比例分割的近似值（BR 段值本身圆整，和可能≠On ±1~5）；
        # plus_minus_total 为 BR 精确值。
        rows.append(row)
    return rows

# ── 解析器 3b：box 页正负值（权威源，2026-08-17 仲裁）─────────────────────
# box 页 box-{TEAM}-game-basic 的 plus_minus 列 = 权威 +/-；
# box-{TEAM}-q{N}-basic 提供精确逐节 +/-（q5+ = OT）；
# th[data-append-csv] = BR slug。经 202105190LAL / 202304120TOR 双案仲裁：
# box 页与另一来源恒一致，pm 页 On 与旧 CDN 值各有离群 → box 为准。
import re as _re
BOX_TID = _re.compile(r"^box-([A-Z]{3})-(game|q(\d+)|ot(\d+))-basic$")

def parse_box_pm(html, game):
    soup = BeautifulSoup(html, "lxml")
    away_br = BR_ABBR.get(game["away"], game["away"])
    home_br = BR_ABBR.get(game["home"], game["home"])
    # team → NBA 惯例
    nba_of = {away_br: game["away"], home_br: game["home"]}
    rows = {}   # name -> row
    for tbl in soup.find_all("table", id=BOX_TID):
        m = BOX_TID.match(tbl.get("id"))
        abbr_br, seg, qn, otn = m.group(1), m.group(2), m.group(3), m.group(4)
        if abbr_br not in nba_of:
            continue
        for tr in (tbl.find("tbody") or tbl).find_all("tr"):
            th = tr.find("th")
            if th is None:
                continue
            name = th.get_text(strip=True)
            if not name:
                continue
            d = {td.get("data-stat"): td.get_text(strip=True) for td in tr.find_all("td")}
            pmv = d.get("plus_minus", "")
            if seg == "game":
                if pmv in ("", None):   # DNP / 未上场
                    continue
                try:
                    total = int(pmv.replace("+", ""))
                except ValueError:
                    continue
                slug = th.get("data-append-csv")
                rows[name] = {
                    "game_id_full": game["game_id_full"], "br_game_id": game["br_url_id"],
                    "season": game["season"], "game_date": game["game_date"],
                    "player_name": name, "br_player_id": slug,
                    "team_abbr": nba_of[abbr_br], "is_home": (abbr_br == home_br),
                    "plus_minus_total": total, "off_court_value": None, "net_value": None,
                }
                for col in ("q1", "q2", "q3", "q4", "ot1", "ot2", "ot3", "ot4"):
                    rows[name][col] = None
            else:
                r = rows.get(name)
                if r is None or pmv in ("", None):
                    continue
                col = None
                if qn:
                    q = int(qn)   # q5+ 罕见；ot 用 otN id
                    if 1 <= q <= 4:
                        col = f"q{q}"
                    elif q <= 8:
                        col = f"ot{q - 4}"
                elif otn and int(otn) <= 4:
                    col = f"ot{otn}"
                if col:
                    try: r[col] = int(pmv.replace("+", ""))
                    except ValueError: pass
    # 逐节和 == 全场值 自检（跳过源本身无逐节数据的场，如 2020 气泡赛）
    bad = [n for n, r in rows.items()
           if any(v is not None for v in (r["q1"], r["q2"], r["q3"], r["q4"],
                                          r["ot1"], r["ot2"], r["ot3"], r["ot4"]))
           and sum(v for v in (r["q1"], r["q2"], r["q3"], r["q4"],
                               r["ot1"], r["ot2"], r["ot3"], r["ot4"]) if v is not None)
           != r["plus_minus_total"]]
    if bad:
        log.warning("  %s: 逐节和≠全场 %d 人: %s", game["br_url_id"], len(bad), bad[:5])
    return list(rows.values())

def parse_box_tables_meta(html, game):
    """box 页逐节表 mp 提取：{team_nba: {period_int: {slug: mp_seconds}}}。
    供 PBP 正负值重建做"节初在场"锚定。"""
    soup = BeautifulSoup(html, "lxml")
    away_br = BR_ABBR.get(game["away"], game["away"])
    home_br = BR_ABBR.get(game["home"], game["home"])
    nba_of = {away_br: game["away"], home_br: game["home"]}
    out = {}
    for tbl in soup.find_all("table", id=BOX_TID):
        m = BOX_TID.match(tbl.get("id"))
        abbr_br, seg, qn, otn = m.group(1), m.group(2), m.group(3), m.group(4)
        if abbr_br not in nba_of or seg == "game":
            continue
        p = int(qn) if qn else 4 + int(otn)
        team = nba_of[abbr_br]
        for tr in (tbl.find("tbody") or tbl).find_all("tr"):
            th = tr.find("th")
            if th is None:
                continue
            slug = th.get("data-append-csv")
            if not slug:
                continue
            mp = ""
            for td in tr.find_all("td"):
                if td.get("data-stat") == "mp":
                    mp = td.get_text(strip=True)
                    break
            mm = re.match(r"(\d+):(\d{2})", mp)
            if mm:
                out.setdefault(team, {}).setdefault(p, {})[slug] = int(mm.group(1)) * 60 + int(mm.group(2))
    return out

# ── DB ─────────────────────────────────────────────────────────────────────
def db_conn():
    env = {}
    with open("/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env") as f:
        for line in f:
            if line.startswith("DB_PASSWORD="):
                env["pw"] = line.strip().split("=", 1)[1]
    return psycopg2.connect(host="127.0.0.1", port=5433, dbname="nba", user="postgres",
                            password=env["pw"])

def load_games(conn, only=None):
    sql = ("SELECT season, game_id_full, br_game_id, game_date::text, home_team_abbr, "
           "away_team_abbr FROM playin_game_dates ORDER BY season, game_date")
    with conn.cursor() as cur:
        cur.execute(sql)
        out = []
        for s, gf, br, dt, h, a in cur.fetchall():
            url_id = br[:9] + BR_ABBR.get(br[-3:], br[-3:])
            g = {"season": s, "game_id_full": gf, "br_game_id": br, "br_url_id": url_id,
                 "game_date": dt, "home": h, "away": a}
            if only and only not in (gf, br, url_id):
                continue
            out.append(g)
    return out

def shots_needed(conn, game):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM player_shot_chart WHERE season_type='Play-In' "
                    "AND game_id=%s LIMIT 1", (game["br_url_id"],))
        return cur.fetchone() is None

PBP_COLS = ("gameid, season, eventnum, period, clock, clock_seconds, h_pts, a_pts, team, "
            "playerid, player, event_type, subtype, action_verb, result, x, y, dist, "
            "description, current_team, homedescription, visitordescription, "
            "neutraldescription, scorehome, scorevisitor, scoremargin, source")
def insert_pbp(cur, rows):
    cur.executemany(
        f"INSERT INTO play_by_play ({PBP_COLS}) VALUES ({','.join(['%s']*27)})",
        [tuple(r.get(c) for c in [c.strip() for c in PBP_COLS.replace(' ', '').split(',')]) for r in rows])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", help="只跑一场（game_id_full / br_game_id / url id）")
    ap.add_argument("--only", choices=["pbp", "shots", "pm", "boxpm"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = db_conn()
    games = load_games(conn, only=args.game)
    log.info("%d 场待处理%s", len(games), "（干跑）" if args.dry_run else "")
    stats = {"pbp": 0, "shots": 0, "pm": 0}
    for g in games:
        tag = g["br_url_id"]
        # PBP
        if args.only in (None, "pbp"):
            html = cached_fetch("pbp", tag)
            rows = parse_pbp_game(html, g) if html else []
            log.info("%s PBP: %d rows", tag, len(rows))
            if not args.dry_run and rows:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM play_by_play WHERE gameid=%s", (g["game_id_full"],))
                    insert_pbp(cur, rows)
                conn.commit()
            stats["pbp"] += len(rows)
        # 投篮图（仅缺口场）
        if args.only in (None, "shots") and shots_needed(conn, g):
            html = cached_fetch("shot", tag)
            rows = parse_shot_chart(html, g) if html else []
            log.info("%s SHOT: %d rows", tag, len(rows))
            if not args.dry_run and rows:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM player_shot_chart WHERE season_type='Play-In' AND game_id=%s",
                                (g["br_url_id"],))
                    cur.executemany(
                        "INSERT INTO player_shot_chart (player_id, season, game_date, game_id, "
                        "season_type, opponent_abbr, is_home, period, time_remaining, made, "
                        "shot_value, dist_ft, x_px, y_px, x_norm, y_norm, src) "
                        "VALUES (%(player_id)s, %(season)s, %(game_date)s, %(game_id)s, "
                        "%(season_type)s, %(opponent_abbr)s, %(is_home)s, %(period)s, "
                        "%(time_remaining)s, %(made)s, %(shot_value)s, %(dist_ft)s, %(x_px)s, "
                        "%(y_px)s, %(x_norm)s, %(y_norm)s, %(src)s)", rows)
                conn.commit()
            stats["shots"] += len(rows)
        elif args.only == "shots":
            log.info("%s SHOT: 已有数据，跳过", tag)
        # 正负值（权威源 = box 页；off/net 合并自 pm 页）
        if args.only in (None, "pm", "boxpm"):
            html = cached_fetch("box", tag)
            rows = parse_box_pm(html, g) if html else []
            pm_html = cached_fetch("pm", tag)
            pm_rows = {r["player_name"]: r for r in (
                parse_plus_minus(pm_html, g) if pm_html else [])}
            for r in rows:
                pr = pm_rows.get(r["player_name"])
                if pr:
                    r["off_court_value"] = pr["off_court_value"]
                    r["net_value"] = pr["net_value"]
            log.info("%s PM(box): %d players", tag, len(rows))
            if not args.dry_run and rows:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM player_playin_plus_minus WHERE game_id_full=%s",
                                (g["game_id_full"],))
                    cur.executemany(
                        "INSERT INTO player_playin_plus_minus (game_id_full, br_game_id, season, "
                        "game_date, player_name, br_player_id, team_abbr, is_home, q1, q2, q3, "
                        "q4, ot1, ot2, ot3, ot4, plus_minus_total, off_court_value, net_value) VALUES ("
                        "%(game_id_full)s, %(br_game_id)s, %(season)s, %(game_date)s, "
                        "%(player_name)s, %(br_player_id)s, %(team_abbr)s, %(is_home)s, %(q1)s, "
                        "%(q2)s, %(q3)s, %(q4)s, %(ot1)s, %(ot2)s, %(ot3)s, %(ot4)s, "
                        "%(plus_minus_total)s, %(off_court_value)s, %(net_value)s)", rows)
                conn.commit()
            stats["pm"] += len(rows)
    conn.close()
    log.info("完成：PBP %d 行 | 投篮图 %d 行 | 正负值 %d 人次%s",
             stats["pbp"], stats["shots"], stats["pm"], "（干跑，未落库）" if args.dry_run else "")

if __name__ == "__main__":
    main()
