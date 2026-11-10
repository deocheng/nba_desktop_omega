#!/usr/bin/env python3
"""历史 NBA 薪资爬虫（1997-2005 缺口填补）。

数据源：Basketball-Reference 每队赛季页的「Salaries」表
    https://www.basketball-reference.com/teams/<TEAM>/<YEAR>.html
    其中 YEAR = 赛季结束年（1998 -> 1997-98）。与库内 player_salaries_historical.season 口径一致。

抓取通道：复用本机 Chrome CDP（127.0.0.1:9223，profile 已含有效 cf_clearance）。
  不走 requests（直连/代理均被 Cloudflare 挑战），改走 CDP 导航真实浏览器渲染，
  拿到的 DOM 含 JS 反注释后的 Salaries 表。

写入：player_salaries_historical，UPSERT 键 (player_name, season)。
  仅补缺口/纠错，不删既有行；同 (player_name,season) 冲突则更新 salary/team_abbr。

用法：
    python3 scrape_historical_salaries.py [--years 1997-2005] [--teams ATL LAL ...]
"""
from __future__ import annotations
import argparse, json, sys, time, random, os, re, urllib.request, urllib.parse, datetime
from bs4 import BeautifulSoup
import psycopg2
from psycopg2.extras import execute_values
import websocket

CDP = "http://127.0.0.1:9223"
DB = dict(host="localhost", port=5433, dbname="nba", user="postgres",
          password="R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1")

TEAMS = ['ATL','BOS','BRK','CHO','CHI','CLE','DAL','DEN','DET','GSW','HOU','IND',
        'LAC','LAL','MEM','MIA','MIL','MIN','NOP','NYK','OKC','ORL','PHI','PHX',
        'POR','SAC','SAS','TOR','UTA','WAS']

def teams_for_year(y):
    """按赛季返回正确的 BR 队码（历史队名/搬迁）。
    权威来源: dim_teams / team_mapping (BR 真实队码)。
    关键修正(用户指出): 菲尼克斯=PHO(非PHX); 夏洛特原黄蜂=CHH(非CHA), 山猫/现黄蜂=CHO;
              网=NJN(2012前); 灰熊 VAN(2001前)/MEM(2002起); 超音速=SEA(2008前)。
    """
    base = ['ATL','BOS','CHI','CLE','DAL','DEN','DET','GSW','HOU','IND','LAC','LAL',
            'MIA','MIL','MIN','NYK','ORL','PHI','PHO','POR','SAC','SAS','TOR','UTA','WAS']
    if y <= 2001:   # 1996-97..2000-01: 网=NJN / 夏洛特黄蜂=CHH / 温哥华灰熊=VAN / 超音速=SEA
        return base + ['NJN','CHH','VAN','SEA']
    elif y == 2002: # 2001-02: 灰熊迁 MEM, 黄蜂仍 CHH
        return base + ['NJN','CHH','MEM','SEA']
    elif y <= 2004: # 2002-03..2003-04: 黄蜂=NOH (山猫 2004-05 季才加入)
        return base + ['NJN','NOH','MEM','SEA']
    else:           # 2005: 夏洛特山猫=CHO 加入 (30 队)
        return base + ['NJN','NOH','MEM','SEA','CHO']

def http_put(path):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(CDP + path, method="PUT", data=b"")
    with op.open(req, timeout=15) as r:
        return json.loads(r.read().decode())

def http_get(path):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(CDP + path, timeout=15) as r:
        return json.loads(r.read().decode())

CF_MARKERS = ["just a moment", "verify you are human", "请稍候", "安全验证",
              "cf-mitigated", "attention required", "ray_id", "cf-chl", "checking your browser"]

def _is_cf(html):
    if not html:
        return False
    low = html.lower()
    return any(k.lower() in low for k in CF_MARKERS)

def fetch_html(url, wait=30, cache_key=None, cache_dir=None, use_cache=True):
    # 命中本地缓存：直接读 HTML，不再访问 BR（避免同一页面反复请求触发风控）
    if use_cache and cache_key and cache_dir:
        p = os.path.join(cache_dir, cache_key + ".html")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
    tgt = http_put("/json/new?about:blank")
    tid = tgt.get("id"); ws = tgt.get("webSocketDebuggerUrl")
    html = None
    sock = websocket.create_connection(ws, timeout=40, suppress_origin=True)
    try:
        sock.send(json.dumps({"id":1,"method":"Page.enable"}))
        sock.send(json.dumps({"id":2,"method":"Runtime.enable"}))
        sock.send(json.dumps({"id":3,"method":"Page.navigate","params":{"url":url}}))
        # 总预算 wait 秒：先等 load 事件，再轮询等 CF 挑战解除
        budget = time.time() + wait
        while time.time() < budget:
            sock.settimeout(2)
            try:
                m = json.loads(sock.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if m.get("method") == "Page.loadEventFired":
                break
            if m.get("id") in (1,2,3) and "error" in m:
                break
        while time.time() < budget:
            sock.send(json.dumps({"id":5,"method":"Runtime.evaluate",
                                   "params":{"expression":"document.documentElement.outerHTML","returnByValue":True}}))
            while True:
                m = json.loads(sock.recv())
                if m.get("id")==5:
                    html = m.get("result",{}).get("result",{}).get("value")
                    break
            if not _is_cf(html):
                break
            time.sleep(2)
    finally:
        sock.close()
        try: http_get("/json/close/"+tid)
        except Exception: pass
    # 仅当成功取到非 CF 页面才落盘缓存（绝不缓存拦截页，避免坏缓存永久漏抓）
    if html and not _is_cf(html) and cache_key and cache_dir:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(os.path.join(cache_dir, cache_key + ".html"), "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass
    return html

def parse_money(t):
    if not t: return None
    t = t.strip().replace('$','').replace(',','').strip()
    if not t: return None
    try: return int(float(t))
    except ValueError: return None

def parse_salaries(html):
    if not html:
        return None
    if _is_cf(html):  # CF challenge (中/英文拦截页)
        return None
    # BR 把部分表（如 salaries2）包在 HTML 注释里，BS4 默认看不到；先还原注释内的 table
    html = re.sub(r'<!--(.*?)-->',
                  lambda m: m.group(1) if '<table' in m.group(1) else m.group(0),
                  html, flags=re.S)
    soup = BeautifulSoup(html, 'lxml')
    for tbl in soup.find_all('table'):
        thead = tbl.find('thead')
        heads = [th.get_text(strip=True) for th in thead.find_all(['th','td'])] if thead else []
        # 薪资表判据：存在 'Salary' 表头列（球员列表头常为空白，不能依赖 'Player'）
        if 'Salary' not in heads:
            continue
        sal_idx = heads.index('Salary')
        out = []
        rows = tbl.find('tbody').find_all('tr') if tbl.find('tbody') else []
        for tr in rows:
            cells = [c.get_text(strip=True) for c in tr.find_all(['th','td'])]
            if len(cells) <= sal_idx:
                continue
            th = tr.find('th', {'data-stat':'player'})
            name = th.get_text(strip=True) if th else (cells[1] if len(cells) > 1 else (cells[0] if cells else ''))
            if not name:
                continue
            sal = parse_money(cells[sal_idx])
            if sal is None:
                continue
            out.append((name, sal))
        if out:
            return out
    return []  # 404 / 无薪资表 -> 空

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="1997-2005")
    ap.add_argument("--teams", nargs="*", default=None)
    ap.add_argument("--delay", type=float, default=3.0,
                    help="seconds to sleep between team requests (be gentle to the source)")
    ap.add_argument("--cache-dir",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "salaries"),
                    help="directory to cache fetched BR team-page HTML (re-grab from cache on re-run)")
    ap.add_argument("--no-cache", action="store_true",
                    help="ignore existing cache and force re-fetch from BR")
    ap.add_argument("--wait", type=int, default=30,
                    help="seconds to wait for Cloudflare challenge / page load before reading HTML")
    args = ap.parse_args()
    cache_dir = None if args.no_cache else args.cache_dir
    y0, y1 = (int(x) for x in args.years.split("-"))
    years = list(range(y0, y1+1))

    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    now = datetime.datetime.now()
    total_new = 0
    per_season = {y:0 for y in years}
    for y in years:
        teams = args.teams or teams_for_year(y)
        for team in teams:
            url = f"https://www.basketball-reference.com/teams/{team}/{y}.html"
            try:
                html = fetch_html(url, wait=args.wait, cache_key=f"{team}_{y}", cache_dir=cache_dir)
                rows = parse_salaries(html)
            except Exception as e:
                print(f"  ERR {team}/{y}: {e}", flush=True)
                rows = None
            if rows is None:
                print(f"  SKIP {team}/{y} (CF challenge / fetch fail)", flush=True)
                time.sleep(args.delay * (0.8 + 0.4*random.random())); continue
            if not rows:
                # 404 / 该队该季无薪资表（如某季球队尚未存在）
                print(f"  EMPTY {team}/{y}", flush=True)
                time.sleep(args.delay * (0.8 + 0.4*random.random())); continue
            data = [(team, y, n, s, 'br_team_page', now) for (n,s) in rows]
            try:
                execute_values(cur, """
                    INSERT INTO player_salaries_historical
                        (team_abbr, season, player_name, salary, source, imported_at)
                    VALUES %s
                    ON CONFLICT (player_name, season) DO UPDATE SET
                        salary=EXCLUDED.salary, team_abbr=EXCLUDED.team_abbr,
                        source=EXCLUDED.source, imported_at=EXCLUDED.imported_at;
                """, data)
                conn.commit()
                total_new += len(data)
                per_season[y] += len(data)
                print(f"  OK {team}/{y}: {len(data)} rows", flush=True)
            except Exception as e:
                conn.rollback()
                print(f"  DBERR {team}/{y}: {e}", flush=True)
            time.sleep(args.delay * (0.8 + 0.4*random.random()))
    cur.close(); conn.close()
    print("===== DONE =====")
    print("per-season rows upserted:", per_season)
    print("total:", total_new)

if __name__ == "__main__":
    main()
