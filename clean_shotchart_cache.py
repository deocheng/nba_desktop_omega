#!/usr/bin/env python3
"""clean_shotchart_cache.py — 核验入库后删除 br_players_shot 缓存 HTML。

安全前提：爬虫正常模式为 内存取数 → 存盘(缓存是副作用) → 内存解析 → 落库，
从不回读缓存文件（仅 --rework 模式读盘，属手动触发）。故删除缓存
对爬虫运行无任何影响。

删除条件：mtime 早于 NOW-GUARD_S（默认 3600 秒 = 1 小时）「且」
  解析出真实球数>0 「且」 DB 已有 (player_id=slug, season=year) → 已「经过库校验」，删。
  （0 球垃圾页永不入库、不属「经过库校验」，默认保留；显式 CLEAN_JUNK=1 才连它一起删。）
护栏：
  - 仅删 GUARD_S(默认 3600)秒前写入的文件，避免与爬虫正在写盘瞬间竞态；也保留 1 小时内缓存作回放/兜底缓冲。
  - DB 不可达 → 一律不删（安全优先）
"""
import os
import sys
import time
from pathlib import Path

PROJ = Path(os.environ.get("PROJ") or os.getcwd()).resolve()
os.chdir(PROJ)
for p in (PROJ, PROJ / "external_crawler" / "crawler", PROJ / "common"):
    sys.path.insert(0, str(p))

GUARD_S = int(os.environ.get("CLEAN_GUARD_S", "3600"))
CLEAN_JUNK = os.environ.get("CLEAN_JUNK", "0") != "0"

# 自解析 .env 的 DB_* 变量，不依赖环境变量注入
def load_db_config():
    cfg = {}
    envf = PROJ / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    return dict(
        host=cfg.get("DB_HOST", "localhost"),
        port=int(cfg.get("DB_PORT", "5432")),
        user=cfg.get("DB_USER", "postgres"),
        password=cfg.get("DB_PASSWORD", ""),
        dbname=cfg.get("DB_NAME", "nba"),
    )


from crawl_br_player_shot_chart import parse_shot_chart_html  # noqa: E402
import psycopg2  # noqa: E402


def db_has(conn, slug, season):
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM player_shot_chart WHERE player_id=%s AND season=%s LIMIT 1",
        (slug, season),
    )
    return cur.fetchone() is not None


def main():
    now = time.time()
    ARCH = PROJ / "raw_archive" / "br_players_shot"
    if not ARCH.exists():
        print(f"[clean] archive missing: {ARCH} -> skip")
        return 0
    files = list(ARCH.glob("*/*.html"))
    deleted_real = deleted_junk = kept = 0
    try:
        conn = psycopg2.connect(**load_db_config(), connect_timeout=10)
    except Exception as e:  # noqa: BLE001
        print(f"[clean] DB UNREACHABLE ({e}) -> delete nothing (safety)")
        return 0
    try:
        for f in files:
            slug = f.parent.name
            stem = f.stem
            if not stem.startswith("shooting_"):
                continue
            try:
                year = int(stem.split("_", 1)[1])
            except Exception:
                continue
            try:
                mtime = f.stat().st_mtime
            except Exception:
                continue
            if now - mtime < GUARD_S:
                kept += 1
                continue
            try:
                html = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                kept += 1
                continue
            recs = parse_shot_chart_html(html)
            if recs:
                if db_has(conn, slug, year):
                    try:
                        f.unlink()
                        deleted_real += 1
                    except Exception:
                        kept += 1
                else:
                    kept += 1  # parsed but not yet in DB (rare in-flight)
            else:
                if CLEAN_JUNK:
                    try:
                        f.unlink()
                        deleted_junk += 1
                    except Exception:
                        kept += 1
                else:
                    kept += 1
    finally:
        conn.close()
    print(
        f"[clean] scanned={len(files)} deleted_real(DB-confirmed)={deleted_real} "
        f"deleted_junk(0-shot)={deleted_junk} kept(in-flight/guarded)={kept}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
