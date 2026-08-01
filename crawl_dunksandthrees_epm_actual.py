#!/usr/bin/env python3
"""dunksandthrees.com EPM *Actual* 爬虫 + 入库 (cache-first, 幂等 upsert).

来源: https://dunksandthrees.com/epm/actual
数据: 赛季实际 EPM (off/def/tot/ewins) + 全套命中率/篮板率/助攻率等 + 每项的 {z, rk, pctl}。

与 /epm (crawl_dunksandthrees_epm.py) 的差异:
  * /epm        —— 预测性每日 EPM, 载荷是 keyed 对象 (88 字段)。
  * /epm/actual —— 赛季实际值, 载荷是 **61 列位置数组** `stats:[[...]]`,
                   紧跟其后的 `k:{season:0,...,fga_75:60}` 是键位映射(以页面自带的为准, 抗改版)。
  * 历史赛季 (?season=2002..2025) 被付费墙锁 (303 → /subscribe?reason=locked-season),
    免费仅当前赛季 → 本脚本只抓当前赛季, 每赛季一行快照, 幂等覆盖。

方法论同 nba-br-crawler skill (cache-first):
  抓取 → 原始 HTML 落 raw_archive/dunksandthrees/epm_actual_{season}_{game_dt}.html
  解析 → stats 位置数组 × 页内 k 映射 → keyed dict ({z,rk,pctl} 原样保留)
  入库 → 核心列 promote, 全字段存 raw JSONB; NBA id → BR id 走 player_id_bridge

用法:
  .venv/bin/python crawl_dunksandthrees_epm_actual.py            # 抓取+入库 (cache-first)
  .venv/bin/python crawl_dunksandthrees_epm_actual.py --force    # 忽略缓存重抓
  .venv/bin/python crawl_dunksandthrees_epm_actual.py --dry-run  # 只解析不写库
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras

URL = "https://dunksandthrees.com/epm/actual"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
ROOT = Path(__file__).resolve().parent
ARCHIVE_DIR = ROOT / "raw_archive" / "dunksandthrees"


def _load_env() -> dict:
    env = {}
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def db_conn():
    env = _load_env()
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", env.get("DB_HOST", "localhost")),
        port=int(os.environ.get("DB_PORT", env.get("DB_PORT", "5433"))),
        dbname=os.environ.get("DB_NAME", env.get("DB_NAME", "nba")),
        user=os.environ.get("DB_USER", env.get("DB_USER", "postgres")),
        password=os.environ.get("DB_PASSWORD", env.get("DB_PASSWORD", "postgres")),
    )


def _node_bin() -> str:
    for cand in (
        shutil.which("node"),
        "/Users/deocheng/.workbuddy/binaries/node/versions/22.22.2/bin/node",
        "/Users/deocheng/.local/bin/node",
    ):
        if cand and Path(cand).exists():
            return cand
    raise RuntimeError("node 未找到, 无法把 JS 对象字面量转 JSON")


def fetch_html(force: bool = False) -> str:
    """cache-first: 命中最新归档直接返回; 否则线上抓取."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    if not force:
        cached = sorted(ARCHIVE_DIR.glob("epm_actual_*.html"))
        if cached and cached[-1].stat().st_size > 10000:
            print(f"[cache] 命中本地归档 {cached[-1].name}")
            return cached[-1].read_text(encoding="utf-8")

    print(f"[fetch] GET {URL}")
    try:
        from curl_cffi import requests as creq  # type: ignore
        r = creq.get(URL, impersonate="chrome124", timeout=60)
        html = r.text
    except Exception:
        import urllib.request
        req = urllib.request.Request(URL, headers={"User-Agent": UA})
        html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
    if "stats:[" not in html:
        raise RuntimeError("页面结构变化: 未找到 stats:[ 载荷")
    return html


def archive_html(html: str, season: int, game_dt: str) -> Path:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dst = ARCHIVE_DIR / f"epm_actual_{season}_{game_dt}.html"
    if dst.exists() and dst.stat().st_size > 10000:
        return dst
    fd, tmp = tempfile.mkstemp(dir=ARCHIVE_DIR, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, dst)
    print(f"[archive] 原始页落盘 {dst}")
    return dst


def _extract_balanced(html: str, key: str) -> str:
    """从 key 处提取配平的 [..] 或 {..} 片段."""
    i = html.find(key)
    if i < 0:
        raise RuntimeError(f"未找到 {key}")
    j = i + len(key) - 1  # open bracket
    open_c = html[j]
    close_c = "]" if open_c == "[" else "}"
    depth = 0
    for k in range(j, len(html)):
        c = html[k]
        if c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return html[j:k + 1]
    raise RuntimeError(f"{key} 括号不匹配")


def _js_to_obj(src: str):
    node = _node_bin()
    script = (
        "let d;const s=require('fs').readFileSync(0,'utf8');"
        "eval('d='+s);process.stdout.write(JSON.stringify(d));"
    )
    out = subprocess.run([node, "-e", script], input=src,
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"node 解析失败: {out.stderr[:500]}")
    return json.loads(out.stdout)


def extract(html: str) -> tuple[list[dict], dict]:
    """返回 (keyed 记录列表, meta{season, game_dt, seasontype})."""
    rows = _js_to_obj(_extract_balanced(html, "stats:["))       # 61 列位置数组
    kmap = _js_to_obj(_extract_balanced(html, "k:{"))           # 键位映射(页面自带)
    idx2key = {v: k for k, v in kmap.items()}
    records = []
    for r in rows:
        rec = {idx2key[i]: v for i, v in enumerate(r) if i in idx2key}
        records.append(rec)

    meta = {"season": records[0]["season"] if records else None,
            "seasontype": records[0].get("seasontype") if records else None,
            "game_dt": None}
    try:
        lg = _js_to_obj(_extract_balanced(html, "lastGame:["))
        if lg:
            meta["game_dt"] = lg[0].get("game_dt")
    except Exception:
        meta["game_dt"] = datetime.now().strftime("%Y-%m-%d")
    return records, meta


DDL = """
CREATE TABLE IF NOT EXISTS player_epm_actual (
    nba_player_id  text      NOT NULL,
    br_player_id   varchar(32),
    player_name    text      NOT NULL,
    season         integer   NOT NULL,
    seasontype     integer   NOT NULL DEFAULT 2,
    game_dt        date,
    team_id        bigint,
    team_alias     text,
    age            integer,
    pos_text       text,
    gp             integer,
    mp             numeric,
    mpg            numeric,
    epm_off        numeric,
    epm_def        numeric,
    epm_tot        numeric,
    ewins          numeric,
    off_rk         integer,
    def_rk         integer,
    tot_rk         integer,
    usg            numeric,
    tspct          numeric,
    efg            numeric,
    fg2pct         numeric,
    fg3pct         numeric,
    ftpct          numeric,
    orbpct         numeric,
    drbpct         numeric,
    astpct         numeric,
    topct          numeric,
    stlpct         numeric,
    blkpct         numeric,
    raw            jsonb     NOT NULL,
    source         text      DEFAULT 'dunksandthrees.com/epm/actual',
    scraped_at     timestamp DEFAULT now(),
    PRIMARY KEY (nba_player_id, season, seasontype)
);
CREATE INDEX IF NOT EXISTS idx_epm_actual_br_id  ON player_epm_actual (br_player_id);
CREATE INDEX IF NOT EXISTS idx_epm_actual_season ON player_epm_actual (season);
CREATE INDEX IF NOT EXISTS idx_epm_actual_tot    ON player_epm_actual (season, epm_tot DESC);
"""

PCT_KEYS = ["usg", "tspct", "efg", "fg2pct", "fg3pct", "ftpct",
            "orbpct", "drbpct", "astpct", "topct", "stlpct", "blkpct"]


def _attr_rk(rec: dict, key: str):
    a = rec.get(f"{key}_attr")
    return a.get("rk") if isinstance(a, dict) else None


def upsert(rows: list[dict], meta: dict, dry_run: bool = False) -> tuple[int, int]:
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(DDL)

    cur.execute("SELECT nba_player_id, br_player_id FROM player_id_bridge")
    bridge = {str(a): b for a, b in cur.fetchall()}

    cols = (["nba_player_id", "br_player_id", "player_name", "season", "seasontype",
             "game_dt", "team_id", "team_alias", "age", "pos_text", "gp", "mp", "mpg",
             "epm_off", "epm_def", "epm_tot", "ewins", "off_rk", "def_rk", "tot_rk"]
            + PCT_KEYS + ["raw"])

    values, matched = [], 0
    for r in rows:
        nba_id = str(r.get("player_id"))
        br = bridge.get(nba_id)
        if br:
            matched += 1
        row = [
            nba_id, br, r.get("player_name"), r.get("season"),
            r.get("seasontype") or 2, meta.get("game_dt"),
            r.get("team_id"), r.get("team_alias"), r.get("age"),
            r.get("pos_text"), r.get("gp"), r.get("mp"), r.get("mpg"),
            r.get("off"), r.get("def"), r.get("tot"), r.get("ewins"),
            _attr_rk(r, "off"), _attr_rk(r, "def"), _attr_rk(r, "tot"),
        ] + [r.get(k) for k in PCT_KEYS] + [json.dumps(r)]
        values.append(row)

    if dry_run:
        cur.close(); conn.close()
        return len(values), matched

    update_cols = [c for c in cols if c not in ("nba_player_id", "season", "seasontype")]
    set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
    set_clause += ", scraped_at=now()"
    sql = (f"INSERT INTO player_epm_actual ({', '.join(cols)}) VALUES %s "
           f"ON CONFLICT (nba_player_id, season, seasontype) DO UPDATE SET {set_clause}")
    psycopg2.extras.execute_values(cur, sql, values, page_size=200)
    conn.commit()
    cur.close(); conn.close()
    return len(values), matched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略本地缓存重新抓取")
    ap.add_argument("--dry-run", action="store_true", help="只解析不写库")
    args = ap.parse_args()

    html = fetch_html(force=args.force)
    rows, meta = extract(html)
    archive_html(html, meta["season"], meta.get("game_dt") or "latest")

    total, matched = upsert(rows, meta, dry_run=args.dry_run)
    tag = "[dry-run] " if args.dry_run else ""
    print(f"{tag}解析 {total} 条 | BR 映射命中 {matched}/{total} "
          f"({matched * 100 // max(total, 1)}%) | season={meta['season']} "
          f"seasontype={meta['seasontype']} game_dt={meta['game_dt']}")
    if not args.dry_run:
        print("[ok] 已 upsert 到 player_epm_actual")


if __name__ == "__main__":
    main()
