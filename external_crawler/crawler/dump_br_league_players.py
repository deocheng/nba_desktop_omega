#!/usr/bin/env python3
"""
dump_br_league_players.py — 抓 BR 联赛级球员页，导出 (name, br_player_id, team) TSV。

用途
----
crawl_br_gamelog.py 的球员清单默认来自 player_per_game（赛季聚合表）。新赛季
（如 2026-27 / season=2027）聚合表尚未导入时该查询返回空 → 爬虫空转。本脚本
直接抓 BR 联赛页（per_game）拿权威球员清单（含 BR slug），产出的 TSV 喂给
crawl_br_gamelog.py --players-file，旁路聚合表依赖。

与 daily crawler 的关系：nba_daily_crawler.crawl_season_player_stats 是
「只检查不导入」（正式导入走 combine_server，当前树内不存在），所以不能靠它
落 per_game；也不应为了拿名单往 fact_player_season_stats 写半填行（违数据
四性）——名单是爬取侧的一次性输入，不是库内数据。

数据源: https://www.basketball-reference.com/leagues/NBA_{season}_per_game.html
通道:   common.browser（Playwright 无头 + CF 熔断器，与 gamelog 爬虫同通道）
输出:   TSV，每行 name\tbr_player_id\tteam；按 br_player_id 去重；跳过 TOT 行
        （与 fact_player_season_stats 既有形态一致：无 TOT 行）

用法:
  python dump_br_league_players.py --season 2027 --out /tmp/players_2027.tsv
  python dump_br_league_players.py --season 2027 --dry-run   # 只解析不写文件
"""
import argparse
import os
import re
import sys
from pathlib import Path

# 与 crawl_br_gamelog.py 一致：把项目根（parents[2]）放上 sys.path，
# 使 `import common.browser` 在独立运行时能解析。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

BR_BASE = "https://www.basketball-reference.com"
_SLUG_RE = re.compile(r"/players/[a-z]/([A-Za-z0-9]+)\.html")


def fetch_page(url: str, poll_seconds: int = 90) -> str:
    """Fetch a fully-rendered BR page via the shared driver (same channel as
    the gamelog crawler: Playwright headless + shared CF breaker / UC backend).

    Cloudflare JS challenges ("请稍候…" / "Just a moment") often clear in place
    after a few seconds of client-side checks — so we poll the rendered DOM
    (mirroring crawl_br_gamelog._fetch_html) instead of giving up on the first
    read. Re-navigates once mid-poll to grant the challenge a fresh attempt.
    """
    import time
    from common.browser import get_driver
    drv = get_driver()
    drv.get(url)
    deadline = time.time() + poll_seconds
    renavigated = False
    while True:
        html = drv.page_source or ""
        if "per_game_stats" in html:
            return html
        if time.time() >= deadline:
            return html  # 调用方检测无表 → 报错退出
        if not renavigated and time.time() >= deadline - poll_seconds / 2:
            renavigated = True
            try:
                drv.get(url)  # 给 CF 挑战一次全新的过签机会
            except Exception:  # noqa: BLE001 - best-effort
                pass
        time.sleep(5)


def parse_players(html: str) -> list:
    """Parse the per_game_stats table into [(name, slug, team), ...].

    Skips TOT rows (multi-team aggregate rows) to match the existing
    fact_player_season_stats形态, and dedupes by slug (a player traded
    mid-season has one row per team).
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="per_game_stats")
    if not table:
        return []
    tbody = table.find("tbody")
    if not tbody:
        return []
    out = []
    seen = set()
    for row in tbody.find_all("tr"):
        cls = row.get("class", []) or []
        if "thead" in cls or "over_header" in cls:
            continue
        # BR 现行联赛表：姓名格 data-stat=name_display（内嵌 /players/{x}/{slug}.html），
        # 队名格 data-stat=team_name_abbr（历史键名 player/team 已弃用）。
        name_td = row.find("td", attrs={"data-stat": "name_display"})
        if not name_td:
            continue
        name = name_td.get_text(strip=True)
        a = name_td.find("a", href=_SLUG_RE)
        slug = None
        if a:
            m = _SLUG_RE.search(a.get("href", ""))
            if m:
                slug = m.group(1)
        team_td = row.find("td", attrs={"data-stat": "team_name_abbr"})
        team = team_td.get_text(strip=True) if team_td else ""
        if not name or not slug:
            continue
        if team == "TOT":
            continue  # 多队合计行：跳过（与库内既有形态一致）
        if slug in seen:
            continue
        seen.add(slug)
        out.append((name, slug, team))
    return out


def main():
    ap = argparse.ArgumentParser(description="导出 BR 联赛页球员清单 TSV")
    ap.add_argument("--season", type=int, required=True,
                    help="赛季结束年 (如 2027 = 2026-27赛季)")
    ap.add_argument("--out", type=str, default=None,
                    help="输出 TSV 路径 (默认 /tmp/br_players_<season>.tsv)")
    ap.add_argument("--table", type=str, default="per_game",
                    choices=["per_game"], help="联赛页类型 (默认 per_game)")
    ap.add_argument("--dry-run", action="store_true",
                    help="只抓取解析并打印统计，不写文件")
    args = ap.parse_args()

    out = args.out or f"/tmp/br_players_{args.season}.tsv"
    url = f"{BR_BASE}/leagues/NBA_{args.season}_{args.table}.html"
    print(f"fetch: {url}", flush=True)

    html = fetch_page(url)
    if not html:
        print("ERROR: 空页面（浏览器通道失败）", file=sys.stderr)
        sys.exit(1)
    if "per_game_stats" not in html:
        # CF 挑战页 / 错误页都不含该表 id
        head = html[:200].replace("\n", " ")
        print(f"ERROR: 页面无 per_game_stats 表（CF 挑战或错误页？）: {head}...",
              file=sys.stderr)
        sys.exit(2)

    players = parse_players(html)
    print(f"parsed: {len(players)} 名球员 (season {args.season})")
    if not players:
        print("ERROR: 解析到 0 名球员", file=sys.stderr)
        sys.exit(3)

    teams = {}
    for _, _, t in players:
        teams[t] = teams.get(t, 0) + 1
    print(f"teams: {len(teams)} 支; top5: "
          f"{sorted(teams.items(), key=lambda kv: -kv[1])[:5]}")

    if args.dry_run:
        for name, slug, team in players[:10]:
            print(f"  {name}\t{slug}\t{team}")
        print(f"  ... (dry-run, 未写文件)")
        return

    with open(out, "w", encoding="utf-8") as fh:
        for name, slug, team in players:
            fh.write(f"{name}\t{slug}\t{team}\n")
    print(f"written: {out}")


if __name__ == "__main__":
    main()
