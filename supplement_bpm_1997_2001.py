#!/usr/bin/env python3
"""
supplement_bpm_1997_2001.py
以「搜索/网络查证」形式补充 1997-2001 赛季的 plus-minus 指标。
dunksandthrees (D&T) EPM 源头只到 2002，故 1997-2001 用 Basketball-Reference 的
Box Plus/Minus (BPM) 作为替代指标，映射到 player_epm 表：
    obpm -> epm_off, dbpm -> epm_def, bpm -> epm_tot
    source = 'basketball-reference.com/bpm'
    nba_player_id = br_player_id (BBR slug; NOT NULL 占位, 不与 D&T 数字 ID 撞)
仅写入 1997-2001（D&T 从 2002 起），避免与 player_season() 的 LEFT JOIN 产生同季重复行。

用法:
    .venv/bin/python supplement_bpm_1997_2001.py            # 默认 dry-run 预览
    .venv/bin/python supplement_bpm_1997_2001.py --write   # 落库(先建备份表+manifest)
"""
import os, sys, re, json, subprocess, time, psycopg2
from bs4 import BeautifulSoup
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "raw_archive", "bbr_bpm")
os.makedirs(CACHE, exist_ok=True)

SEASONS = [1997, 1998, 1999, 2000, 2001]          # 赛季结束年 = BBR 页年份
SOURCE = "basketball-reference.com/bpm"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"

# ---------- DB ----------
def load_env():
    env = {}
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    return env

ENV = load_env()
def conn():
    return psycopg2.connect(host=ENV["DB_HOST"], port=int(ENV["DB_PORT"]),
                            dbname=ENV["DB_NAME"], user=ENV["DB_USER"],
                            password=ENV["DB_PASSWORD"])

# ---------- fetch ----------
def fetch_season(season):
    url = f"https://www.basketball-reference.com/leagues/NBA_{season}_advanced.html"
    path = os.path.join(CACHE, f"NBA_{season}_advanced.html")
    if os.path.exists(path) and os.path.getsize(path) > 50000:
        return path
    for attempt in range(3):
        try:
            subprocess.run(
                ["curl", "-s", "--max-time", "40", "-A", UA, "--compressed",
                 "-H", "Accept-Language: en-US,en;q=0.9", url, "-o", path],
                check=True, env={**os.environ, "http_proxy": "", "https_proxy": "",
                                 "HTTP_PROXY": "", "HTTPS_PROXY": ""})
            if os.path.exists(path) and os.path.getsize(path) > 50000:
                return path
        except subprocess.CalledProcessError:
            pass
        time.sleep(2 + attempt)
    raise RuntimeError(f"fetch failed: {url}")

# ---------- parse ----------
def parse_season(path, season):
    html = open(path, encoding="utf-8").read()
    soup = BeautifulSoup(html, "html.parser")
    tbl = soup.find("table", id="advanced")
    if tbl is None:
        for t in soup.find_all("table"):
            if t.find("th", {"data-stat": "bpm"}):
                tbl = t; break
    if tbl is None or tbl.find("tbody") is None:
        return []
    rows = tbl.find("tbody").find_all("tr")
    seen = set()
    out = []
    for r in rows:
        cls = " ".join(r.get("class", []))
        if "partial_table" in cls:         # 跳过按队拆分的逐队行, 只保留赛季合计行(空 class)
            continue
        p = r.find(["td", "th"], {"data-stat": "name_display"})
        if p is None:
            continue
        slug = p.get("data-append-csv") or (p.find("a") and p.find("a").get("data-append-csv"))
        if not slug or slug in seen:
            continue
        seen.add(slug)
        name = p.get_text(strip=True)
        def cell(stat):
            c = r.find(["td", "th"], {"data-stat": stat})
            return c.get_text(strip=True) if c else None
        team = cell("team_name_abbr")
        age = cell("age")
        obpm = cell("obpm"); dbpm = cell("dbpm"); bpm = cell("bpm")
        def num(x):
            if x in (None, "", "-"): return None
            try: return float(x)
            except ValueError: return None
        out.append({
            "nba_player_id": slug,
            "br_player_id": slug,
            "player_name": name,
            "season": season,
            "team_alias": team,
            "age": int(age) if age and age.isdigit() else None,
            "epm_off": num(obpm),
            "epm_def": num(dbpm),
            "epm_tot": num(bpm),
            "source": SOURCE,
        })
    return out

# ---------- main ----------
def main():
    write = "--write" in sys.argv
    all_rows = []
    summary = {}
    for s in SEASONS:
        path = fetch_season(s)
        rows = parse_season(path, s)
        all_rows += rows
        summary[s] = len(rows)
        print(f"[season {s}] parsed {len(rows)} players  (cache: {os.path.basename(path)})")

    # coverage vs fact_player_season_stats (RS)
    c = conn(); cur = c.cursor()
    print("\n=== coverage vs fact_player_season_stats (RS) ===")
    for s in SEASONS:
        cur.execute("""SELECT COUNT(DISTINCT player_id) FROM fact_player_season_stats
                       WHERE season=%s AND season_type='Regular Season'""", (s,))
        db_players = cur.fetchone()[0]
        slugs = {r["br_player_id"] for r in all_rows if r["season"] == s}
        cur.execute("""SELECT COUNT(*) FROM (SELECT UNNEST(%s::text[]) AS slug) x
                       WHERE slug IN (SELECT DISTINCT player_id FROM fact_player_season_stats
                                      WHERE season=%s AND season_type='Regular Season')""",
                     (list(slugs), s))
        matched = cur.fetchone()[0]
        pct = (matched / db_players * 100) if db_players else 0
        print(f"  {s}: BBR {len(slugs)} rows | DB RS distinct {db_players} | matched {matched} ({pct:.1f}%)")
    c.close()

    # sample
    print("\n=== sample (first 5 of 1998) ===")
    for r in [x for x in all_rows if x["season"] == 1998][:5]:
        print(f"  {r['br_player_id']:12} {r['player_name']:22} {r['team_alias']:4} "
              f"off={r['epm_off']} def={r['epm_def']} tot={r['epm_tot']}")

    print(f"\nTOTAL rows to insert: {len(all_rows)}")
    if not write:
        print("\n*** DRY-RUN (no DB write). Re-run with --write to persist. ***")
        return

    # ---- WRITE ----
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    c = conn(); cur = c.cursor()
    bak = f"player_epm_bak_bpm_{ts}"
    cur.execute(f"CREATE TABLE {bak} AS SELECT * FROM player_epm")
    print(f"\n[backup] created {bak}")
    manifest = os.path.join(ROOT, "scripts", "rollback", f"bpm_1997_2001_{ts}.json")
    os.makedirs(os.path.dirname(manifest), exist_ok=True)

    cols = ["nba_player_id","br_player_id","player_name","season","team_alias","age",
            "epm_off","epm_def","epm_tot","source"]
    sql = f"""INSERT INTO player_epm ({','.join(cols)})
              VALUES ({','.join(['%s']*len(cols))})
              ON CONFLICT (nba_player_id, season, source) DO NOTHING"""
    inserted = 0
    for r in all_rows:
        cur.execute(sql, [r[c] for c in cols])
        inserted += cur.rowcount
    c.commit()

    # post-verify
    cur.execute("SELECT season, COUNT(*) FROM player_epm WHERE source=%s GROUP BY season ORDER BY season", (SOURCE,))
    after = dict(cur.fetchall())
    print(f"[write] inserted (new) rows: {inserted}")
    print("[verify] player_epm rows by season (source=bbr/bpm):", after)
    c.close()

    with open(manifest, "w") as f:
        json.dump({"backup_table": bak, "source": SOURCE, "seasons": SEASONS,
                   "rows": [{ "br_player_id": r["br_player_id"], "season": r["season"] } for r in all_rows],
                   "inserted": inserted}, f, indent=2)
    print(f"[manifest] {manifest}")

if __name__ == "__main__":
    main()
