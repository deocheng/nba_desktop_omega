#!/usr/bin/env python3
"""
dump_br_boxscore_players.py — 抓单场 BR box score，导出该场两队出场球员 (name, br_player_id, team) TSV。

背景
----
BR 联赛 per_game 聚合页在比赛夜后不一定立即滚动更新（2026-10-23 实测：
10-22 打完的 CLE@PHI / DEN@OKC 仍不出现在 NBA_2027_per_game.html，仍是旧
的 322 人/28 队）。但 box score 页在比赛一结束即上线，是「本场确切出场名单」
的权威源。本脚本从 box score 解析两队球员 slug，喂给 crawl_br_gamelog.py
--players-file，针对性补爬单场 gamelog（避免全量 58 分钟重跑）。

数据源: https://www.basketball-reference.com/boxscores/{game_id}.html
        game_id = YYYYMMDD + 主队 3 字母缩写（如 202610220PHI）
通道:   common.browser（UC 无头，与 gamelog 爬虫同通道；CF 轮询自愈）
输出:   TSV，每行 name\tbr_player_id\tteam；按 slug 去重。

用法:
  python dump_br_boxscore_players.py --game-id 202610220PHI --out /tmp/bs_202610220PHI.tsv
"""
import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

BR_BASE = "https://www.basketball-reference.com"
_SLUG_RE = re.compile(r"/players/[a-z]/([A-Za-z0-9]+)\.html")
_BOX_RE = re.compile(r'box_([A-Z]{3})_(basic|advanced)')


def fetch_page(url: str, poll_seconds: int = 90) -> str:
    """Fetch a fully-rendered BR box score via the shared driver (UC backend).

    Same CF-clear-in-place polling strategy as dump_br_league_players.
    """
    from common.browser import get_driver
    drv = get_driver()
    drv.get(url)
    deadline = time.time() + poll_seconds
    renavigated = False
    while True:
        html = drv.page_source or ""
        # box score 表 id 形如 box_PHI_basic；CF 挑战页不含这些
        if 'box_' in html and ('line_score' in html or 'boxscores' in html):
            return html
        if time.time() >= deadline:
            return html
        if not renavigated and time.time() >= deadline - poll_seconds / 2:
            renavigated = True
            try:
                drv.get(url)
            except Exception:  # noqa: BLE001 - best-effort
                pass
        time.sleep(5)


def parse_players(html: str) -> list:
    """Parse both teams' player rows from the box score (basic tables).

    BR wraps box-score tables in HTML comments in raw source, but after JS
    execution (real browser) they appear as live DOM elements. To be safe we
    strip comment markers before parsing.
    """
    from bs4 import BeautifulSoup
    html_clean = html.replace("<!--", "").replace("-->", "")
    soup = BeautifulSoup(html_clean, "html.parser")
    out = []
    seen = set()
    for table in soup.find_all("table"):
        tid = table.get("id", "") or ""
        m = _BOX_RE.match(tid)
        if not m:
            continue
        team = m.group(1)
        tbody = table.find("tbody")
        if not tbody:
            continue
        for row in tbody.find_all("tr"):
            cls = row.get("class", []) or []
            if "thead" in cls or "over_header" in cls:
                continue
            player_td = row.find("td", attrs={"data-stat": "player"})
            if not player_td:
                continue
            a = player_td.find("a", href=_SLUG_RE)
            if not a:
                # 非链接行（如 "Team Totals" 或 DNP 无链接）——跳过
                continue
            mslug = _SLUG_RE.search(a.get("href", ""))
            if not mslug:
                continue
            slug = mslug.group(1)
            name = a.get_text(strip=True)
            if slug in seen:
                continue
            seen.add(slug)
            out.append((name, slug, team))
    return out


def main():
    ap = argparse.ArgumentParser(description="导出 BR box score 两队球员清单 TSV")
    ap.add_argument("--game-id", type=str, required=True,
                    help="BR game_id，如 202610220PHI (YYYYMMDD+主队缩写)")
    ap.add_argument("--out", type=str, default=None,
                    help="输出 TSV 路径 (默认 /tmp/bs_<game_id>.tsv)")
    ap.add_argument("--dry-run", action="store_true",
                    help="只抓取解析并打印统计，不写文件")
    args = ap.parse_args()

    out = args.out or f"/tmp/bs_{args.game_id}.tsv"
    url = f"{BR_BASE}/boxscores/{args.game_id}.html"
    print(f"fetch: {url}", flush=True)

    html = fetch_page(url)
    if not html:
        print("ERROR: 空页面（浏览器通道失败）", file=sys.stderr)
        sys.exit(1)
    if "box_" not in html:
        head = html[:200].replace("\n", " ")
        print(f"ERROR: 页面无 box_ 表（CF 挑战/404/重定向？）: {head}...",
              file=sys.stderr)
        sys.exit(2)

    players = parse_players(html)
    print(f"parsed: {len(players)} 名球员 (game {args.game_id})")
    if not players:
        print("ERROR: 解析到 0 名球员", file=sys.stderr)
        sys.exit(3)

    teams = {}
    for _, _, t in players:
        teams[t] = teams.get(t, 0) + 1
    print(f"teams: {sorted(teams.items())}")

    if args.dry_run:
        for name, slug, team in players[:12]:
            print(f"  {name}\t{slug}\t{team}")
        print("  ... (dry-run, 未写文件)")
        return

    with open(out, "w", encoding="utf-8") as fh:
        for name, slug, team in players:
            fh.write(f"{name}\t{slug}\t{team}\n")
    print(f"written: {out}")


if __name__ == "__main__":
    main()
