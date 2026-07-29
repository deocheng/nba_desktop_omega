"""crawl_br_team_logos.py — 队标(team logo)按年回填。

设计（遵循访问限制铁律 #0：≤5 req/s，CF 感知，节流，幂等）：
- 遍历 team_summaries 全部 (abbreviation, season)，对缺 logo 的队季：
  1) 经共享 CDP driver 抓 BR 队主页 HTML（复用 BRTeamPageCrawler.fetch_team_page，
     内含 ~7s 限速 + CF/404 检测）；
  2) extract_team_logo_src 抽取 <img class="teamlogo"> 的 cdn.ssref.net URL；
  3) save_team_logo 落盘 {slug}-{season}.png（幂等，存在则跳过）；
  4) upsert team_logos(abbr, season, logo_path, logo_url, franchise_id)。
- 已存在 logo 文件者仅补 DB 关联（populate-from-disk），不重复抓 BR。
- 命中 CF 挑战页则暂停等待用户清挑战（与 orchestrator 同策略），避免缺口被静默清零。
- 不主动 quit 共享 driver（留给 orchestrator 继续用）。

用法
----
  python crawl_br_team_logos.py                 # 全量回填（幂等，可重复跑）
  python crawl_br_team_logos.py --season 2026  # 仅某季
  python crawl_br_team_logos.py --dry-run       # 仅统计缺口，不抓
  python crawl_br_team_logos.py --limit 5       # 试跑前 5 个缺失队季
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg2

from common.br_team_page import (
    BRTeamPageCrawler,
    DB_CONFIG,
)
from common.browser import ensure_cf_cleared
from common.logo_store import (
    LOGO_ROOT,
    extract_team_logo_src,
    save_team_logo,
)

logger = logging.getLogger("team_logos")

BR_MAIN_URL = "https://www.basketball-reference.com/teams/{slug}/{season}.html"
CF_PAUSE_S = 600  # CF 命中后暂停等用户清挑战
CF_MAX_RETRY = 8


def _upsert_logo(conn, abbr: str, season: int, path: str,
                 url: str | None, franchise_id: int | None) -> None:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO team_logos (team_abbr, season, logo_path, logo_url, franchise_id)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (team_abbr, season) DO UPDATE SET
               logo_path   = EXCLUDED.logo_path,
               logo_url    = COALESCE(EXCLUDED.logo_url, team_logos.logo_url),
               franchise_id = EXCLUDED.franchise_id,
               fetched_at  = now()""",
        (abbr, season, path, url, franchise_id),
    )
    conn.commit()
    cur.close()


def _franchise_id_for(conn, abbr: str, season: int) -> int | None:
    cur = conn.cursor()
    cur.execute(
        "SELECT franchise_id FROM team_summaries "
        "WHERE abbreviation=%s AND season=%s AND franchise_id IS NOT NULL LIMIT 1",
        (abbr, season),
    )
    row = cur.fetchone()
    cur.close()
    return row[0] if row else None


def main() -> None:
    ap = argparse.ArgumentParser(description="BR 队标按年回填")
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="最多处理 N 个缺失队季（调试）")
    ap.add_argument("--no-cf-pause", action="store_true",
                    help="命中 CF 不暂停，直接跳过（谨慎使用）")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    if args.season:
        cur.execute(
            "SELECT DISTINCT abbreviation, season FROM team_summaries "
            "WHERE season=%s ORDER BY abbreviation", (args.season,))
    else:
        cur.execute(
            "SELECT DISTINCT abbreviation, season FROM team_summaries "
            "ORDER BY season DESC, abbreviation")
    pairs = cur.fetchall()
    cur.close()

    crawler = BRTeamPageCrawler(resume=True)
    driver = None
    if not args.dry_run:
        driver = crawler.get_driver()
        try:
            ensure_cf_cleared(driver)
        except Exception as _e:  # noqa: BLE001
            logger.warning("CF 握手前置检查异常（仍继续）: %s", _e)

    total = len(pairs)
    logger.info("队季总数: %d | logo 根目录: %s", total, LOGO_ROOT)

    handled = 0
    skipped_exist = 0
    fetched = 0
    failed = 0

    for abbr, season in pairs:
        slug = crawler._br_slug(conn, abbr)
        dst = LOGO_ROOT / f"{slug}-{season}.png"
        fid = _franchise_id_for(conn, abbr, season)

        # 已落盘：仅确保 DB 关联
        if dst.exists() and dst.stat().st_size > 500:
            if not args.dry_run:
                _upsert_logo(conn, abbr, season, str(dst), None, fid)
            skipped_exist += 1
            handled += 1
            continue

        if args.dry_run:
            failed += 1  # dry-run 下计为“待抓”
            continue

        # 抓取队主页并抽取队标
        url = BR_MAIN_URL.format(slug=slug, season=season)
        ok = False
        for attempt in range(1, CF_MAX_RETRY + 1):
            html = crawler.fetch_team_page(driver, url)
            if crawler._last_fetch_cf:
                if args.no_cf_pause:
                    logger.warning("CF 命中，按 --no-cf-pause 跳过: %s", url)
                    break
                logger.warning("CF 挑战页，暂停 %ds 等用户清挑战 (尝试 %d/%d): %s",
                               CF_PAUSE_S, attempt, CF_MAX_RETRY, url)
                time.sleep(CF_PAUSE_S)
                continue
            if not html:
                # 404 或空页：隔离跳过
                logger.warning("无页(404/空)，隔离跳过: %s", url)
                break
            src = extract_team_logo_src(html)
            if not src:
                logger.warning("未抽到队标 src，跳过: %s", url)
                break
            path = save_team_logo(slug, season, src)
            if path:
                _upsert_logo(conn, abbr, season, path, src, fid)
                ok = True
            break

        if ok:
            fetched += 1
        else:
            failed += 1
        handled += 1

        if args.limit and fetched >= args.limit:
            logger.info("--limit %d 已达，停止。", args.limit)
            break

        # 每 200 个打印进度
        if handled % 200 == 0:
            logger.info("进度 %d/%d | 已抓=%d 已存在=%d 失败=%d",
                        handled, total, fetched, skipped_exist, failed)

    logger.info("完成 | 队季=%d 已落盘复用=%d 新抓=%d 待补/失败=%d",
                total, skipped_exist, fetched, failed)
    # 不 quit 共享 driver（留给 orchestrator）


if __name__ == "__main__":
    main()
