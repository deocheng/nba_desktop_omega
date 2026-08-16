#!/usr/bin/env python3
"""gamelog 双轨缓存冷归档工具 (2026-08-11, 自包含, 仅依赖标准库)。

把 gamelog_cache 每季的 JSON 轨道(gamelog_<season>.json + .part.jsonl) 与
HTML 原始页轨道(html/<season>/) **复制**到冷归档区 raw_archive/gamelog/<season>/，
作为「以防万一」的额外副本(本地仍保留)。可选 --enforce 按阈值把最老季**移动**
到冷档腾空间(不删除)。

设计：本工具刻意不 import crawl_br_gamelog(其会触发 common 重链, 易 OOM)，纯标准库
实现，可在任意 python 直接跑。归档逻辑与 crawl_br_gamelog 内的 archive_season_cold /
enforce_overflow_policy 保持一致(双轨皆归档, 复制/移动不删除)。
"""
import argparse
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))   # external_crawler/crawler
PROJ = os.path.dirname(HERE)                          # external_crawler
ROOT = os.path.dirname(PROJ)                           # 项目根
RAW_ARCHIVE_ROOT = os.path.join(ROOT, "raw_archive", "gamelog")
CACHE_OVERFLOW_GB = float(os.environ.get("CACHE_OVERFLOW_GB", "20"))
ARCHIVE_ON_OVERFLOW = os.environ.get("ARCHIVE_ON_OVERFLOW", "1") == "1"
DEFAULT_CACHE_DIR = os.path.join(HERE, "gamelog_cache")


def _cache_size_bytes(path: str) -> int:
    total = 0
    try:
        for root, _d, files in os.walk(path):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _count_files(path: str) -> int:
    n = 0
    try:
        for _root, _d, files in os.walk(path):
            n += len(files)
    except OSError:
        pass
    return n


def archive_season_cold(season: int, cache_dir: str, raw_root: str = RAW_ARCHIVE_ROOT) -> bool:
    """本季双轨(JSON + HTML)复制到冷归档。已归档则幂等跳过。返回是否新归档。"""
    if not ARCHIVE_ON_OVERFLOW:
        return False
    src_html = os.path.join(cache_dir, "html", str(season))
    src_json = os.path.join(cache_dir, f"gamelog_{season}.json")
    src_part = os.path.join(cache_dir, f"gamelog_{season}.part.jsonl")
    dst = os.path.join(raw_root, str(season))
    dst_html = os.path.join(dst, "html")
    src_html_n = _count_files(src_html)
    dst_html_n = _count_files(dst_html)
    dst_has_json = os.path.exists(os.path.join(dst, f"gamelog_{season}.json"))
    # 智能跳过：已归档且 html 已追平源(或源本就无 html) → 视为完整, 跳过。
    # 源后续补齐 html 时(dst_html_n < src_html_n)会刷新补全, 不漏归档。
    if dst_has_json and (src_html_n == 0 or dst_html_n >= src_html_n):
        return False
    have = src_html_n > 0 or os.path.exists(src_json) or os.path.exists(src_part)
    if not have:
        return False
    try:
        os.makedirs(dst, exist_ok=True)
        if os.path.isdir(src_html):
            shutil.copytree(src_html, os.path.join(dst, "html"), dirs_exist_ok=True)
        for src in (src_json, src_part):
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dst, os.path.basename(src)))
        print(f"    [冷归档] 季 {season} 双轨已复制到 {dst}")
        return True
    except OSError as exc:
        print(f"    [冷归档] 季 {season} 失败: {exc}", file=sys.stderr)
        return False


def enforce_overflow_policy(cache_dir: str, raw_root: str = RAW_ARCHIVE_ROOT) -> None:
    """本地缓存超阈值时, 把最老季双轨 MOVE 到冷归档腾空间(不删除)。"""
    if not ARCHIVE_ON_OVERFLOW:
        return
    threshold = CACHE_OVERFLOW_GB * 1_000_000_000
    try:
        if _cache_size_bytes(cache_dir) <= threshold:
            return
    except OSError:
        return
    html_root = os.path.join(cache_dir, "html")
    seasons: list[int] = []
    if os.path.isdir(html_root):
        for name in os.listdir(html_root):
            if name.isdigit():
                seasons.append(int(name))
    for fn in os.listdir(cache_dir):
        m = re.match(r"gamelog_(\d{4})\.json$", fn)
        if m and int(m.group(1)) not in seasons:
            seasons.append(int(m.group(1)))
    seasons.sort()
    moved = 0
    for season in seasons:
        if _cache_size_bytes(cache_dir) <= threshold:
            break
        dst_season = os.path.join(raw_root, str(season))
        if os.path.isdir(dst_season) and any(os.scandir(dst_season)):
            continue
        try:
            os.makedirs(dst_season, exist_ok=True)
            src_html = os.path.join(html_root, str(season))
            if os.path.isdir(src_html):
                shutil.move(src_html, os.path.join(dst_season, "html"))
            for fn in (f"gamelog_{season}.json", f"gamelog_{season}.part.jsonl"):
                src = os.path.join(cache_dir, fn)
                if os.path.exists(src):
                    shutil.move(src, os.path.join(dst_season, fn))
            print(f"    [溢出归档] 季 {season} 双轨已移至 {dst_season} (不删除)")
            moved += 1
        except OSError as exc:
            print(f"    [溢出归档] 季 {season} 失败: {exc}", file=sys.stderr)
            break
    if moved:
        print(f"    [溢出归档] 共迁移 {moved} 季")


def list_seasons(cache_dir: str) -> list[int]:
    seasons: set[int] = set()
    html_root = os.path.join(cache_dir, "html")
    if os.path.isdir(html_root):
        for n in os.listdir(html_root):
            if n.isdigit():
                seasons.add(int(n))
    for fn in os.listdir(cache_dir):
        m = re.match(r"gamelog_(\d{4})\.json$", fn)
        if m:
            seasons.add(int(m.group(1)))
    return sorted(seasons)


def main() -> int:
    ap = argparse.ArgumentParser(description="gamelog 双轨缓存冷归档(自包含)")
    ap.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR,
                    help=f"源缓存目录(默认 {DEFAULT_CACHE_DIR})")
    ap.add_argument("--raw-archive-dir", default=None,
                    help="冷归档根目录(默认 项目根/raw_archive/gamelog)")
    ap.add_argument("--enforce", action="store_true",
                    help="额外执行溢出迁移(最老季移到冷档腾空间, 不删除)")
    args = ap.parse_args()

    raw_root = args.raw_archive_dir or RAW_ARCHIVE_ROOT
    if not os.path.isdir(args.cache_dir):
        print(f"缓存目录不存在: {args.cache_dir}")
        return 1
    seasons = list_seasons(args.cache_dir)
    if not seasons:
        print("缓存目录无已缓存季")
        return 0

    print(f"源缓存: {args.cache_dir}")
    print(f"冷归档: {raw_root}")
    print(f"待归档季数: {len(seasons)}")
    copied = 0
    for s in seasons:
        if archive_season_cold(s, args.cache_dir, raw_root):
            copied += 1
    print(f"新归档季: {copied} (已存在则幂等跳过)")

    if args.enforce:
        enforce_overflow_policy(args.cache_dir, raw_root)

    print("完成。冷归档为额外副本, 本地 gamelog_cache 不受影响(仍可秒级 rework)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
