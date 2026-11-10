#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NBA 仓库统一入口（纯标准库）。

--list  打印来源清单与固定路径。
--check 校验每个来源路径是否仍存在并输出 OK / MISSING。

设计约束：只对固定绝对路径做 os.path.exists 单次检查，
绝不递归扫描大目录（外置盘 6TB 素材区会导致卡死 / exit 137）。
"""
import argparse
import os

NBA_ROOT = "/Volumes/12T/NBA"
R = NBA_ROOT + "/nba_desktop_omega_mac_migrate_2026-07-13"
W = "/Users/deocheng/WorkBuddy/2026-07-13-10-47-43"
P = NBA_ROOT + "/nba_analysis"

# 三个逻辑来源
CORE = [
    ("R 主仓库（唯一代码根）", R),
    ("W WorkBuddy 会话工作区", W),
    ("P 仓外报告产物（nba_analysis）", P),
]

# 盘根下 5 个未评估代码目录
UNREVIEWED = [
    ("FRA_SRB_QS 视频处理实验", NBA_ROOT + "/FRA_SRB_QS"),
    ("WeVisOne-VL 第三方开源", NBA_ROOT + "/WeVisOne-VL"),
    ("nba_bot", NBA_ROOT + "/nba_bot"),
    ("stream_download", NBA_ROOT + "/stream_download"),
    ("nba_analysis（同 P）", NBA_ROOT + "/nba_analysis"),
]

SOURCES = CORE + UNREVIEWED


def cmd_list():
    print("统一入口来源清单（固定绝对路径，不递归扫描）")
    print("\n[三个逻辑来源]")
    for label, path in CORE:
        print("  %-32s %s" % (label, path))
    print("\n[盘根 5 个未评估代码目录]")
    for label, path in UNREVIEWED:
        print("  %-32s %s" % (label, path))
    print("\n共 %d 条。明细见 workspace/README.md、workspace/sources.md。" % len(SOURCES))


def cmd_check():
    """仅对固定路径做 exists（单次 stat）：不递归、不读取目录内容。"""
    print("校验来源路径（--check，固定路径 exists 检查）")
    missing = 0
    for label, path in SOURCES:
        ok = os.path.exists(path)
        print("  %-8s %-32s %s" % ("OK" if ok else "MISSING", label, path))
        if not ok:
            missing += 1
    print("----")
    print("total=%d OK=%d MISSING=%d" % (len(SOURCES), len(SOURCES) - missing, missing))
    return 1 if missing else 0


def main():
    ap = argparse.ArgumentParser(
        description="NBA 仓库统一入口：列出 / 校验来源，只读固定路径、不递归扫描"
    )
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="打印来源清单与路径")
    group.add_argument(
        "--check", action="store_true",
        help="校验每个来源路径是否存在，输出 OK / MISSING",
    )
    args = ap.parse_args()
    if args.list:
        cmd_list()
        return 0
    return cmd_check()


if __name__ == "__main__":
    raise SystemExit(main())
