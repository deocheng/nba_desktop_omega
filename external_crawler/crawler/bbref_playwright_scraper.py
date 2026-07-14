#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Basketball Reference Playwright爬取器 - 用于从Basketball Reference网站获取数据
使用Playwright处理JavaScript渲染的页面
"""
from playwright.sync_api import sync_playwright
import pandas as pd
import time
import logging
import os

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BasketballReferencePlaywrightScraper:
    """Basketball Reference Playwright爬取器类"""
    
    def __init__(self, headless=True, base_delay=5):
        """
        初始化Basketball Reference Playwright爬取器
        
        Args:
            headless: 是否使用无头模式
            base_delay: 基础延迟时间（秒），用于防封锁
        """
        self.headless = headless
        self.base_delay = base_delay
        self.base_url = "https://www.basketball-reference.com"
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    
    def _safe_delay(self):
        """安全延迟，防止429错误"""
        time.sleep(self.base_delay)
    
    def scrape_per_game_stats(self, season, output_dir=None):
        """
        抓取赛季球员每场平均数据
        
        Args:
            season: 赛季年份，如 2026
            output_dir: 输出目录，默认为当前目录
            
        Returns:
            DataFrame包含球员数据
        """
        url = f"{self.base_url}/leagues/NBA_{season}_per_game.html"
        
        logger.info(f"正在访问: {url}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(user_agent=self.user_agent)
            page = context.new_page()
            
            page.goto(url, wait_until="domcontentloaded")
            
            # 每场平均数据的表格 ID 是 'per_game_stats'
            table_selector = "table#per_game_stats"
            page.wait_for_selector(table_selector)
            
            # 1. 提取表头
            headers = []
            th_elements = page.query_selector_all(f"{table_selector} thead tr th")
            for th in th_elements:
                text = th.inner_text().strip()
                if text:
                    headers.append(text)
            
            # 如果第一列是 Rk (排名)，表头里通常没有它，这里做个微调对齐
            if "Rk" not in headers:
                headers.insert(0, "Rk")
                
            logger.info(f"成功获取表头，共 {len(headers)} 列。")
            
            # 2. 提取数据行（利用 CSS 选择器排除掉 class 带有 thead 的重复表头行）
            rows = page.query_selector_all(f"{table_selector} tbody tr:not(.thead)")
            
            player_data = []
            for row in rows:
                cells = row.query_selector_all("th, td")
                row_vals = [cell.inner_text().strip() for cell in cells]
                if row_vals:
                    player_data.append(row_vals)
            
            browser.close()
            
            # 3. 转换为 DataFrame
            df = pd.DataFrame(player_data)
            if df.shape[1] == len(headers):
                df.columns = headers
            
            # 4. 保存文件
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                output_file = os.path.join(output_dir, f"nba_player_per_game_{season}.csv")
            else:
                output_file = f"nba_player_per_game_{season}.csv"
            
            df.to_csv(output_file, index=False, encoding="utf-8-sig")
            logger.info(f"🎉 数据抓取成功！已保存至：{output_file}")
            
            return df
    
    def scrape_team_stats(self, team_abbr, season, output_dir=None):
        """
        抓取球队赛季统计数据
        
        Args:
            team_abbr: 球队缩写，如 'LAL'
            season: 赛季年份，如 2026
            output_dir: 输出目录
            
        Returns:
            DataFrame包含球队数据
        """
        url = f"{self.base_url}/teams/{team_abbr}/{season}.html"
        
        logger.info(f"正在访问: {url}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(user_agent=self.user_agent)
            page = context.new_page()
            
            page.goto(url, wait_until="domcontentloaded")
            self._safe_delay()
            
            # 查找多个统计表格
            tables = []
            table_ids = ['team_and_opponent', 'per_game', 'totals', 'advanced', 'shooting']
            
            for table_id in table_ids:
                table_selector = f"table#{table_id}"
                try:
                    page.wait_for_selector(table_selector, timeout=5000)
                    
                    headers = []
                    th_elements = page.query_selector_all(f"{table_selector} thead tr th")
                    for th in th_elements:
                        text = th.inner_text().strip()
                        if text:
                            headers.append(text)
                    
                    rows = page.query_selector_all(f"{table_selector} tbody tr:not(.thead)")
                    data = []
                    for row in rows:
                        cells = row.query_selector_all("th, td")
                        row_vals = [cell.inner_text().strip() for cell in cells]
                        if row_vals:
                            data.append(row_vals)
                    
                    if data:
                        df = pd.DataFrame(data)
                        if df.shape[1] == len(headers):
                            df.columns = headers
                        tables.append((table_id, df))
                        logger.info(f"成功获取 {table_id} 表格数据")
                except Exception as e:
                    logger.warning(f"未找到 {table_id} 表格或读取失败: {e}")
            
            browser.close()
            
            # 保存所有表格
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            
            for table_id, df in tables:
                if output_dir:
                    output_file = os.path.join(output_dir, f"{team_abbr}_{season}_{table_id}.csv")
                else:
                    output_file = f"{team_abbr}_{season}_{table_id}.csv"
                df.to_csv(output_file, index=False, encoding="utf-8-sig")
                logger.info(f"已保存: {output_file}")
            
            return tables
    
    def scrape_standings(self, season, output_dir=None):
        """
        抓取赛季排名
        
        Args:
            season: 赛季年份，如 2026
            output_dir: 输出目录
            
        Returns:
            包含东西部排名的字典
        """
        url = f"{self.base_url}/leagues/NBA_{season}_standings.html"
        
        logger.info(f"正在访问: {url}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(user_agent=self.user_agent)
            page = context.new_page()
            
            page.goto(url, wait_until="domcontentloaded")
            self._safe_delay()
            
            result = {}
            
            # 东部联盟
            east_table_selector = "table#confs_standings_E"
            try:
                page.wait_for_selector(east_table_selector)
                headers = []
                th_elements = page.query_selector_all(f"{east_table_selector} thead tr th")
                for th in th_elements:
                    text = th.inner_text().strip()
                    if text:
                        headers.append(text)
                
                rows = page.query_selector_all(f"{east_table_selector} tbody tr")
                data = []
                for row in rows:
                    cells = row.query_selector_all("th, td")
                    row_vals = [cell.inner_text().strip() for cell in cells]
                    if row_vals:
                        data.append(row_vals)
                
                if data:
                    df = pd.DataFrame(data)
                    if df.shape[1] == len(headers):
                        df.columns = headers
                    result['east'] = df
                    logger.info("成功获取东部联盟排名")
            except Exception as e:
                logger.warning(f"获取东部联盟排名失败: {e}")
            
            # 西部联盟
            west_table_selector = "table#confs_standings_W"
            try:
                page.wait_for_selector(west_table_selector)
                headers = []
                th_elements = page.query_selector_all(f"{west_table_selector} thead tr th")
                for th in th_elements:
                    text = th.inner_text().strip()
                    if text:
                        headers.append(text)
                
                rows = page.query_selector_all(f"{west_table_selector} tbody tr")
                data = []
                for row in rows:
                    cells = row.query_selector_all("th, td")
                    row_vals = [cell.inner_text().strip() for cell in cells]
                    if row_vals:
                        data.append(row_vals)
                
                if data:
                    df = pd.DataFrame(data)
                    if df.shape[1] == len(headers):
                        df.columns = headers
                    result['west'] = df
                    logger.info("成功获取西部联盟排名")
            except Exception as e:
                logger.warning(f"获取西部联盟排名失败: {e}")
            
            browser.close()
            
            # 保存文件
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            
            for conference, df in result.items():
                if output_dir:
                    output_file = os.path.join(output_dir, f"nba_standings_{season}_{conference}.csv")
                else:
                    output_file = f"nba_standings_{season}_{conference}.csv"
                df.to_csv(output_file, index=False, encoding="utf-8-sig")
                logger.info(f"已保存: {output_file}")
            
            return result

if __name__ == "__main__":
    scraper = BasketballReferencePlaywrightScraper(headless=False)
    
    # 测试抓取2025-26赛季数据
    try:
        df = scraper.scrape_per_game_stats(2026, output_dir="nba_data/CSV")
        print("\n数据前5行预览:")
        print(df.head())
    except Exception as e:
        print(f"抓取失败: {e}")
