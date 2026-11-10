#!/usr/bin/env python3
"""兼容 wrapper → bg="grid" 星环图。唯一实现：同目录 team_shot_radial.py
的 render(season, team, top_n, bg)。本文件只解析原 CLI + 调用 render 写文件，
不再含 631 行重复主体。
原用法: python star_grid.py 2026 OKC 5 out.html   (bg 固定 "grid")
缺省:   season=2026, team=OKC, top_n=5, out=同目录同名 .html
"""
import sys
from pathlib import Path

_BG = "grid"


def parse_cli(args):
    """按原 CLI 解析 season/team/top_n/out_path；bg 由本 wrapper 固定。"""
    season = int(args[0]) if len(args) > 0 else 2026
    team = args[1].upper() if len(args) > 1 else "OKC"
    top_n = int(args[2]) if len(args) > 2 else 5
    out = args[3] if len(args) > 3 else str(Path(__file__).with_suffix(".html"))
    return season, team, top_n, _BG, out


if __name__ == "__main__":
    from team_shot_radial import render  # 延迟导入：静态导入本 wrapper 无 DB 副作用

    season, team, top_n, bg, out_path = parse_cli(sys.argv[1:])
    html = render(season, team, top_n, bg)
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} for {team} {season} (top {top_n}, bg={bg})")
