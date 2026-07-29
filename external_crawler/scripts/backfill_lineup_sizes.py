#!/usr/bin/env python3
"""backfill_lineup_sizes.py — 本地重放所有已存 lineup 归档 HTML，
用新版解析器（5/4/3/2-man + 季后赛）补齐 player_lineups 行。

免爬：只读 raw_archive/br_players/{slug}/lineups_{year}.html，
不触碰任何 BR 请求、不依赖 Chrome。

用法:
    .venv/bin/python external_crawler/scripts/backfill_lineup_sizes.py [--dry-run] [--limit N]
"""
import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from external_crawler.crawler.crawl_br_player_lineup import PlayerLineupCrawler  # noqa: E402


def iter_archive_htmls(root: Path):
    """yield (slug, year, path) for every lineups_*.html under root/{slug}/."""
    for html in sorted(root.glob("*/lineups_*.html")):
        slug = html.parent.name
        stem = html.stem  # lineups_2024
        ypart = stem.split("_")[-1]
        if not ypart.isdigit():
            continue
        yield slug, int(ypart), html


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                   help="只枚举文件，不重放、不写库")
    ap.add_argument("--limit", type=int, default=None,
                   help="最多处理 N 个文件（抽样验证）")
    args = ap.parse_args()

    root = REPO / "raw_archive" / "br_players"
    crawler = PlayerLineupCrawler()
    files = list(iter_archive_htmls(root))
    if args.limit:
        files = files[: args.limit]
    total = len(files)
    print(f"[sweep] 发现 {total} 个 lineup 归档 HTML（root={root}）")
    if args.dry_run:
        for slug, year, _ in files[:5]:
            print(f"  would rework {slug}/{year}")
        print(f"[sweep] dry-run 完成，共 {total} 个待重放")
        return

    t0 = time.time()
    grand = 0
    done = 0
    for i, (slug, year, path) in enumerate(files, 1):
        try:
            n = crawler.rework_from_archive(slug, year)
            grand += n
        except Exception as e:  # noqa: BLE001
            print(f"[sweep][ERR] {slug}/{year}: {type(e).__name__}: {e}")
            n = 0
        done += 1
        if i % 100 == 0 or i == total:
            el = time.time() - t0
            print(f"[sweep] {done}/{total}  rework 完成，累计 upsert {grand} 行 "
                  f"（{el:.1f}s，{el/max(1,done):.2f}s/文件）")
    el = time.time() - t0
    print(f"[sweep] DONE {done}/{total} 文件，累计 upsert {grand} 行，耗时 {el:.1f}s")


if __name__ == "__main__":
    main()
