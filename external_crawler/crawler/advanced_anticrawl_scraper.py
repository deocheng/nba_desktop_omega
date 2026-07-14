#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高级反爬爬虫 - 长期稳定运行，避免被封禁
包含：代理IP池、智能延迟、真实用户行为模拟、Cookie管理、智能调度
"""
import requests
import time
import random
import logging
import json
import os
from datetime import datetime, time as dt_time
from typing import Optional, Dict, Any, List
from pathlib import Path
from playwright.sync_api import sync_playwright
import hashlib

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ProxyPool:
    """代理IP池管理"""
    
    def __init__(self, proxy_file='nba_data/crawler/proxy_pool.json'):
        self.proxy_file = Path(proxy_file)
        self.proxies = []
        self.failed_proxies = set()
        self.current_index = 0
        self.load_proxies()
    
    def load_proxies(self):
        """加载代理IP列表"""
        if self.proxy_file.exists():
            try:
                with open(self.proxy_file, 'r') as f:
                    data = json.load(f)
                    self.proxies = data.get('proxies', [])
                logger.info(f"已加载 {len(self.proxies)} 个代理IP")
            except Exception as e:
                logger.error(f"加载代理IP失败: {e}")
                self.proxies = []
        
        # 如果没有代理，使用空列表（直连模式）
        if not self.proxies:
            logger.warning("没有配置代理IP，将使用直连模式")
    
    def get_proxy(self) -> Optional[Dict]:
        """获取下一个可用的代理IP"""
        if not self.proxies:
            return None
        
        # 跳过失败的代理
        available_proxies = [p for p in self.proxies if p.get('ip') not in self.failed_proxies]
        
        if not available_proxies:
            logger.warning("所有代理IP都已失败，重置失败列表")
            self.failed_proxies.clear()
            available_proxies = self.proxies
        
        # 随机选择一个代理
        proxy = random.choice(available_proxies)
        self.current_index = (self.current_index + 1) % len(available_proxies)
        
        return {
            'http': f"http://{proxy.get('ip')}:{proxy.get('port')}",
            'https': f"http://{proxy.get('ip')}:{proxy.get('port')}"
        }
    
    def mark_failed(self, proxy_ip: str):
        """标记失败的代理IP"""
        self.failed_proxies.add(proxy_ip)
        logger.warning(f"代理IP {proxy_ip} 已标记为失败")
    
    def save_proxies(self):
        """保存代理IP列表"""
        try:
            with open(self.proxy_file, 'w') as f:
                json.dump({'proxies': self.proxies}, f, indent=2)
            logger.info(f"已保存 {len(self.proxies)} 个代理IP")
        except Exception as e:
            logger.error(f"保存代理IP失败: {e}")


class CookieManager:
    """Cookie管理器"""
    
    def __init__(self, cookie_file='nba_data/crawler/cookies.json'):
        self.cookie_file = Path(cookie_file)
        self.cookies = {}
        self.load_cookies()
    
    def load_cookies(self):
        """加载保存的Cookie"""
        if self.cookie_file.exists():
            try:
                with open(self.cookie_file, 'r') as f:
                    self.cookies = json.load(f)
                logger.info(f"已加载 {len(self.cookies)} 个Cookie")
            except Exception as e:
                logger.error(f"加载Cookie失败: {e}")
    
    def save_cookies(self, domain: str, cookies: List[Dict]):
        """保存Cookie"""
        self.cookies[domain] = {
            'cookies': cookies,
            'updated_at': datetime.now().isoformat()
        }
        
        try:
            with open(self.cookie_file, 'w') as f:
                json.dump(self.cookies, f, indent=2)
            logger.info(f"已保存 {domain} 的Cookie")
        except Exception as e:
            logger.error(f"保存Cookie失败: {e}")
    
    def get_cookies(self, domain: str) -> List[Dict]:
        """获取指定域名的Cookie"""
        return self.cookies.get(domain, {}).get('cookies', [])


class SmartScheduler:
    """智能调度器 - 避开高峰时段，控制爬取频率"""
    
    # 高峰时段（避免爬取）
    PEAK_HOURS = [
        (dt_time(9, 0), dt_time(12, 0)),   # 上午高峰
        (dt_time(14, 0), dt_time(17, 0)),  # 下午高峰
        (dt_time(19, 0), dt_time(22, 0)),  # 晚间高峰
    ]
    
    # 低峰时段（适合爬取）
    LOW_HOURS = [
        (dt_time(0, 0), dt_time(6, 0)),    # 夜间
        (dt_time(12, 0), dt_time(14, 0)),  # 午休
        (dt_time(17, 0), dt_time(19, 0)),  # 晚饭
    ]
    
    def __init__(self):
        self.daily_limit = 1000  # 每日爬取限制
        self.hourly_limit = 100  # 每小时爬取限制
        self.request_count = {'daily': 0, 'hourly': 0}
        self.last_reset = datetime.now()
    
    def is_peak_hour(self) -> bool:
        """判断当前是否是高峰时段"""
        now = datetime.now().time()
        for start, end in self.PEAK_HOURS:
            if start <= now <= end:
                return True
        return False
    
    def get_recommended_delay(self) -> float:
        """获取推荐的延迟时间"""
        if self.is_peak_hour():
            # 高峰时段：更长延迟
            return random.uniform(15, 30)
        else:
            # 低峰时段：正常延迟
            return random.uniform(8, 15)
    
    def can_crawl(self) -> bool:
        """判断是否可以继续爬取"""
        now = datetime.now()
        
        # 重置计数器
        if now.hour != self.last_reset.hour:
            self.request_count['hourly'] = 0
        if now.day != self.last_reset.day:
            self.request_count['daily'] = 0
        
        self.last_reset = now
        
        # 检查限制
        if self.request_count['daily'] >= self.daily_limit:
            logger.warning(f"已达到每日限制 {self.daily_limit}")
            return False
        
        if self.request_count['hourly'] >= self.hourly_limit:
            logger.warning(f"已达到每小时限制 {self.hourly_limit}")
            return False
        
        return True
    
    def record_request(self):
        """记录一次请求"""
        self.request_count['daily'] += 1
        self.request_count['hourly'] += 1


class AdvancedAntiCrawlScraper:
    """高级反爬爬虫 - 长期稳定运行"""
    
    USER_AGENTS = [
        # Chrome
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        # Firefox
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
        # Safari
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        # Edge
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36",
    ]
    
    BASE_URL = "https://www.basketball-reference.com"
    
    def __init__(self, use_proxy=False, use_playwright=True):
        self.use_proxy = use_proxy
        self.use_playwright = use_playwright
        self.proxy_pool = ProxyPool() if use_proxy else None
        self.cookie_manager = CookieManager()
        self.scheduler = SmartScheduler()
        self.session = requests.Session()
        self.browser_context = None
        self.playwright_browser = None
        
        logger.info("=" * 60)
        logger.info("🚀 高级反爬爬虫已初始化")
        logger.info(f"   - 代理模式: {'启用' if use_proxy else '禁用'}")
        logger.info(f"   - Playwright模式: {'启用' if use_playwright else '禁用'}")
        logger.info(f"   - 每日限制: {self.scheduler.daily_limit}")
        logger.info(f"   - 每小时限制: {self.scheduler.hourly_limit}")
        logger.info("=" * 60)
    
    def _simulate_human_behavior(self, page):
        """模拟真实用户行为"""
        # 随机滚动
        scroll_times = random.randint(2, 5)
        for _ in range(scroll_times):
            scroll_distance = random.randint(100, 500)
            page.evaluate(f"window.scrollBy(0, {scroll_distance})")
            time.sleep(random.uniform(0.5, 1.5))
        
        # 随机鼠标移动
        try:
            page.mouse.move(random.randint(0, 1000), random.randint(0, 600))
            time.sleep(random.uniform(0.3, 0.8))
        except:
            pass
    
    def _get_smart_delay(self) -> float:
        """获取智能延迟时间"""
        base_delay = self.scheduler.get_recommended_delay()
        
        # 根据最近的请求成功率动态调整
        # 如果最近有失败，增加延迟
        # 如果连续成功，可以稍微减少延迟
        
        return base_delay
    
    def crawl_with_playwright(self, url: str, wait_time: int = 10) -> str:
        """使用Playwright爬取（模拟真实浏览器）"""
        if not self.scheduler.can_crawl():
            raise Exception("已达到爬取限制，请等待下一时段")
        
        delay = self._get_smart_delay()
        logger.info(f"智能延迟: {delay:.2f} 秒")
        time.sleep(delay)
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            # 使用随机User-Agent
            user_agent = random.choice(self.USER_AGENTS)
            context = browser.new_context(user_agent=user_agent)
            page = context.new_page()
            
            # 加载Cookie
            cookies = self.cookie_manager.get_cookies('basketball-reference.com')
            if cookies:
                context.add_cookies(cookies)
            
            try:
                logger.info(f"正在访问: {url}")
                response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                if response.status == 403 or response.status == 429:
                    logger.warning(f"收到 {response.status} 状态码")
                    # 如果使用代理，标记当前代理失败
                    if self.use_proxy and self.proxy_pool:
                        # 这里需要记录当前使用的代理IP
                        pass
                    
                    # 等待更长时间
                    wait_longer = random.uniform(60, 120)
                    logger.warning(f"等待 {wait_longer:.2f} 秒后重试")
                    time.sleep(wait_longer)
                    
                    # 重新请求
                    response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # 模拟真实用户行为
                self._simulate_human_behavior(page)
                
                # 等待页面加载
                time.sleep(wait_time)
                
                # 保存Cookie
                cookies = context.cookies()
                self.cookie_manager.save_cookies('basketball-reference.com', cookies)
                
                # 获取页面内容
                content = page.content()
                
                # 记录请求
                self.scheduler.record_request()
                
                logger.info(f"✅ 成功获取页面，长度: {len(content)}")
                
                return content
                
            except Exception as e:
                logger.error(f"❌ 爬取失败: {e}")
                raise
            finally:
                browser.close()
    
    def crawl_with_requests(self, url: str) -> str:
        """使用requests爬取（带代理和反爬）"""
        if not self.scheduler.can_crawl():
            raise Exception("已达到爬取限制，请等待下一时段")
        
        delay = self._get_smart_delay()
        logger.info(f"智能延迟: {delay:.2f} 秒")
        time.sleep(delay)
        
        # 设置请求头
        headers = {
            'User-Agent': random.choice(self.USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'Referer': self.BASE_URL
        }
        
        # 获取代理
        proxies = None
        if self.use_proxy and self.proxy_pool:
            proxies = self.proxy_pool.get_proxy()
            if proxies:
                logger.info(f"使用代理: {proxies.get('http', '').split('@')[0] if '@' in proxies.get('http', '') else proxies.get('http', '')}")
        
        try:
            response = self.session.get(url, headers=headers, proxies=proxies, timeout=60)
            
            if response.status_code == 403 or response.status_code == 429:
                logger.warning(f"收到 {response.status_code} 状态码")
                
                # 如果使用代理，标记失败
                if self.use_proxy and self.proxy_pool and proxies:
                    proxy_ip = proxies.get('http', '').split('//')[1].split(':')[0] if '//' in proxies.get('http', '') else ''
                    self.proxy_pool.mark_failed(proxy_ip)
                
                # 等待更长时间
                wait_longer = random.uniform(60, 120)
                logger.warning(f"等待 {wait_longer:.2f} 秒后重试")
                time.sleep(wait_longer)
                
                # 使用新的代理重试
                if self.use_proxy and self.proxy_pool:
                    proxies = self.proxy_pool.get_proxy()
                
                response = self.session.get(url, headers=headers, proxies=proxies, timeout=60)
            
            response.raise_for_status()
            
            # 记录请求
            self.scheduler.record_request()
            
            logger.info(f"✅ 成功获取页面，长度: {len(response.text)}")
            
            return response.text
            
        except Exception as e:
            logger.error(f"❌ 爬取失败: {e}")
            raise
    
    def crawl(self, url: str) -> str:
        """智能爬取 - 自动选择最佳方式"""
        if self.use_playwright:
            return self.crawl_with_playwright(url)
        else:
            return self.crawl_with_requests(url)
    
    def get_player_list(self, letter: str) -> str:
        """获取球员列表"""
        url = f"{self.BASE_URL}/players/{letter.lower()}/"
        return self.crawl(url)
    
    def get_team_season(self, team_abbr: str, season: str) -> str:
        """获取球队赛季数据"""
        year = int(season.split('-')[1])
        url = f"{self.BASE_URL}/teams/{team_abbr}/{year}.html"
        return self.crawl(url)
    
    def get_player_page(self, player_id: str) -> str:
        """获取球员页面"""
        url = f"{self.BASE_URL}/players/{player_id[0].lower()}/{player_id}.html"
        return self.crawl(url)


class SafeCrawlerManager:
    """安全爬取管理器 - 控制整体爬取节奏"""
    
    def __init__(self):
        self.scraper = AdvancedAntiCrawlScraper(use_proxy=False, use_playwright=True)
        self.progress_file = Path('nba_data/crawler/safe_crawler_progress.json')
        self.progress = self.load_progress()
    
    def load_progress(self) -> Dict:
        """加载进度"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_progress(self):
        """保存进度"""
        with open(self.progress_file, 'w') as f:
            json.dump(self.progress, f, indent=2)
    
    def crawl_team_data_safe(self, teams: List[str], seasons: List[str]):
        """安全地爬取球队数据"""
        logger.info("=" * 60)
        logger.info("🚀 开始安全爬取球队数据")
        logger.info(f"   球队数量: {len(teams)}")
        logger.info(f"   赛季数量: {len(seasons)}")
        logger.info(f"   总任务数: {len(teams) * len(seasons)}")
        logger.info("=" * 60)
        
        for team in teams:
            for season in seasons:
                task_key = f"{team}_{season}"
                
                # 检查是否已完成
                if self.progress.get(task_key) == 'completed':
                    logger.info(f"跳过已完成: {team} {season}")
                    continue
                
                # 检查是否可以爬取
                if not self.scraper.scheduler.can_crawl():
                    logger.warning("已达到爬取限制，暂停爬取")
                    logger.info("将在下一个低峰时段继续")
                    break
                
                try:
                    logger.info(f"正在爬取: {team} {season}")
                    html = self.scraper.get_team_season(team, season)
                    
                    # 保存数据
                    self.save_team_data(team, season, html)
                    
                    # 更新进度
                    self.progress[task_key] = 'completed'
                    self.save_progress()
                    
                    logger.info(f"✅ 完成: {team} {season}")
                    
                except Exception as e:
                    logger.error(f"❌ 失败: {team} {season} - {e}")
                    self.progress[task_key] = 'failed'
                    self.save_progress()
                    
                    # 如果连续失败，暂停爬取
                    time.sleep(300)  # 等待5分钟
    
    def save_team_data(self, team: str, season: str, html: str):
        """保存球队数据"""
        data_dir = Path('nba_data/crawler/crawler_data/team_data')
        data_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{team}_{season}_raw.html"
        filepath = data_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        
        logger.info(f"数据已保存: {filepath}")


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 高级反爬爬虫测试")
    print("=" * 60)
    
    # 创建爬虫
    scraper = AdvancedAntiCrawlScraper(use_proxy=False, use_playwright=True)
    
    # 测试爬取
    try:
        print("\n🔍 测试爬取...")
        html = scraper.get_player_list('a')
        print(f"✅ 成功获取页面，长度: {len(html)}")
        
        # 显示调度状态
        print("\n📊 调度状态:")
        print(f"   - 当前时段: {'高峰' if scraper.scheduler.is_peak_hour() else '低峰'}")
        print(f"   - 今日已爬取: {scraper.scheduler.request_count['daily']}")
        print(f"   - 本小时已爬取: {scraper.scheduler.request_count['hourly']}")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")