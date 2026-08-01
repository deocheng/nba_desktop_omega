#!/usr/bin/env python3
"""dunksandthrees.com 历史 EPM 爬虫 (球员生涯 eskills, 2002→now) —— 免费获取全历史.

背景 / 为什么走球员页:
  官网 /epm 与 /epm/actual 免费只给**当前赛季**; 历史赛季 (?season=2002..2025)
  被付费墙锁 (303 → /subscribe?reason=locked-season)。
  但**球员个人页免费内嵌整段生涯逐年 EPM**: 载荷里的 `eskills:[{season,off,def,tot,...}]`
  每元素是一个赛季的完整预测性 EPM (90 字段, 与 /epm 同 schema)。
  实测可追溯到 2002 (= 2001-02, D&T 最早数据): Duncan/Kobe 2002-2016, LeBron 2004-2026。
  → 遍历全体球员页 (页面自带搜索索引共 2852 人, 含退役), 即可免费重建 2002–2026 全历史。

方法论同 nba-br-crawler skill (cache-first):
  抓取 → 每个球员页原始 HTML 落 raw_archive/dunksandthrees/players/{pid}.html (原子写)
  解析 → 抽 eskills 数组 (JS 字面量, node eval 转 JSON)
  入库 → 灌入 player_epm 表 (与 /epm 同表同 schema), 幂等 upsert; source 标记区分来源
         NBA 数字 id → BR id 走 player_id_bridge

用法:
  .venv/bin/python crawl_dunksandthrees_epm_history.py            # cache-first 全量 (2852 人)
  .venv/bin/python crawl_dunksandthrees_epm_history.py --limit 20 # 只跑前 20 人 (试跑)
  .venv/bin/python crawl_dunksandthrees_epm_history.py --force    # 忽略本地缓存重抓
  .venv/bin/python crawl_dunksandthrees_epm_history.py --min-season 2002 --max-season 2025
  .venv/bin/python crawl_dunksandthrees_epm_history.py --dry-run  # 只解析不写库
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psycopg2
import psycopg2.extras

BASE = "https://dunksandthrees.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
ROOT = Path(__file__).resolve().parent
ARCHIVE_DIR = ROOT / "raw_archive" / "dunksandthrees"
PLAYER_DIR = ARCHIVE_DIR / "players"
SOURCE = "dunksandthrees.com/player/eskills"

# 与 crawl_dunksandthrees_epm.py 保持一致的核心列
CORE_NUM = [
    "p_pct_start", "p_t_poss_48", "p_mp_48", "p_usg", "p_pts_100",
    "p_tspct", "p_efg", "p_ast_100", "p_tov_100", "p_orb_100",
    "p_drb_100", "p_stl_100", "p_blk_100",
]


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
    raise RuntimeError("node 未找到")


def _js_to_obj(src: str):
    node = _node_bin()
    script = ("let d;const s=require('fs').readFileSync(0,'utf8');"
              "eval('d='+s);process.stdout.write(JSON.stringify(d));")
    out = subprocess.run([node, "-e", script], input=src,
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"node 解析失败: {out.stderr[:300]}")
    return json.loads(out.stdout)


def _extract_balanced(html: str, key: str, start: int = 0):
    i = html.find(key, start)
    if i < 0:
        return None, -1
    j = i + len(key) - 1
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
                return html[j:k + 1], k
    return None, -1


def _http_get(url: str) -> str:
    try:
        from curl_cffi import requests as creq  # type: ignore
        r = creq.get(url, impersonate="chrome124", timeout=60,
                     allow_redirects=False)
        if r.status_code in (301, 302, 303):
            raise RuntimeError(f"redirect {r.status_code} -> {r.headers.get('location')}")
        return r.text
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        return urllib.request.urlopen(req, timeout=60).read().decode("utf-8")


def get_player_index() -> list[dict]:
    """从一个球员页的搜索索引 (resolve(1)) 提取全体球员 (含退役)."""
    seed = PLAYER_DIR / "201939.html"
    html = seed.read_text(encoding="utf-8") if seed.exists() else _http_get(f"{BASE}/player/201939")
    i = html.find("resolve(1")
    if i < 0:
        raise RuntimeError("未找到球员搜索索引 resolve(1)")
    a = html.find("[[", i)
    seg, _ = _extract_balanced(html, "[", a + 1)  # inner array starts at a+1
    # a points to '[[', inner array begins at a+1
    seg, _ = _extract_balanced(html[a + 1:], "[")
    data = _js_to_obj(seg)
    return [p for p in data if p.get("pid")]


def fetch_player_html(pid: int, force: bool = False) -> str | None:
    PLAYER_DIR.mkdir(parents=True, exist_ok=True)
    dst = PLAYER_DIR / f"{pid}.html"
    if not force and dst.exists() and dst.stat().st_size > 5000:
        return dst.read_text(encoding="utf-8")
    try:
        html = _http_get(f"{BASE}/player/{pid}")
    except Exception as e:
        print(f"  [warn] pid={pid} 抓取失败: {e}")
        return None
    if "eskills:[" not in html:
        # 仍归档 (可能真无 EPM), 但返回内容供上层判断
        pass
    fd, tmp = tempfile.mkstemp(dir=PLAYER_DIR, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, dst)
    return html


def extract_eskills(html: str) -> list[dict]:
    seg, _ = _extract_balanced(html, "eskills:[")
    if not seg or seg == "[]":
        return []
    return _js_to_obj(seg)


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


def build_rows(records: list[dict], bridge: dict,
               min_s: int, max_s: int) -> list[list]:
    rows = []
    for r in records:
        s = r.get("season")
        if s is None or s < min_s or s > max_s:
            continue
        nba_id = str(r.get("player_id"))
        br = bridge.get(nba_id)
        row = [
            nba_id, br, r.get("player_name"), s, r.get("game_dt"),
            r.get("team_id"), r.get("team_alias"), r.get("age"), r.get("position"),
            r.get("off"), r.get("def"), r.get("tot"), r.get("tot_change"),
            r.get("off_rk"), r.get("def_rk"), r.get("tot_rk"),
            r.get("n_rapm"), r.get("n"),
        ] + [r.get(k) for k in CORE_NUM] + [json.dumps(r), SOURCE]
        rows.append(row)
    return rows


COLS = (["nba_player_id", "br_player_id", "player_name", "season", "game_dt",
         "team_id", "team_alias", "age", "position",
         "epm_off", "epm_def", "epm_tot", "epm_tot_change",
         "off_rk", "def_rk", "tot_rk", "n_rapm", "n"]
        + CORE_NUM + ["raw", "source"])


def upsert(cur, rows: list[list]):
    if not rows:
        return
    update_cols = [c for c in COLS if c not in ("nba_player_id", "season")]
    set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
    set_clause += ", scraped_at=now()"
    sql = (f"INSERT INTO player_epm ({', '.join(COLS)}) VALUES %s "
           f"ON CONFLICT (nba_player_id, season, source) DO UPDATE SET {set_clause}")
    psycopg2.extras.execute_values(cur, sql, rows, page_size=500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑 N 个球员 (0=全部, 与 --offset 配合切片)")
    ap.add_argument("--offset", type=int, default=0, help="从第 N 个球员开始 (0-based, 用于并行分块)")
    ap.add_argument("--force", action="store_true", help="忽略本地缓存重抓")
    ap.add_argument("--dry-run", action="store_true", help="只解析不写库")
    ap.add_argument("--min-season", type=int, default=2002)
    ap.add_argument("--max-season", type=int, default=2026)
    ap.add_argument("--sleep", type=float, default=1.2, help="每次线上抓取间隔秒")
    args = ap.parse_args()

    conn = db_conn()
    cur = conn.cursor()
    cur.execute(DDL)
    cur.execute("SELECT nba_player_id, br_player_id FROM player_id_bridge")
    bridge = {str(a): b for a, b in cur.fetchall()}
    conn.commit()

    index = get_player_index()
    if args.offset:
        index = index[args.offset:]
    if args.limit:
        index = index[:args.limit]
    print(f"[index] 球员总数 {len(index)} (offset={args.offset}) | season {args.min_season}-{args.max_season}")

    total_rows = matched = players_ok = players_empty = players_fail = 0
    for n, p in enumerate(index, 1):
        pid = p["pid"]
        dst = PLAYER_DIR / f"{pid}.html"
        was_cached = dst.exists() and dst.stat().st_size > 5000 and not args.force
        html = fetch_player_html(pid, force=args.force)
        if html is None:
            players_fail += 1
            continue
        try:
            records = extract_eskills(html)
        except Exception as e:
            print(f"  [warn] pid={pid} 解析失败: {e}")
            players_fail += 1
            continue
        if not records:
            players_empty += 1
        else:
            rows = build_rows(records, bridge, args.min_season, args.max_season)
            matched += sum(1 for r in rows if r[1])
            total_rows += len(rows)
            if not args.dry_run and rows:
                upsert(cur, rows)
                conn.commit()
            players_ok += 1
        if n % 100 == 0:
            print(f"  [{n}/{len(index)}] rows={total_rows} ok={players_ok} "
                  f"empty={players_empty} fail={players_fail}")
        if not was_cached and not args.force:
            time.sleep(args.sleep + random.uniform(0, 0.6))
        elif args.force:
            time.sleep(args.sleep + random.uniform(0, 0.6))

    cur.close(); conn.close()
    tag = "[dry-run] " if args.dry_run else ""
    print(f"{tag}完成 | 球员 有EPM={players_ok} 无EPM={players_empty} 失败={players_fail}")
    print(f"{tag}写入行数 {total_rows} | BR 映射命中 {matched}/{total_rows} "
          f"({matched * 100 // max(total_rows, 1)}%)")


if __name__ == "__main__":
    main()
