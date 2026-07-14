#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Basketball Reference爬取器 - 用于从Basketball Reference网站获取数据
支持 requests/BeautifulSoup 和 Playwright 两种模式
"""
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import logging
import os

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 尝试导入 Playwright，可选依赖
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright 未安装，将仅使用 requests 模式")

class BasketballReferenceScraper:
    """Basketball Reference爬取器类"""
    
    def __init__(self, max_retries=3, base_delay=2, use_playwright=False, headless=True):
        """
        初始化Basketball Reference爬取器
        
        Args:
            max_retries: 最大重试次数
            base_delay: 基础延迟时间（秒）
            use_playwright: 是否使用 Playwright 模式
            headless: Playwright 模式下是否使用无头浏览器
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.base_url = "https://www.basketball-reference.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        self.use_playwright = use_playwright and PLAYWRIGHT_AVAILABLE
        self.headless = headless
    
    def _retry_with_backoff(self, func, *args, **kwargs):
        """
        带指数退避的重试机制
        
        Args:
            func: 要执行的函数
            *args: 函数参数
            **kwargs: 函数关键字参数
            
        Returns:
            函数执行结果
        """
        for retry in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"尝试 {retry+1}/{self.max_retries} 失败: {e}")
                if retry < self.max_retries - 1:
                    delay = self.base_delay * (2 ** retry)
                    logger.info(f"{delay}秒后重试...")
                    time.sleep(delay)
                else:
                    logger.error(f"达到最大重试次数，操作失败: {e}")
                    raise
    
    def _get_soup(self, url):
        """
        获取页面的BeautifulSoup对象
        
        Args:
            url: 页面URL
            
        Returns:
            BeautifulSoup对象
        """
        def _fetch():
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        
        return self._retry_with_backoff(_fetch)
    
    def get_team_stats(self, team_abbr, season):
        """
        获取球队赛季统计数据
        
        Args:
            team_abbr: 球队缩写，如 'LAL'
            season: 赛季，如 '2023-24'
            
        Returns:
            球队统计数据
        """
        season_end = season.split('-')[1]
        url = f"{self.base_url}/teams/{team_abbr}/{season_end}.html"
        
        def _get_stats():
            soup = self._get_soup(url)
            
            # 查找统计表格
            table = soup.find('table', id='team_and_opponent')
            if not table:
                raise Exception("找不到统计表格")
            
            # 解析表格数据
            df = pd.read_html(str(table))[0]
            return df
        
        return self._retry_with_backoff(_get_stats)
    
    def get_player_stats(self, player_id, season):
        """
        获取球员赛季统计数据
        
        Args:
            player_id: 球员ID，如 'jamesle01'
            season: 赛季，如 '2023-24'
            
        Returns:
            球员统计数据
        """
        season_end = season.split('-')[1]
        url = f"{self.base_url}/players/{player_id[0]}/{player_id}.html"
        
        def _get_stats():
            soup = self._get_soup(url)
            
            # 查找赛季统计表格
            table = soup.find('table', id=f'per_game.{season_end}')
            if not table:
                raise Exception(f"找不到 {season} 赛季的统计表格")
            
            # 解析表格数据
            df = pd.read_html(str(table))[0]
            return df
        
        return self._retry_with_backoff(_get_stats)
    
    def get_team_schedule(self, team_abbr, season):
        """
        获取球队赛季赛程
        
        Args:
            team_abbr: 球队缩写，如 'LAL'
            season: 赛季，如 '2023-24'
            
        Returns:
            球队赛程数据
        """
        season_end = season.split('-')[1]
        url = f"{self.base_url}/teams/{team_abbr}/{season_end}_games.html"
        
        def _get_schedule():
            soup = self._get_soup(url)
            
            # 查找赛程表格
            table = soup.find('table', id='games')
            if not table:
                raise Exception("找不到赛程表格")
            
            # 解析表格数据
            df = pd.read_html(str(table))[0]
            return df
        
        return self._retry_with_backoff(_get_schedule)
    
    def get_player_gamelog(self, player_id, season):
        """
        获取球员比赛日志
        
        Args:
            player_id: 球员ID，如 'jamesle01'
            season: 赛季，如 '2023-24'
            
        Returns:
            球员比赛日志数据
        """
        season_end = season.split('-')[1]
        url = f"{self.base_url}/players/{player_id[0]}/{player_id}/gamelog/{season_end}"
        
        def _get_gamelog():
            soup = self._get_soup(url)
            
            # 查找比赛日志表格
            table = soup.find('table', id='pgl_basic')
            if not table:
                raise Exception("找不到比赛日志表格")
            
            # 解析表格数据
            df = pd.read_html(str(table))[0]
            return df
        
        return self._retry_with_backoff(_get_gamelog)
    
    def get_standings(self, season):
        """
        获取赛季排名
        
        Args:
            season: 赛季，如 '2023-24'
            
        Returns:
            赛季排名数据
        """
        season_end = season.split('-')[1]
        url = f"{self.base_url}/leagues/NBA_{season_end}_standings.html"
        
        def _get_standings():
            soup = self._get_soup(url)
            
            # 查找东部联盟排名表格
            east_table = soup.find('table', id='confs_standings_E')
            # 查找西部联盟排名表格
            west_table = soup.find('table', id='confs_standings_W')
            
            if not east_table or not west_table:
                raise Exception("找不到排名表格")
            
            # 解析表格数据
            east_df = pd.read_html(str(east_table))[0]
            west_df = pd.read_html(str(west_table))[0]
            
            return {'east': east_df, 'west': west_df}
        
        return self._retry_with_backoff(_get_standings)

    def scrape_per_game_stats_playwright(self, season, output_dir=None):
        """
        使用 Playwright 抓取赛季球员每场平均数据
        
        Args:
            season: 赛季年份，如 2026
            output_dir: 输出目录，默认为当前目录
            
        Returns:
            DataFrame包含球员数据
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise Exception("Playwright 未安装，无法使用此功能")
        
        url = f"{self.base_url}/leagues/NBA_{season}_per_game.html"
        
        logger.info(f"正在访问: {url}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(user_agent=self.headers["User-Agent"])
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

if __name__ == "__main__":
    # 测试Basketball Reference爬取器
    print("测试 requests 模式...")
    scraper = BasketballReferenceScraper()
    
    try:
        print("测试 Playwright 模式...")
        scraper_pw = BasketballReferenceScraper(use_playwright=True, headless=False)
        df = scraper_pw.scrape_per_game_stats_playwright(2026, output_dir="nba_data/CSV")
        print("\n数据前5行预览:")
        print(df.head())
    except Exception as e:
        print(f"Playwright 测试失败: {e}")
        print("回退到 requests 模式测试...")
        try:
            team_stats = scraper.get_team_stats('LAL', '2023-24')
            print("球队统计数据获取成功:")
            print(team_stats.head())
        except Exception as e2:
            print(f"测试失败: {e2}")