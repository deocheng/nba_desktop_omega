#!/usr/bin/env python3
"""dunksandthrees.com EPM 爬虫 + 入库 (cache-first, 幂等 upsert).

来源: https://dunksandthrees.com/epm
数据: EPM (Estimated Plus-Minus) —— off/def/tot 三分量 + 88 个字段(per-100 统计/排名/z-score)。
      整份数据直接内嵌在 SvelteKit 页面的 hydration 载荷里 (`stats:[{...}]`),无需额外 API。

方法论 (遵循 nba-br-crawler skill 的 cache-first):
  1. 抓取 → 原始 HTML 第一时间落 raw_archive/dunksandthrees/epm_{game_dt}.html
  2. 解析 → 从本地/内存提取 stats 数组 (JS 对象字面量, 用 node 转 JSON)
  3. 入库 → 榨干 88 字段: 核心列 promote 成表列, 全量 raw 存 JSONB, 一字段不丢
  4. NBA 数字 player_id → BR player_id 经 player_id_bridge 映射

用法:
  .venv/bin/python crawl_dunksandthrees_epm.py            # 抓取+入库 (cache-first)
  .venv/bin/python crawl_dunksandthrees_epm.py --force    # 忽略本地缓存重新抓取
  .venv/bin/python crawl_dunksandthrees_epm.py --dry-run  # 只解析不写库
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

URL = "https://dunksandthrees.com/epm"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
ROOT = Path(__file__).resolve().parent
ARCHIVE_DIR = ROOT / "raw_archive" / "dunksandthrees"

# 提升为独立表列的核心字段 (其余全部保留在 raw JSONB)
CORE_NUM = [
    "off", "def", "tot", "tot_change",
    "p_pct_start", "p_t_poss_48", "p_mp_48", "p_usg", "p_pts_100",
    "p_tspct", "p_efg", "p_ast_100", "p_tov_100", "p_orb_100",
    "p_drb_100", "p_stl_100", "p_blk_100",
]
CORE_INT = ["off_rk", "def_rk", "tot_rk", "n_rapm", "n"]


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
    """cache-first: 命中最新归档直接返回; 否则线上抓取并落盘."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    if not force:
        cached = sorted(ARCHIVE_DIR.glob("epm_20*.html"))
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


def archive_html(html: str, game_dt: str) -> Path:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dst = ARCHIVE_DIR / f"epm_{game_dt}.html"
    if dst.exists() and dst.stat().st_size > 10000:
        return dst  # 已归档, 幂等跳过
    fd, tmp = tempfile.mkstemp(dir=ARCHIVE_DIR, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, dst)  # 原子写
    print(f"[archive] 原始页落盘 {dst}")
    return dst


def extract_stats(html: str) -> list[dict]:
    """从 SvelteKit 载荷提取 stats 数组 (JS 对象字面量 → JSON via node)."""
    key = "stats:["
    i = html.find(key)
    if i < 0:
        raise RuntimeError("未找到 stats 数组")
    j = i + len(key) - 1  # 指向 '['
    depth, end = 0, -1
    for k in range(j, len(html)):
        c = html[k]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = k
                break
    if end < 0:
        raise RuntimeError("stats 数组括号不匹配")
    arr_src = html[j:end + 1]

    node = _node_bin()
    script = (
        "let d;const s=require('fs').readFileSync(0,'utf8');"
        "eval('d='+s);process.stdout.write(JSON.stringify(d));"
    )
    out = subprocess.run(
        [node, "-e", script], input=arr_src, capture_output=True, text=True
    )
    if out.returncode != 0:
        raise RuntimeError(f"node 解析失败: {out.stderr[:500]}")
    return json.loads(out.stdout)


DDL = """
CREATE TABLE IF NOT EXISTS player_epm (
    nba_player_id   text        NOT NULL,
    br_player_id    varchar(32),
    player_name     text        NOT NULL,
    season          integer     NOT NULL,
    game_dt         date,
    team_id         bigint,
    team_alias      text,
    age             integer,
    position        text,
    epm_off         numeric,
    epm_def         numeric,
    epm_tot         numeric,
    epm_tot_change  numeric,
    off_rk          integer,
    def_rk          integer,
    tot_rk          integer,
    n_rapm          integer,
    n               integer,
    p_pct_start     numeric,
    p_t_poss_48     numeric,
    p_mp_48         numeric,
    p_usg           numeric,
    p_pts_100       numeric,
    p_tspct         numeric,
    p_efg           numeric,
    p_ast_100       numeric,
    p_tov_100       numeric,
    p_orb_100       numeric,
    p_drb_100       numeric,
    p_stl_100       numeric,
    p_blk_100       numeric,
    raw             jsonb       NOT NULL,
    source          text        DEFAULT 'dunksandthrees.com/epm',
    scraped_at      timestamp   DEFAULT now(),
    PRIMARY KEY (nba_player_id, season, source)
);
CREATE INDEX IF NOT EXISTS idx_epm_br_id  ON player_epm (br_player_id);
CREATE INDEX IF NOT EXISTS idx_epm_season ON player_epm (season);
CREATE INDEX IF NOT EXISTS idx_epm_tot    ON player_epm (season, epm_tot DESC);
"""


def upsert(rows: list[dict], dry_run: bool = False) -> tuple[int, int]:
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(DDL)

    # NBA 数字 id → BR id 映射
    cur.execute("SELECT nba_player_id, br_player_id FROM player_id_bridge")
    bridge = {str(a): b for a, b in cur.fetchall()}

    cols = (["nba_player_id", "br_player_id", "player_name", "season", "game_dt",
             "team_id", "team_alias", "age", "position",
             "epm_off", "epm_def", "epm_tot", "epm_tot_change",
             "off_rk", "def_rk", "tot_rk", "n_rapm", "n"]
            + CORE_NUM[4:]  # p_pct_start ... p_blk_100
            + ["raw"])

    values = []
    matched = 0
    for r in rows:
        nba_id = str(r.get("player_id"))
        br = bridge.get(nba_id)
        if br:
            matched += 1
        row = [
            nba_id, br, r.get("player_name"), r.get("season"), r.get("game_dt"),
            r.get("team_id"), r.get("team_alias"), r.get("age"), r.get("position"),
            r.get("off"), r.get("def"), r.get("tot"), r.get("tot_change"),
            r.get("off_rk"), r.get("def_rk"), r.get("tot_rk"),
            r.get("n_rapm"), r.get("n"),
        ] + [r.get(k) for k in CORE_NUM[4:]] + [json.dumps(r)]
        values.append(row)

    if dry_run:
        cur.close(); conn.close()
        return len(values), matched

    update_cols = [c for c in cols if c not in ("nba_player_id", "season")]
    set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
    set_clause += ", scraped_at=now()"
    sql = (f"INSERT INTO player_epm ({', '.join(cols)}) VALUES %s "
           f"ON CONFLICT (nba_player_id, season, source) DO UPDATE SET {set_clause}")
    psycopg2.extras.execute_values(cur, sql, values, page_size=200)
    conn.commit()
    n = cur.rowcount
    cur.close(); conn.close()
    return len(values), matched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略本地缓存重新抓取")
    ap.add_argument("--dry-run", action="store_true", help="只解析不写库")
    args = ap.parse_args()

    html = fetch_html(force=args.force)
    rows = extract_stats(html)
    game_dt = rows[0].get("game_dt") if rows else datetime.now().strftime("%Y-%m-%d")
    archive_html(html, game_dt)

    total, matched = upsert(rows, dry_run=args.dry_run)
    tag = "[dry-run] " if args.dry_run else ""
    print(f"{tag}解析 {total} 条 | BR 映射命中 {matched}/{total} "
          f"({matched * 100 // max(total, 1)}%) | season={rows[0]['season']} game_dt={game_dt}")
    if not args.dry_run:
        print("[ok] 已 upsert 到 player_epm")


if __name__ == "__main__":
    main()
