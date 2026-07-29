#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NBA月度赛程爬虫 - 用于从Basketball Reference抓取月度比赛数据
改进版：随机延迟、未完成列表、自动重试
"""
from playwright.sync_api import sync_playwright
import pandas as pd
import time
import logging
import os
import random
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ScheduleScraper:
    """NBA赛程爬虫类 - 改进版"""

    def __init__(self, headless=True, min_delay=40, max_delay=40):
        """
        初始化赛程爬虫

        Args:
            headless: 是否使用无头模式
            min_delay: 最小延迟（秒）
            max_delay: 最大延迟（秒）
        """
        self.headless = headless
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.base_url = "https://www.basketball-reference.com"
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        self.incomplete_list = []
        self.incomplete_list_path = None
        self.start_time = None
        self.run_interval = 30 * 60  # 运行30分钟
        self.rest_interval = 5 * 60   # 休息5分钟

    def _safe_random_delay(self):
        """安全随机延迟，防止429错误"""
        delay = random.uniform(self.min_delay, self.max_delay)
        logger.info(f"休眠 {delay:.1f} 秒，防止触发网站的 429 请求过多限制...")
        time.sleep(delay)
    
    def _check_and_rest(self):
        """
        检查是否需要休息
        每运行30分钟，休息5分钟
        """
        if self.start_time is None:
            self.start_time = time.time()
            return
        
        elapsed = time.time() - self.start_time
        if elapsed >= self.run_interval:
            logger.info("=" * 80)
            logger.info(f"已运行 {elapsed/60:.1f} 分钟，休息 {self.rest_interval/60:.0f} 分钟...")
            logger.info("=" * 80)
            time.sleep(self.rest_interval)
            logger.info("休息结束，继续运行...")
            logger.info("=" * 80)
            self.start_time = time.time()  # 重置开始时间

    def _load_incomplete_list(self, output_dir, year):
        """加载未完成列表"""
        self.incomplete_list_path = os.path.join(output_dir, f"incomplete_{year}.json")
        if os.path.exists(self.incomplete_list_path):
            try:
                with open(self.incomplete_list_path, 'r', encoding='utf-8') as f:
                    self.incomplete_list = json.load(f)
                logger.info(f"加载未完成列表: {self.incomplete_list}")
            except Exception as e:
                logger.warning(f"加载未完成列表失败: {e}")
                self.incomplete_list = []
        else:
            self.incomplete_list = []

    def _save_incomplete_list(self):
        """保存未完成列表"""
        if self.incomplete_list_path:
            try:
                with open(self.incomplete_list_path, 'w', encoding='utf-8') as f:
                    json.dump(self.incomplete_list, f, ensure_ascii=False, indent=2)
                logger.info(f"保存未完成列表: {self.incomplete_list}")
            except Exception as e:
                logger.error(f"保存未完成列表失败: {e}")

    def _remove_from_incomplete_list(self, year, month):
        """从待完成列表中移除"""
        self.incomplete_list = [item for item in self.incomplete_list 
                               if not (item['year'] == year and item['month'] == month)]
        self._save_incomplete_list()

    def _add_to_incomplete_list(self, year, month, retry_count=0):
        """添加到待完成列表"""
        if not any(item['year'] == year and item['month'] == month for item in self.incomplete_list):
            self.incomplete_list.append({
                'year': year,
                'month': month,
                'retry_count': retry_count
            })
            self._save_incomplete_list()

    def scrape_month_schedule(self, year, month, output_dir=None, max_retries=3):
        """
        抓取指定年月的NBA比赛数据（带重试）

        Args:
            year: 赛季开始年份，如 2024 (表示2024-25赛季)
            month: 月份（英文），如 'october', 'november'
            output_dir: 输出目录
            max_retries: 最大重试次数

        Returns:
            DataFrame包含该月所有比赛数据
        """
        # Basketball Reference使用赛季结束年份作为URL参数
        season_year = year + 1
        url = f"{self.base_url}/leagues/NBA_{season_year}_games-{month}.html"

        for attempt in range(max_retries):
            logger.info(f"正在访问: {url} (尝试 {attempt + 1}/{max_retries})")

            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=self.headless)
                    context = browser.new_context(user_agent=self.user_agent)
                    page = context.new_page()

                    page.goto(url, wait_until="networkidle", timeout=60000)
                    
                    # 等待 Cloudflare 验证完成
                    logger.info("等待页面加载完成...")
                    time.sleep(5)  # 给 Cloudflare 验证时间
                    
                    # 检查是否还在验证页面
                    page_content = page.content()
                    if "安全验证" in page_content or "security" in page_content.lower():
                        logger.info("检测到 Cloudflare 验证页面，等待验证完成...")
                        time.sleep(10)  # 等待验证

                    # 等待表格加载 - 使用多种选择器尝试
                    table_found = False
                    selectors = ["table#schedule", "table#games", "table.stats_table", "table[id*='schedule']", "table[id*='games']"]
                    
                    for selector in selectors:
                        try:
                            page.wait_for_selector(selector, timeout=10000)
                            table_found = True
                            logger.info(f"✓ 找到表格: {selector}")
                            break
                        except Exception:
                            continue
                    
                    if not table_found:
                        # 尗试查找任何表格
                        try:
                            page.wait_for_selector("table", timeout=5000)
                            tables = page.query_selector_all("table")
                            logger.info(f"页面共有 {len(tables)} 个表格")
                            if len(tables) > 0:
                                table_found = True
                        except Exception:
                            pass
                    
                    if not table_found:
                        logger.warning(f"⚠️ 找不到 {month} 月的表格数据，可能尚未排期或已结束，跳过。")
                        browser.close()
                        # 这种情况不需要重试，移除自待完成列表
                        self._remove_from_incomplete_list(year, month)
                        return pd.DataFrame()

                    # 找到正确的赛程表格
                    schedule_table = None
                    for selector in selectors:
                        tables = page.query_selector_all(selector)
                        for table in tables:
                            # 检查表格是否包含比赛数据（通常有多列）
                            rows = table.query_selector_all("tbody tr")
                            if len(rows) > 0:
                                schedule_table = table
                                break
                        if schedule_table:
                            break
                    
                    if not schedule_table:
                        # 使用第一个有数据的表格
                        tables = page.query_selector_all("table")
                        for table in tables:
                            rows = table.query_selector_all("tbody tr")
                            if len(rows) > 0:
                                schedule_table = table
                                break
                    
                    if not schedule_table:
                        logger.warning(f"⚠️ 无法找到有效的赛程表格")
                        browser.close()
                        return pd.DataFrame()

                    # 提取表头
                    headers = []
                    th_elements = schedule_table.query_selector_all("thead tr th")
                    headers = [th.inner_text().strip() for th in th_elements]

                    # 提取数据行
                    rows = schedule_table.query_selector_all("tbody tr:not(.thead)")

                    game_data = []
                    for row in rows:
                        cells = row.query_selector_all("th, td")
                        row_vals = [cell.inner_text().strip() for cell in cells]

                        # 过滤掉空行和干扰行
                        if row_vals and len(row_vals) > 5:
                            game_data.append(row_vals)

                    browser.close()

                    # 转换为DataFrame
                    if game_data:
                        df = pd.DataFrame(game_data)

                        # 对齐列名
                        if len(headers) == df.shape[1]:
                            df.columns = headers
                        else:
                            logger.warning(f"⚠️ 列数不匹配: headers={len(headers)}, data={df.shape[1]}")

                        # 清理空列名
                        df = df.rename(columns={"": "Notes/BoxScore"})

                        # 添加年月信息
                        df['Year'] = year
                        df['Month'] = month.capitalize()

                        logger.info(f"✅ {month.capitalize()} 月抓取完成，共 {len(game_data)} 场比赛。")

                        # 保存数据
                        if output_dir:
                            os.makedirs(output_dir, exist_ok=True)
                            filename = f"nba_schedule_{year}_{month}.csv"
                            filepath = os.path.join(output_dir, filename)
                            df.to_csv(filepath, index=False, encoding='utf-8-sig')
                            logger.info(f"✓ 已保存到: {filepath}")

                        # 成功抓取，移除自待完成列表
                        self._remove_from_incomplete_list(year, month)
                        return df
                    else:
                        logger.info(f"⚠️ {month.capitalize()} 月无有效数据")
                        self._remove_from_incomplete_list(year, month)
                        return pd.DataFrame()

            except Exception as e:
                logger.error(f"❌ 抓取失败 (尝试 {attempt + 1}/{max_retries}): {e}")

                if attempt < max_retries - 1:
                    retry_delay = random.uniform(self.min_delay + 2, self.max_delay + 5)
                    logger.info(f"等待 {retry_delay:.1f} 秒后重试...")
                    time.sleep(retry_delay)
                else:
                    # 所有重试都失败，添加到待完成列表
                    self._add_to_incomplete_list(year, month, attempt + 1)
                    logger.error(f"已达到最大重试次数，添加到未完成列表")
                    return pd.DataFrame()

    def scrape_full_season(self, year, output_dir=None, max_retries=3):
        """
        抓取完整赛季（10月-6月）的所有比赛数据，带自动重试

        Args:
            year: 赛季年份（10月所在年份）
            output_dir: 输出目录
            max_retries: 每轮最大重试次数

        Returns:
            DataFrame包含该赛季所有比赛数据
        """
        months = [
            "october", "november", "december", "january",
            "february", "march", "april", "may", "june"
        ]

        all_games = []

        logger.info("=" * 80)
        logger.info(f"开始抓取 {year}-{year+1} 赛季完整数据")
        logger.info("=" * 80)

        # 初始化未完成列表
        if output_dir:
            self._load_incomplete_list(output_dir, year)

        # 第一轮抓取
        logger.info("\n" + "=" * 80)
        logger.info("第一轮抓取...")
        logger.info("=" * 80)

        for month in months:
            logger.info(f"\n正在抓取 {month.capitalize()} 月份...")

            # 检查文件是否已存在，避免重复抓取
            if output_dir:
                existing_file = os.path.join(output_dir, f"nba_schedule_{year}_{month}.csv")
                if os.path.exists(existing_file):
                    logger.info(f"文件已存在，跳过抓取: {existing_file}")
                    try:
                        df = pd.read_csv(existing_file, encoding='utf-8-sig')
                        if not df.empty:
                            all_games.append(df)
                            continue
                    except Exception:
                        logger.warning("加载已存在文件失败，重新抓取")

            month_df = self.scrape_month_schedule(year, month, output_dir, max_retries)

            if not month_df.empty:
                all_games.append(month_df)

            # 防封锁延迟
            if month != months[-1]:
                self._safe_random_delay()
            
            # 检查是否需要休息
            self._check_and_rest()

        # 检查并处理未完成列表
        round_num = 2
        while self.incomplete_list:
            logger.info("\n" + "=" * 80)
            logger.info(f"第 {round_num} 轮抓取 - 处理未完成列表: {self.incomplete_list}")
            logger.info("=" * 80)

            # 复制当前待完成列表
            current_incomplete = self.incomplete_list.copy()

            for item in current_incomplete:
                year_item = item['year']
                month_item = item['month']
                retry_count = item.get('retry_count', 0)

                logger.info(f"\n重试抓取: {month_item.capitalize()} ({year_item})")

                month_df = self.scrape_month_schedule(
                    year_item, month_item, output_dir, 
                    max_retries=max_retries
                )

                if not month_df.empty:
                    all_games.append(month_df)

                # 防封锁延迟
                self._safe_random_delay()
                
                # 检查是否需要休息
                self._check_and_rest()

            round_num += 1

        if all_games:
            # 合并所有月份数据
            full_season_df = pd.concat(all_games, ignore_index=True)

            logger.info("\n" + "=" * 80)
            logger.info("🎉 整个赛季的数据全部抓取成功！")
            logger.info(f"总计获取 {len(full_season_df)} 场比赛数据。")
            logger.info("=" * 80)

            # 保存完整赛季数据
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                filename = f"nba_full_schedule_{year}-{year+1}.csv"
                filepath = os.path.join(output_dir, filename)
                full_season_df.to_csv(filepath, index=False, encoding='utf-8-sig')
                logger.info(f"✓ 完整赛季数据已保存到: {filepath}")

                # 删除临时未完成列表文件
                if self.incomplete_list_path and os.path.exists(self.incomplete_list_path):
                    try:
                        os.remove(self.incomplete_list_path)
                        logger.info(f"已删除临时未完成列表文件")
                    except Exception:
                        pass

            return full_season_df
        else:
            logger.warning("❌ 未抓取到任何有效数据")
            return pd.DataFrame()

if __name__ == "__main__":
    # 抓取2024-25赛季完整数据（已结束的赛季，数据完整）
    scraper = ScheduleScraper(headless=True, min_delay=40, max_delay=40)
    df = scraper.scrape_full_season(2024, output_dir="CSV")

    if not df.empty:
        print("\n数据预览:")
        print(df.head())
