#!/usr/bin/env python3
"""检查指定目录下 *.html 的单文件体积，超过阈值则告警。

仅扫描显式给出的目录本身（非递归，绝不遍历全盘 / 外置盘）。
默认检查仓库根与 frontend/；返回码 1 表示检出超标文件。
"""
import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIRS = [REPO_ROOT, os.path.join(REPO_ROOT, "frontend")]


def iter_html(directory):
    """产出 directory 目录下（非递归）每个 *.html 的 (绝对路径, 字节数)。"""
    try:
        names = sorted(os.listdir(directory))
    except FileNotFoundError:
        return
    for name in names:
        if not name.lower().endswith(".html"):
            continue
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        yield path, os.path.getsize(path)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="检查指定目录下 *.html 单文件体积是否超过阈值（不递归子目录）。"
    )
    parser.add_argument(
        "dirs",
        nargs="*",
        default=None,
        help="要检查的目录列表；默认：仓库根与 frontend/",
    )
    parser.add_argument(
        "--max-mb",
        type=float,
        default=2.0,
        help="单文件体积上限（MB），默认 2.0",
    )
    args = parser.parse_args(argv)

    if args.max_mb <= 0:
        parser.error("--max-mb 必须为正数")

    dirs = args.dirs if args.dirs else DEFAULT_DIRS
    limit = args.max_mb * 1024 * 1024
    oversized = []
    checked = 0

    for directory in dirs:
        for path, size in iter_html(directory):
            checked += 1
            if size > limit:
                oversized.append((path, size))

    print(
        f"[check_report_size] 阈值 {args.max_mb:.2f} MB | "
        f"扫描目录 {len(dirs)} 个 | 检查 .html 文件 {checked} 个"
    )
    if not oversized:
        print("[check_report_size] OK：无超标文件")
        return 0

    print(f"[check_report_size] FAIL：{len(oversized)} 个文件超过 {args.max_mb:.2f} MB：")
    for path, size in oversized:
        print(f"  {size / 1024 / 1024:8.2f} MB  {path}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
