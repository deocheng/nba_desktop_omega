#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_markdown_cache.py
==========================
一次性补齐：把 raw_archive/br_teams_franchise/ 下已有的 *.html 缓存，
另存一份可读 *.md 副本（纯本地 HTML→MD，零线上请求）。

复用 crawl_br_team_franchise_pages 里的 html_to_markdown / save_markdown，
保证与爬虫在线落盘的产物完全一致。已存在且非空的 .md 跳过。
"""
import glob
import os
import sys

#: 仓库根（脚本已收敛到 scripts/oneoff/，自身目录不再是仓库根）
#: 🔴 上溯**三层**：scripts/oneoff/x.py → oneoff → scripts → 仓库根
REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HERE = REPO_DIR
sys.path.insert(0, HERE)

import crawl_br_team_franchise_pages as m  # noqa: E402

RAW = m.RAW



def main() -> int:
    if not os.path.isdir(RAW):
        print("缓存目录不存在:", RAW)
        return 1
    total = 0
    skipped = 0
    failed = 0
    for slug_dir in sorted(os.listdir(RAW)):
        sd = os.path.join(RAW, slug_dir)
        if not os.path.isdir(sd):
            continue
        for html_path in sorted(glob.glob(os.path.join(sd, "*.html"))):
            page = os.path.basename(html_path)[:-5]  # 去掉 .html
            md_path = os.path.join(sd, page + ".md")
            if os.path.exists(md_path) and os.path.getsize(md_path) > 0:
                skipped += 1
                continue
            with open(html_path, "r", encoding="utf-8") as fh:
                html = fh.read()
            if not m._is_real_html(html):
                continue
            try:
                m.save_markdown(slug_dir, page, html)
                total += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print("FAIL", html_path, "->", exc)
    print(f"done: 新增 md={total}  跳过已存在={skipped}  失败={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
