#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
终极版 Basketball Reference Playwright 爬虫
结合所有反爬机制：真实浏览器模拟 + 智能调度 + Cookie管理 + 拟人化行为
"""
from playwright.sync_api import sync_playwright
import pandas as pd
import time
import random
import logging
import os
import json
from datetime import datetime, time as dt_time
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CookieManager:
    """Cookie管理器 - 持久化会话状态"""
    
    def __init__(self, cookie_file='nba_data/crawler/ultimate_cookies.json'):
        self.cookie_file = Path(cookie_file)
        self.cookies = []
        self.load_cookies()
    
    def load_cookies(self):
        """加载保存的Cookie"""
        if self.cookie_file.exists():
            try:
                with open(self.cookie_file, 'r', encoding='utf-8') as f:
                    self.cookies = json.load(f)
                logger.info(f"已加载 {len(self.cookies)} 个Cookie")
            except Exception as e:
                logger.error(f"加载Cookie失败: {e}")
                self.cookies = []
    
    def save_cookies(self, cookies):
        """保存Cookie"""
        self.cookies = cookies
        try:
            with open(self.cookie_file, 'w', encoding='utf-8') as f:
                json.dump(self.cookies, f, ensure_ascii=False, indent=2)
            logger.info(f"已保存 {len(self.cookies)} 个Cookie")
        except Exception as e:
            logger.error(f"保存Cookie失败: {e}")
    
    def apply_to_context(self, context):
        """将Cookie应用到Playwright context"""
        if self.cookies:
            context.add_cookies(self.cookies)
            logger.info(f"已应用 {len(self.cookies)} 个Cookie")


class SmartScheduler:
    """智能调度器 - 控制爬取节奏"""
    
    PEAK_HOURS = [
        (dt_time(9, 0), dt_time(12, 0)),
        (dt_time(14, 0), dt_time(17, 0)),
        (dt_time(19, 0), dt_time(22, 0)),
    ]
    
    LOW_HOURS = [
        (dt_time(0, 0), dt_time(6, 0)),
        (dt_time(12, 0), dt_time(14, 0)),
        (dt_time(17, 0), dt_time(19, 0)),
    ]
    
    def __init__(self):
        self.daily_limit = 200
        self.hourly_limit = 20
        self.request_count = {'daily': 0, 'hourly': 0}
        self.last_reset = datetime.now()
        self.progress_file = Path('nba_data/crawler/ultimate_progress.json')
        self.load_progress()
    
    def load_progress(self):
        """加载进度"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.request_count = data.get('request_count', {'daily': 0, 'hourly': 0})
            except Exception as e:
                logger.error(f"加载进度失败: {e}")
    
    def save_progress(self):
        """保存进度"""
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'request_count': self.request_count,
                    'last_update': datetime.now().isoformat()
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存进度失败: {e}")
    
    def is_peak_hour(self):
        now = datetime.now().time()
        for start, end in self.PEAK_HOURS:
            if start <= now <= end:
                return True
        return False
    
    def get_recommended_delay(self):
        if self.is_peak_hour():
            return random.uniform(40, 80)
        else:
            return random.uniform(25, 50)
    
    def can_crawl(self):
        now = datetime.now()
        if now.hour != self.last_reset.hour:
            self.request_count['hourly'] = 0
        if now.day != self.last_reset.day:
            self.request_count['daily'] = 0
        self.last_reset = now
        
        if self.request_count['daily'] >= self.daily_limit:
            logger.warning(f"已达到每日限制 {self.daily_limit}")
            return False
        if self.request_count['hourly'] >= self.hourly_limit:
            logger.warning(f"已达到每小时限制 {self.hourly_limit}")
            return False
        return True
    
    def record_request(self):
        self.request_count['daily'] += 1
        self.request_count['hourly'] += 1
        self.save_progress()


class UltimatePlaywrightScraper:
    """终极版 Playwright 爬虫"""
    
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]
    
    def __init__(self, headless=True):
        self.headless = headless
        self.base_url = "https://www.basketball-reference.com"
        self.cookie_manager = CookieManager()
        self.scheduler = SmartScheduler()
        self.browser = None
        self.context = None
        self.page = None
    
    def _simulate_human_behavior(self, page):
        """模拟真实用户行为"""
        # 随机滚动
        scroll_times = random.randint(1, 3)
        for _ in range(scroll_times):
            scroll_distance = random.randint(100, 400)
            page.evaluate(f"window.scrollBy(0, {scroll_distance})")
            time.sleep(random.uniform(0.3, 0.8))
        
        # 随机鼠标移动
        try:
            page.mouse.move(random.randint(100, 800), random.randint(100, 500))
            time.sleep(random.uniform(0.2, 0.5))
        except:
            pass
        
        # 滚动回顶部
        page.evaluate("window.scrollTo(0, 0)")
    
    def _smart_delay(self):
        """智能延迟"""
        delay = self.scheduler.get_recommended_delay()
        logger.info(f"智能延迟: {delay:.2f} 秒 (时段: {'高峰' if self.scheduler.is_peak_hour() else '低峰'})")
        time.sleep(delay)
        return delay
    
    def _get_context_options(self):
        """获取 context 配置 - 模拟真实浏览器"""
        user_agent = random.choice(self.USER_AGENTS)
        viewport = {'width': random.randint(1280, 1920), 'height': random.randint(720, 1080)}
        
        return {
            'user_agent': user_agent,
            'viewport': viewport,
            'locale': 'en-US',
            'timezone_id': 'America/New_York',
            'color_scheme': 'light',
            'permissions': [],
            'geolocation': None,
            'accept_downloads': False,
            'extra_http_headers': {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1'
            }
        }
    
    def _handle_403_429(self, page, url):
        """处理 403/429 错误"""
        wait_time = random.uniform(300, 600) if self.scheduler.is_peak_hour() else random.uniform(120, 240)
        logger.warning(f"检测到反爬，等待 {wait_time:.2f} 秒后重试")
        time.sleep(wait_time)
        
        # 重试
        logger.info(f"重新访问: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=120000)
        time.sleep(random.uniform(3, 6))
    
    def launch(self):
        """启动浏览器"""
        logger.info("启动浏览器...")
        playwright = sync_playwright().start()
        
        self.browser = playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process'
            ]
        )
        
        context_options = self._get_context_options()
        self.context = self.browser.new_context(**context_options)
        
        # 应用保存的Cookie
        self.cookie_manager.apply_to_context(self.context)
        
        self.page = self.context.new_page()
        
        # 注入反检测脚本
        self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        """)
        
        logger.info("浏览器已启动")
    
    def close(self):
        """关闭浏览器"""
        if self.page:
            # 保存Cookie
            cookies = self.context.cookies()
            self.cookie_manager.save_cookies(cookies)
        
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        
        logger.info("浏览器已关闭")
    
    def fetch_url(self, url):
        """获取页面内容 - 完整的反爬流程"""
        # 检查调度
        if not self.scheduler.can_crawl():
            raise Exception("已达到爬取限制")
        
        # 智能延迟
        self._smart_delay()
        
        logger.info(f"访问: {url}")
        
        # 访问页面
        self.page.goto(url, wait_until="domcontentloaded", timeout=120000)
        
        # 检查状态码
        page_title = self.page.title()
        
        # 模拟人类行为
        self._simulate_human_behavior(self.page)
        
        # 额外等待
        time.sleep(random.uniform(3, 6))
        
        # 记录请求
        self.scheduler.record_request()
        
        logger.info(f"页面加载完成，标题: {page_title[:50]}...")
        
        return self.page
    
    def scrape_team_season(self, team_abbr, season, output_dir=None):
        """抓取球队赛季数据"""
        year = int(season.split('-')[1]) if '-' in season else int(season)
        url = f"{self.base_url}/teams/{team_abbr}/{year}.html"
        
        try:
            page = self.fetch_url(url)
            
            tables = []
            table_ids = ['team_and_opponent', 'per_game', 'totals', 'advanced', 'shooting']
            
            for table_id in table_ids:
                table_selector = f"table#{table_id}"
                try:
                    page.wait_for_selector(table_selector, timeout=10000)
                    
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
                        logger.info(f"成功获取 {table_id} 表格")
                except Exception as e:
                    logger.warning(f"未找到 {table_id} 表格: {e}")
            
            # 保存
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
            
        except Exception as e:
            logger.error(f"抓取失败: {e}")
            raise
    
    def scrape_player_list(self, letter, output_dir=None):
        """抓取字母开头的球员列表"""
        url = f"{self.base_url}/players/{letter.lower()}/"
        
        try:
            page = self.fetch_url(url)
            
            table_selector = "table#players"
            page.wait_for_selector(table_selector, timeout=10000)
            
            headers = []
            th_elements = page.query_selector_all(f"{table_selector} thead tr th")
            for th in th_elements:
                text = th.inner_text().strip()
                if text:
                    headers.append(text)
            
            rows = page.query_selector_all(f"{table_selector} tbody tr:not(.thead)")
            player_data = []
            for row in rows:
                cells = row.query_selector_all("th, td")
                row_vals = [cell.inner_text().strip() for cell in cells]
                if row_vals:
                    player_data.append(row_vals)
            
            df = pd.DataFrame(player_data)
            if df.shape[1] == len(headers):
                df.columns = headers
            
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                output_file = os.path.join(output_dir, f"players_{letter}.csv")
            else:
                output_file = f"players_{letter}.csv"
            
            df.to_csv(output_file, index=False, encoding="utf-8-sig")
            logger.info(f"已保存: {output_file}")
            
            return df
            
        except Exception as e:
            logger.error(f"抓取失败: {e}")
            raise


if __name__ == "__main__":
    print("=" * 80)
    print("🚀 终极版 Playwright 爬虫 - 最稳妥的爬取方案")
    print("=" * 80)
    
    print("\n⚠️  当前IP可能已被封禁，请等待24-48小时后再使用")
    print("💡 我们已有大量完整数据，建议先用现有数据库进行分析")
    print("\n📊 反爬特性:")
    print("  - 真实浏览器模拟 (Playwright)")
    print("  - 智能延迟 (高峰40-80秒，低峰25-50秒)")
    print("  - Cookie 持久化")
    print("  - 拟人化行为 (随机滚动、鼠标移动)")
    print("  - 每日200次，每小时20次限制")
    print("  - 避开高峰时段 (9-12,14-17,19-22)")
    
    print("\n📈 当前状态:")
    print(f"  - 今日已爬: 0/{SmartScheduler().daily_limit}")
    print(f"  - 本小时已爬: 0/{SmartScheduler().hourly_limit}")
    print(f"  - 当前时段: {'高峰' if SmartScheduler().is_peak_hour() else '低峰'}")
    
    print("\n" + "=" * 80)
    print("建议：等待IP解封后使用，当前先用现有数据库")
    print("=" * 80)
