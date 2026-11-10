"""crawl_2027_shot_charts_games.py — 按比赛定向补爬 2027 shot chart。

用途：日更爬虫只重 load box/pbp，不抓逐人 shot chart；新比赛的 shot chart
需按「该场出场球员」定向重爬其 BR shooting 页（幂等 upsert，已入库的球不变）。

用法:
    python crawl_2027_shot_charts_games.py 22600006 22600007
    LIMIT=2 python crawl_2027_shot_charts_games.py 22600006   # 冒烟只跑前 N 人

需环境变量：BROWSER_BACKEND=cdp  CHROME_CDP_URL=http://127.0.0.1:9223  PGPASSWORD
（长跑请另加 PYTHONPATH= 并剥掉 HTTP(S)_PROXY，见项目记忆）
"""
import os
import sys

import psycopg2

from crawl_br_player_shot_chart import PlayerShotChartCrawler, DB_CONFIG

SEASON = 2027


def main() -> None:
    gameids = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not gameids:
        sys.exit("usage: crawl_2027_shot_charts_games.py <nba_api_gameid> [...]")
    limit = int(os.environ.get("LIMIT", "0")) or None

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT player_id FROM player_gamelog "
            "WHERE season=%s AND gameid = ANY(%s) "
            "AND player_id IS NOT NULL AND player_id <> '' "
            "ORDER BY player_id",
            (SEASON, gameids),
        )
        slugs = [r[0] for r in cur.fetchall()]
        cur.close()

        pairs = [(s, SEASON) for s in slugs]
        if limit is not None:
            pairs = pairs[:limit]
        print(f"[driver] 待爬 (slug,{SEASON}) 对: {len(pairs)}（该场共 {len(slugs)} 人, games={gameids}）",
              flush=True)

        crawler = PlayerShotChartCrawler(dry_run=False, resume=True)
        total = crawler.run_pairs(conn, pairs, resume=True, skip_done_check=True)
        print(f"[driver] DONE：upsert {total} 球（处理 {len(pairs)} 对）", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
