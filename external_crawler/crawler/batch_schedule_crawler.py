#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NBA批量赛季赛程爬虫 - 用于批量抓取多个赛季的比赛数据
"""
from nba_data.crawler.schedule_scraper import ScheduleScraper
import pandas as pd
import time
import logging
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BatchScheduleCrawler:
    """NBA批量赛季赛程爬虫类"""

    def __init__(self, headless=True, delay=40, output_dir=None):
        """
        初始化批量爬虫

        Args:
            headless: 是否使用无头模式
            delay: 两次请求之间的延迟（秒）
            output_dir: 输出目录
        """
        self.scraper = ScheduleScraper(headless=headless, min_delay=delay, max_delay=delay+3)
        self.output_dir = output_dir or "nba_data/CSV"
        os.makedirs(self.output_dir, exist_ok=True)

    def scrape_seasons(self, start_year=2016, end_year=2026, save_intermediate=True):
        """
        批量抓取多个赛季的数据

        Args:
            start_year: 起始年份
            end_year: 结束年份
            save_intermediate: 是否保存中间结果

        Returns:
            所有赛季数据的合并DataFrame
        """
        all_seasons_data = []

        total_seasons = end_year - start_year + 1
        current_season = 0

        logger.info("=" * 80)
        logger.info(f"开始批量抓取 {start_year}-{end_year} 年间共 {total_seasons} 个赛季的数据")
        avg_delay = (4 + 7) / 2
        logger.info(f"预计总耗时: 约 {total_seasons * 9 * (avg_delay + 1) / 60:.1f} 分钟")
        logger.info("=" * 80)

        for year in range(start_year, end_year + 1):
            current_season += 1
            season_start = time.time()

            logger.info("\n" + "=" * 80)
            logger.info(f"[{current_season}/{total_seasons}] 正在处理 {year}-{year+1} 赛季...")
            logger.info("=" * 80)

            try:
                season_df = self.scraper.scrape_full_season(year, self.output_dir if save_intermediate else None)

                if not season_df.empty:
                    season_df['Season'] = f"{year}-{year+1}"
                    all_seasons_data.append(season_df)

                    # 保存单个赛季数据
                    season_file = os.path.join(self.output_dir, f"nba_schedule_{year}-{year+1}.csv")
                    season_df.to_csv(season_file, index=False, encoding='utf-8-sig')
                    logger.info(f"✓ {year}-{year+1} 赛季数据已保存: {season_file}")

                season_duration = time.time() - season_start
                remaining_seasons = total_seasons - current_season
                estimated_remaining = season_duration * remaining_seasons / 60

                logger.info(f"该赛季耗时: {season_duration/60:.1f} 分钟")
                logger.info(f"预计剩余时间: {estimated_remaining:.1f} 分钟")

            except Exception as e:
                logger.error(f"❌ 抓取 {year}-{year+1} 赛季失败: {e}")
                continue

        # 合并所有数据
        if all_seasons_data:
            combined_df = pd.concat(all_seasons_data, ignore_index=True)

            # 保存完整数据
            combined_file = os.path.join(self.output_dir, f"nba_schedule_{start_year}-{end_year}_combined.csv")
            combined_df.to_csv(combined_file, index=False, encoding='utf-8-sig')

            logger.info("\n" + "=" * 80)
            logger.info("🎉 批量抓取完成！")
            seasons_count = len(all_seasons_data)
            logger.info(f"共抓取 {seasons_count} 个赛季的数据")
            logger.info(f"总计 {len(combined_df)} 场比赛")
            logger.info(f"数据已保存到: {combined_file}")
            logger.info("=" * 80)

            return combined_df
        else:
            logger.warning("❌ 未抓取到任何有效数据")
            return pd.DataFrame()

    def scrape_single_season_with_progress(self, year):
        """
        带进度显示的单赛季抓取

        Args:
            year: 赛季年份

        Returns:
            DataFrame包含该赛季所有比赛数据
        """
        logger.info("\n" + "=" * 70)
        logger.info(f"开始抓取 {year}-{year+1} 赛季数据")
        logger.info("=" * 70)

        df = self.scraper.scrape_full_season(year, self.output_dir)

        if not df.empty:
            logger.info(f"\n✅ 成功抓取 {len(df)} 场比赛")
        else:
            logger.warning("⚠️ 未抓取到数据")

        return df

if __name__ == "__main__":
    # 测试批量抓取（只抓取2026赛季作为测试）
    crawler = BatchScheduleCrawler(headless=False)

    # 只抓取2026赛季测试
    df = crawler.scrape_single_season_with_progress(2026)

    if not df.empty:
        print("\n数据预览:")
        print(df.head(10))
