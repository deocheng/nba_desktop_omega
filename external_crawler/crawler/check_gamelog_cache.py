#!/usr/bin/env python3
"""gamelog 本地缓存体检：一眼看清每季缓存到底存没存全。

背景
----
缓存的定位（2026-08-07 用户确认）：**缓存是「修正补充」的缓冲，不是 DB 的完整性镜像。**
DB 是权威源 ——
  * DB 数据没问题 → 缓存文件缺失 / 空壳都是**合理的**，不是 bug；全量入库后缓存可删。
  * DB 数据有问题 → 才拿缓存去修正补充（``--rework`` 重放）。

``crawl_br_gamelog.py`` 历史上只在整季爬完最后一刻写一次缓存，被打断就丢；
已于 2026-08-07 改为每球员实时追加 ``gamelog_<season>.part.jsonl`` 分片、崩溃零丢失。
已于 2026-08-08 起新增 **HTML 轨道**（``<cache_dir>/html/<season>/<player_id>.html``）：抓取成功后同时落盘
原始页面，使「改解析器后免重爬重解」能恢复丢字段（如季后赛 minutes）。本工具新增 ``HTML球员`` 列
用于核对双轨覆盖——``HTML球员`` < ``球员`` 表示该季仅有旧 JSON 缓存、缺原始 HTML（需重抓一次补齐）。

本脚本用途：一眼看清每季缓存的存全程度，并（``--with-db`` 时）对照 DB 判定：
  * DB 完整 + 缓存空壳/缺失 → 正常（缓存可选、可删，无需动作）；
  * DB 不完整 + 有缓存     → 缓存可用于修正；
  * DB 不完整 + 无缓存     → 真缺口，需重爬。

用法
----
    python3 check_gamelog_cache.py                     # 体检默认缓存目录
    python3 check_gamelog_cache.py --cache-dir <DIR>   # 指定目录
    python3 check_gamelog_cache.py --with-db           # 顺带对比 DB 实际行数

退出码
------
    0 = 全部有效；1 = 存在空壳或残缺季（可用于 CI / 门禁）
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "gamelog_cache")

# 低于该球员数视为"残缺"（正常一季 NBA 有 300~600 名出场球员；
# 早期赛季球队少，故阈值取得较宽松，仅用于提示而非硬判定）。
THIN_PLAYER_THRESHOLD = 60


def scan_cache(cache_dir: str) -> list[dict]:
    """扫描缓存目录，返回每季的统计。

    Returns:
        列表，每项形如
        ``{"season": 1996, "bytes": 47, "players": 0, "games": 0,
           "status": "EMPTY", "part_lines": 0}``。
    """
    rows: list[dict] = []
    pattern = os.path.join(cache_dir, "gamelog_*.json")
    for path in sorted(glob.glob(pattern)):
        name = os.path.basename(path)
        m = re.match(r"gamelog_(\d{4})\.json$", name)
        if not m:
            continue  # 跳过 .tmp / .part.jsonl 等非主缓存文件
        season = int(m.group(1))

        size = os.path.getsize(path)
        players = games = 0
        status = "OK"
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            plist = (data or {}).get("players") or []
            if not isinstance(plist, list):
                plist = []
            players = len(plist)
            games = sum(len(p.get("games") or [])
                        for p in plist if isinstance(p, dict))
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            status = f"CORRUPT({type(exc).__name__})"

        if status == "OK":
            if players == 0:
                status = "EMPTY"          # 空壳：文件在，数据没有
            elif players < THIN_PLAYER_THRESHOLD:
                status = "THIN"           # 残缺：明显不足一季规模

        # 遗留分片（上次被打断、尚未并入主缓存）
        part_path = os.path.join(cache_dir, f"gamelog_{season}.part.jsonl")
        part_lines = 0
        if os.path.exists(part_path):
            try:
                with open(part_path, "r", encoding="utf-8") as fh:
                    part_lines = sum(1 for line in fh if line.strip())
            except OSError:
                part_lines = -1

        # HTML 轨道(双轨): 统计 <cache_dir>/html/<season>/ 下已落盘的原始页面数
        html_dir = os.path.join(cache_dir, "html", str(season))
        html_players = 0
        if os.path.isdir(html_dir):
            for first_dir in os.listdir(html_dir):
                d = os.path.join(html_dir, first_dir)
                if not os.path.isdir(d):
                    continue
                for fn in os.listdir(d):
                    if fn.endswith(".html"):
                        fp = os.path.join(d, fn)
                        try:
                            if os.path.getsize(fp) > 0:
                                html_players += 1
                        except OSError:
                            pass

        rows.append({"season": season, "bytes": size, "players": players,
                     "games": games, "status": status, "part_lines": part_lines,
                     "html_players": html_players})
    return rows


def fetch_db_counts(seasons: list[int]) -> dict[int, tuple[int, int]]:
    """取 DB 中各季 player_gamelog 的 (行数, 球员数)，失败则返回空 dict。"""
    if not seasons:
        return {}
    try:
        sys.path.insert(0, os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..")))
        import psycopg2  # noqa: WPS433
        from crawl_br_gamelog import DB_CONFIG  # 复用同一套连接配置
    except Exception as exc:  # pragma: no cover - 环境相关
        print(f"[warn] 无法连接 DB，跳过对比: {exc}", file=sys.stderr)
        return {}

    out: dict[int, tuple[int, int]] = {}
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(
            "SELECT season, count(*), count(DISTINCT br_player_id) "
            "FROM player_gamelog WHERE season = ANY(%s) GROUP BY 1",
            (seasons,),
        )
        for season, rows, players in cur.fetchall():
            out[int(season)] = (int(rows), int(players))
        cur.close()
        conn.close()
    except Exception as exc:  # pragma: no cover - 环境相关
        print(f"[warn] DB 查询失败，跳过对比: {exc}", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="gamelog 本地缓存体检")
    ap.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR,
                    help=f"缓存目录（默认 {DEFAULT_CACHE_DIR}）")
    ap.add_argument("--with-db", action="store_true",
                    help="顺带对比 DB 中各季实际行数/球员数")
    args = ap.parse_args()

    if not os.path.isdir(args.cache_dir):
        print(f"缓存目录不存在: {args.cache_dir}")
        return 1

    rows = scan_cache(args.cache_dir)
    if not rows:
        print(f"缓存目录为空: {args.cache_dir}")
        return 1

    db = fetch_db_counts([r["season"] for r in rows]) if args.with_db else {}

    header = f"{'季':<6}{'状态':<10}{'球员':>7}{'场次':>9}{'体积':>12}{'遗留分片':>9}{'HTML球员':>9}"
    if db:
        header += f"{'DB行数':>10}{'DB球员':>8}"
    print(f"缓存目录: {args.cache_dir}")
    print(header)
    print("-" * len(header))

    for r in rows:
        line = (f"{r['season']:<6}{r['status']:<10}{r['players']:>7,}"
                f"{r['games']:>9,}{r['bytes']:>12,}"
                f"{(r['part_lines'] or 0):>9}{r['html_players']:>9,}")
        if db:
            d_rows, d_players = db.get(r["season"], (0, 0))
            line += f"{d_rows:>10,}{d_players:>8,}"
        print(line)

    ok = [r for r in rows if r["status"] == "OK"]
    # 按用户模型：缓存是修正缓冲，DB 完整时缺失/空壳均合理。
    # 仅以下算「真问题」：① 文件损坏(CORRUPT)；② 有 --with-db 且 DB 也空(真缺口)。
    bad = [r for r in rows if r["status"].startswith("CORRUPT")]
    real_gap = []
    if args.with_db:
        for r in rows:
            if r["status"] in ("EMPTY", "THIN"):
                d_rows, _ = db.get(r["season"], (0, 0))
                if d_rows == 0:
                    real_gap.append(r)  # 缓存空 + DB 也空 → 真缺口
    bad += real_gap
    optional = [r for r in rows if r["status"] in ("EMPTY", "THIN") and r not in bad]

    print("-" * len(header))
    print(f"合计 {len(rows)} 季  |  有效 {len(ok)}  |  可选(空壳/缺失,DB完整) {len(optional)}  |  真问题 {len(bad)}")
    if optional:
        for tag in ("EMPTY", "THIN"):
            hit = [str(r["season"]) for r in optional if r["status"] == tag]
            if hit:
                label = "空壳(players=[])" if tag == "EMPTY" else "残缺(球员数偏少)"
                print(f"  {label}: {' '.join(hit)}  → DB 完整, 缓存可删(可选)")
    if real_gap:
        hit = [str(r["season"]) for r in real_gap]
        print(f"  真缺口(DB与缓存皆空): {' '.join(hit)}  → 需重爬")
    corrupt = [str(r["season"]) for r in rows if r["status"].startswith("CORRUPT")]
    if corrupt:
        print(f"  损坏: {' '.join(corrupt)}  → 检查半截写入")
    if not bad:
        print("\n结论: 无真问题。空壳/缺失缓存对应的季 DB 均完整（缓存本就是可选修正缓冲）。")
    else:
        print("\n提示: 仅 CORRUPT 或 DB 也空的季才是真问题；其余空壳缓存 DB 完整即可删。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
