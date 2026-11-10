#!/usr/bin/env python3
"""FIBA 每日报告滚动归档。

把自动化活动记录 memory.md 里「除最近 KEEP 条以外」的条目原文追加到
reports/archive/fiba_daily_report_<YYYY-MM>.md，然后从活动文件中删除。

设计要点
--------
- 确定性：纯文本按 "## " 段落切分，不做任何解释/改写，归档内容与原文字节一致。
- 幂等：条目数 <= KEEP 时什么都不做，直接退出 0。
- 原子：先写 .tmp 再 os.replace，中断不会留下半个文件。
- 安全：只动 memory.md 与 reports/archive/ 下的归档文件，不碰数据库、不碰爬虫脚本。

用法：
    python3 archive_daily_report.py            # 正常归档
    python3 archive_daily_report.py --dry-run  # 只看会归档什么，不写盘
    python3 archive_daily_report.py --keep 7   # 自定义保留条数（默认 5）
"""

from __future__ import annotations

import argparse
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(
    BASE, ".workbuddy/memory/automations/e962d9f0-c4a0-4dc4-a9e8-747f5b46584d/memory.md"
)
ARCHIVE_DIR = os.path.join(BASE, "reports/archive")

ENTRY_RE = re.compile(r"^##\s+(\d{4})-(\d{2})-\d{2}")


def split_entries(text: str):
    """返回 (头部, [(起始行号, 条目文本), ...])。"""
    lines = text.splitlines(keepends=True)
    starts = [i for i, l in enumerate(lines) if l.startswith("## ")]
    if not starts:
        return text, []
    head = "".join(lines[: starts[0]])
    entries = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(lines)
        entries.append((s, "".join(lines[s:e])))
    return head, entries


def entry_month(entry_text: str) -> str:
    m = ENTRY_RE.match(entry_text)
    if not m:
        return "unknown"
    return "%s-%s" % (m.group(1), m.group(2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=5, help="活动文件保留的最近条目数（默认 5）")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写盘")
    args = ap.parse_args()

    if not os.path.exists(LIVE):
        print("[archive] 找不到活动记录文件: %s" % LIVE)
        return 1

    text = open(LIVE, encoding="utf-8").read()
    head, entries = split_entries(text)
    total = len(entries)

    if total <= args.keep:
        print("[archive] 活动条目 %d <= 保留 %d，无需归档。" % (total, args.keep))
        return 0

    old = entries[: total - args.keep]
    keep = entries[total - args.keep :]

    buckets = {}
    for _, body in old:
        buckets.setdefault(entry_month(body), []).append(body)

    plan = ", ".join("%s×%d" % (m, len(v)) for m, v in sorted(buckets.items()))
    print("[archive] 活动条目 %d，将归档 %d 条（%s），保留最近 %d 条。"
          % (total, len(old), plan, args.keep))

    if args.dry_run:
        print("[archive] --dry-run，未写盘。")
        return 0

    if not os.path.exists(ARCHIVE_DIR):
        os.makedirs(ARCHIVE_DIR)

    for month, bodies in sorted(buckets.items()):
        path = os.path.join(ARCHIVE_DIR, "fiba_daily_report_%s.md" % month)
        exists = os.path.exists(path)
        tmp = path + ".tmp"
        with open(tmp, "a" if exists else "w", encoding="utf-8") as fh:
            if exists:
                fh.write("\n")
            else:
                fh.write(
                    "# FIBA 每日增量爬虫 · 每日运行报告归档（%s）\n\n"
                    "> 由 `fiba_scraper/archive_daily_report.py` 自动滚动归档。\n"
                    "> 内容为活动记录 memory.md 中过期条目的**原文**，未做改写。\n\n---\n\n"
                    % month
                )
            for b in bodies:
                fh.write(b if b.endswith("\n") else b + "\n")
        os.replace(tmp, path)
        print("[archive] 已追加 %d 条 -> %s" % (len(bodies), os.path.basename(path)))

    tmp_live = LIVE + ".tmp"
    with open(tmp_live, "w", encoding="utf-8") as fh:
        fh.write(head)
        for _, b in keep:
            fh.write(b if b.endswith("\n") else b + "\n")
    os.replace(tmp_live, LIVE)
    print("[archive] 活动文件已瘦身：%d -> %d 条。" % (total, len(keep)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
