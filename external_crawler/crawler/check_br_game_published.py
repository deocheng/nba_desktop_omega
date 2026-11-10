#!/usr/bin/env python3
"""
check_br_game_published.py — 探测 BR 是否已发布某场比赛的 player gamelog 行。

背景
----
BR 的详细 box score / player gamelog 在比赛结束后往往滞后数小时才上线
（scoreboard 比分先出，box/gamelog 后出）。本脚本通过抓取一名该队球员的
gamelog/<season> 页，检查其中是否含目标 game_id 行，从而判断「现在爬有没有
意义」。避免在 BR 未发布时跑无效爬取（0 新行）。

输出（供自动化判定）:
  PUBLISHED    -> 目标 game_id 已出现在 gamelog 页，可以爬
  NOT_YET      -> 尚未发布

用法:
  python check_br_game_published.py <game_id> <sample_slug> [season]
  python check_br_game_published.py 202610220PHI udehjer01 2027
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(".").resolve()))


def main():
    if len(sys.argv) < 3:
        print("usage: check_br_game_published.py <game_id> <sample_slug> [season]",
              file=sys.stderr)
        sys.exit(2)
    game_id = sys.argv[1]
    sample = sys.argv[2]
    season = sys.argv[3] if len(sys.argv) > 3 else "2027"

    from common.browser import get_driver
    url = f"https://www.basketball-reference.com/players/{sample[0]}/{sample}/gamelog/{season}"
    drv = get_driver()
    drv.get(url)
    deadline = time.time() + 90
    renav = False
    while True:
        html = drv.page_source or ""
        if game_id in html:
            print("PUBLISHED")
            return
        if time.time() >= deadline:
            break
        if not renav and time.time() >= deadline - 45:
            renav = True
            try:
                drv.get(url)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(5)
    print("NOT_YET")


if __name__ == "__main__":
    main()
