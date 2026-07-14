"""
BR (Basketball-Reference) 每日自动化爬取包装脚本
=================================================
整合伤病、薪资、球员合同数据的定期爬取。
使用 LightScraper (requests + 随机 UA, 3-6s 延迟) 轻量反爬。

用法:
  python crawler/br_daily.py --mode injuries        # 仅伤病（~10s, 每日）
  python crawler/br_daily.py --mode payroll          # 仅薪资（~3min, 每周）
  python crawler/br_daily.py --mode all              # 全部（~3min）
  python crawler/br_daily.py --mode injuries --dry-run  # 只看不写

自动化集成:
  每日 10:30: br_daily.py --mode injuries
  每周一 10:30: br_daily.py --mode payroll
"""

import sys
import os
import time
import argparse
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from injuries_payroll_scraper import (
    LightScraper, init_db, scrape_injuries, scrape_all_payroll,
    DB_CONFIG, TEAM_ABBRS
)
import psycopg2

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("br_daily")


def run_injuries(scraper: LightScraper, conn, dry_run: bool = False):
    """爬取伤病数据 — 使用 Playwright Stealth (绕过 Cloudflare)"""
    import subprocess

    logger.info("=" * 60)
    logger.info("[伤病] 开始爬取 (Playwright Stealth)")
    logger.info("=" * 60)

    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "br_injuries_playwright.py")

    if dry_run:
        logger.info(f"[伤病 DRY-RUN] 将调用: {script_path}")
        return

    result = subprocess.run(
        [sys.executable, script_path],
        capture_output=True, text=True, timeout=120,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    if result.stdout:
        for line in result.stdout.strip().split('\n'):
            logger.info(f"  {line}")
    if result.returncode != 0:
        logger.error(f"[伤病] Playwright 脚本失败: {result.stderr}")
    else:
        logger.info("[伤病] 完成")


def run_payroll(scraper: LightScraper, conn, dry_run: bool = False,
                max_teams: int = 0):
    """爬取球队薪资 + 球员合同数据

    Args:
        max_teams: 最多爬取队伍数 (0=全部30队)
    """
    logger.info("=" * 60)
    logger.info("[薪资] 开始爬取")
    logger.info("=" * 60)

    teams_to_scrape = TEAM_ABBRS
    if max_teams and max_teams < len(TEAM_ABBRS):
        teams_to_scrape = TEAM_ABBRS[:max_teams]

    if dry_run:
        from injuries_payroll_scraper import scrape_payroll_summary
        summary = scrape_payroll_summary(scraper, conn)
        logger.info(f"[薪资 DRY-RUN] 获取汇总: {len(summary)} 队")
        for team_abbr in teams_to_scrape[:3]:
            team_name = TEAM_ABBRS  # just check availability
            try:
                from injuries_payroll_scraper import TEAM_NAMES
                url = f"https://www.basketball-reference.com/contracts/{team_abbr}.html"
                html = scraper.fetch(url)
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'lxml')
                table = soup.find('table', id='contracts')
                player_count = len(table.find('tbody').find_all('tr')) if table and table.find('tbody') else 0
                logger.info(f"  {team_abbr}: {player_count} 名球员合同 (未写入)")
            except Exception as e:
                logger.warning(f"  {team_abbr}: 请求失败 - {e}")
        return

    # Use the full scrape_all_payroll function
    scrape_all_payroll(scraper, conn)
    logger.info("[薪资] 完成: 30 队已更新")


def main():
    parser = argparse.ArgumentParser(description="BR 每日自动化爬取")
    parser.add_argument("--mode", choices=["injuries", "payroll", "all"],
                        default="all", help="爬取模式")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅测试不写库")
    parser.add_argument("--max-teams", type=int, default=0,
                        help="薪资模式最多爬取队伍数 (0=全部)")
    args = parser.parse_args()

    start = time.time()
    scraper = LightScraper(delay_min=3, delay_max=6)

    conn = None if args.dry_run else psycopg2.connect(**DB_CONFIG)

    try:
        if not args.dry_run and conn:
            init_db(conn)

        if args.mode in ("injuries", "all"):
            run_injuries(scraper, conn, dry_run=args.dry_run)

        if args.mode in ("payroll", "all"):
            run_payroll(scraper, conn, dry_run=args.dry_run,
                        max_teams=args.max_teams)

    finally:
        if conn:
            conn.close()

    elapsed = time.time() - start
    logger.info("=" * 60)
    logger.info(f"BR 爬取完成! 模式={args.mode}, 耗时: {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
