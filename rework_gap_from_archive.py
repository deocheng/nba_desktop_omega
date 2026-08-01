#!/usr/bin/env python3
"""批量本地重放：用归档 HTML 补 player_shot_chart 缺口（零线上请求）。

流程：
1. 枚举缺口对 (player_shooting EXCEPT player_shot_chart)；
2. 过滤出本地归档存在的对（raw_archive/br_players_shot/{slug}/shooting_{season}.html）；
3. 逐对本地解析 + 幂等 upsert（games_cache 只加载一次）；
4. 解析 0 球的对如实统计（多为该季页面确无散点数据）。

不碰 CDP / 不发任何网络请求，可与在线爬虫并行运行。
用法：.venv/bin/python rework_gap_from_archive.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg2  # noqa: E402

from external_crawler.crawler.crawl_br_player_shot_chart import (  # noqa: E402
    PlayerShotChartCrawler, parse_shot_chart_html, DB_CONFIG,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("rework_gap")


def main() -> None:
    crawler = PlayerShotChartCrawler(dry_run=False, resume=False)
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT player_id, season FROM ("
            " SELECT DISTINCT player_id, season FROM player_shooting"
            " EXCEPT"
            " SELECT DISTINCT player_id, season FROM player_shot_chart"
            ") t ORDER BY season DESC, player_id"
        )
        gap = cur.fetchall()
        cur.close()

        archive_root = Path(crawler.RAW_ARCHIVE)
        todo = [(s, y) for s, y in gap
                if (archive_root / s / f"shooting_{y}.html").exists()]
        log.info("缺口 %d 对，其中本地有归档 %d 对", len(gap), len(todo))

        cache = crawler.load_games_cache(conn)
        log.info("games_cache 加载完成：%d 键", len(cache))

        total_balls = 0
        ok = zero = err = 0
        for i, (slug, season) in enumerate(todo, 1):
            path = archive_root / slug / f"shooting_{season}.html"
            try:
                html = path.read_text(encoding="utf-8")
                recs = parse_shot_chart_html(html)
                if not recs:
                    zero += 1
                    if zero <= 20:
                        log.warning("[%d/%d] %s/%s 解析 0 球（页面确无散点）",
                                    i, len(todo), slug, season)
                    continue
                rows = [crawler.build_rows(conn, slug, season, r, cache)
                        for r in recs]
                n = crawler.upsert(conn, rows)
                conn.commit()
                total_balls += n
                ok += 1
                log.info("[%d/%d] %s/%s upsert %d 球", i, len(todo), slug, season, n)
            except Exception as e:  # noqa: BLE001
                err += 1
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
                log.error("[%d/%d] %s/%s 失败: %s", i, len(todo), slug, season, e)

        log.info("完成：成功 %d 对 / 0球 %d 对 / 失败 %d 对，共 upsert %d 球",
                 ok, zero, err, total_balls)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
