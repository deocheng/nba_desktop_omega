"""赛季末 shot chart 全量补爬驱动（文件名含 2027 是历史原因，实际支持任意赛季）。

背景：日更爬虫只重 load box/pbp，不抓逐人 shot chart；`player_shooting` 当季为 0 行
（shot chart 爬虫的原枚举源），故本驱动改从 `player_gamelog` 取该季全部 BR slug，
直接构造 (slug, season) 对喂给已有 `PlayerShotChartCrawler.run_pairs`（不查 player_shooting）。

定位（老程 2026-10-24 决策）：player_shot_chart **赛季结束后一次性处理**，不进日更
（依赖 BR 网页 + CDP 9223 + CF 人工验证，无法无人值守）。本脚本即赛季末入口。

用法：
  python crawl_2027_shot_charts.py                 # 自动探测赛季（dim_games 最新比赛）
  python crawl_2027_shot_charts.py --season 2027   # 指定赛季
  python crawl_2027_shot_charts.py 20              # 位置参数=limit，小批验证
  python crawl_2027_shot_charts.py --season 2027 20
需环境变量：BROWSER_BACKEND=cdp  CHROME_CDP_URL=http://127.0.0.1:9223
"""
import argparse
import sys

import psycopg2
from crawl_br_player_shot_chart import DB_CONFIG, PlayerShotChartCrawler


def detect_season(cur) -> int:
    """自动探测目标赛季：dim_games 中最新比赛所属赛季。"""
    cur.execute("SELECT season FROM dim_games "
                "WHERE game_date IS NOT NULL ORDER BY game_date DESC LIMIT 1")
    row = cur.fetchone()
    if not row or row[0] is None:
        raise SystemExit("无法探测赛季：dim_games 无有效 game_date，请显式传 --season")
    return int(row[0])


def main() -> None:
    ap = argparse.ArgumentParser(description="赛季末 shot chart 全量补爬")
    ap.add_argument("--season", type=int, default=None,
                    help="目标赛季；缺省自动探测（dim_games 最新比赛所属赛季）")
    ap.add_argument("limit", nargs="?", default=None,
                    help="只处理前 N 对（小批验证）；空=全量")
    args = ap.parse_args()

    limit = int(args.limit) if args.limit and args.limit.isdigit() else None

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        season = args.season if args.season is not None else detect_season(cur)
        cur.execute(
            "SELECT DISTINCT player_id FROM player_gamelog "
            "WHERE season=%s AND player_id IS NOT NULL AND player_id <> '' "
            "ORDER BY player_id", (season,))
        slugs = [r[0] for r in cur.fetchall()]
        cur.close()

        pairs = [(s, season) for s in slugs]
        if limit is not None:
            pairs = pairs[: max(0, limit)]
        print(f"[driver] season={season} 待爬 (slug,season) 对: {len(pairs)}（全量 {len(slugs)}）")

        crawler = PlayerShotChartCrawler(dry_run=False, resume=True)
        total = crawler.run_pairs(conn, pairs, resume=True, skip_done_check=True)
        print(f"[driver] DONE：upsert {total} 球（处理 {len(pairs)} 对）")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
