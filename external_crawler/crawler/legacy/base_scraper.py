#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
爬虫基类 - 包含 User-Agent 轮换、请求延迟、反爬机制和指数退避重试
优化版：更完善的反爬机制，模拟真实浏览器
"""
import requests
import time
import random
import logging
import json
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime, time as dt_time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CookieManager:
    """Cookie管理器 - 保持会话状态"""
    
    def __init__(self, cookie_file='nba_data/crawler/base_cookies.json'):
        self.cookie_file = Path(cookie_file)
        self.cookies = []
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
                self.cookies = []
    
    def save_cookies(self):
        """保存Cookie"""
        try:
            with open(self.cookie_file, 'w') as f:
                json.dump(self.cookies, f, indent=2)
            logger.info("Cookie已保存")
        except Exception as e:
            logger.error(f"保存Cookie失败: {e}")
    
    def update_from_response(self, response):
        """从响应更新Cookie"""
        # 将requests CookieJar转换为字典列表
        for cookie in response.cookies:
            cookie_dict = {
                'name': cookie.name,
                'value': cookie.value,
                'domain': cookie.domain,
                'path': cookie.path,
                'expires': cookie.expires
            }
            # 检查是否已存在
            exists = False
            for i, existing in enumerate(self.cookies):
                if existing.get('name') == cookie.name and existing.get('domain') == cookie.domain:
                    self.cookies[i] = cookie_dict
                    exists = True
                    break
            if not exists:
                self.cookies.append(cookie_dict)
        
        self.save_cookies()
    
    def apply_to_session(self, session):
        """将Cookie应用到session"""
        if self.cookies:
            for cookie in self.cookies:
                session.cookies.set(
                    cookie.get('name'),
                    cookie.get('value'),
                    domain=cookie.get('domain'),
                    path=cookie.get('path')
                )
        return session


class SmartScheduler:
    """智能调度器 - 控制爬取节奏"""
    
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
        self.daily_limit = 300  # 每日爬取限制（更保守）
        self.hourly_limit = 30  # 每小时爬取限制（更保守）
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
            return random.uniform(30, 60)
        else:
            # 低峰时段：正常延迟
            return random.uniform(20, 40)
    
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


class BaseScraper:
    """带有完善反爬机制的爬虫基类，模拟真实浏览器行为"""

    USER_AGENTS = [
        # Chrome (Windows)
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        # Edge (Windows)
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/119.0.0.0 Safari/537.36",
        # Chrome (Mac)
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        # Safari (Mac)
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        # Chrome (Linux)
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        # Firefox (Windows)
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        # Firefox (Mac)
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0",
    ]

    MAX_RETRIES = 10  # 增加重试次数
    TIMEOUT = 90  # 增加超时时间
    RATE_LIMIT_WAIT_MIN = 120  # 增加等待时间
    RATE_LIMIT_WAIT_MAX = 240
    FORBIDDEN_WAIT_MIN = 300  # 403等待5分钟
    FORBIDDEN_WAIT_MAX = 600

    def __init__(self, delay_min=20, delay_max=40):
        self.session = requests.Session()
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.cookie_manager = CookieManager()
        self.scheduler = SmartScheduler()
        self._setup_session()

    def _setup_session(self):
        """配置会话 - 模拟真实浏览器"""
        # 应用保存的Cookie
        self.cookie_manager.apply_to_session(self.session)
        
        # 完整的浏览器请求头
        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'DNT': '1'
        })
        
        logger.info("会话已配置")

    def _get_random_user_agent(self) -> str:
        """随机选择 User-Agent"""
        ua = random.choice(self.USER_AGENTS)
        logger.debug(f"选择 User-Agent: {ua[:60]}...")
        return ua

    def _smart_delay(self) -> float:
        """智能延迟 - 根据时段动态调整"""
        delay = self.scheduler.get_recommended_delay()
        logger.info(f"智能延迟等待: {delay:.2f} 秒 (时段: {'高峰' if self.scheduler.is_peak_hour() else '低峰'})")
        time.sleep(delay)
        return delay

    def _handle_rate_limit(self) -> float:
        """处理429速率限制，等待更长时间"""
        wait_time = random.uniform(self.RATE_LIMIT_WAIT_MIN, self.RATE_LIMIT_WAIT_MAX)
        logger.warning(f"触发429速率限制，等待: {wait_time:.2f} 秒")
        time.sleep(wait_time)
        return wait_time

    def _handle_forbidden(self) -> float:
        """处理403禁止访问，等待更长时间"""
        wait_time = random.uniform(self.FORBIDDEN_WAIT_MIN, self.FORBIDDEN_WAIT_MAX)
        logger.warning(f"触发403禁止访问，等待: {wait_time:.2f} 秒")
        time.sleep(wait_time)
        return wait_time

    def _retry_with_backoff(self, func, *args, max_retries: Optional[int] = None, **kwargs) -> Any:
        """指数退避重试机制，失败后等待时间指数增长（2^attempt秒）

        Args:
            func: 要重试的函数
            *args: 函数参数
            max_retries: 最大重试次数，默认使用类属性 MAX_RETRIES
            **kwargs: 函数关键字参数

        Returns:
            函数返回值

        Raises:
            最后一次重试失败后抛出异常
        """
        if max_retries is None:
            max_retries = self.MAX_RETRIES

        last_exception = None

        for attempt in range(max_retries):
            try:
                result = func(*args, **kwargs)
                if attempt > 0:
                    logger.info(f"第 {attempt + 1} 次重试成功")
                return result
            except requests.exceptions.Timeout:
                last_exception = Exception(f"请求超时（尝试 {attempt + 1}/{max_retries}）")
                logger.warning(f"请求超时（尝试 {attempt + 1}/{max_retries}），等待 {2 ** attempt:.2f} 秒后重试")
                time.sleep(2 ** attempt)
            except requests.exceptions.ConnectionError as e:
                last_exception = e
                logger.warning(f"连接错误（尝试 {attempt + 1}/{max_retries}）: {e}，等待 {2 ** attempt:.2f} 秒后重试")
                time.sleep(2 ** attempt)
            except requests.exceptions.HTTPError as e:
                response = e.response
                if response.status_code == 429:
                    wait_time = self._handle_rate_limit()
                    last_exception = e
                    logger.warning(f"429速率限制（尝试 {attempt + 1}/{max_retries}），已等待 {wait_time:.2f} 秒")
                elif response.status_code == 403:
                    wait_time = self._handle_forbidden()
                    last_exception = e
                    logger.warning(f"403禁止访问（尝试 {attempt + 1}/{max_retries}），已等待 {wait_time:.2f} 秒")
                else:
                    logger.error(f"HTTP错误 {response.status_code}: {e}")
                    raise
            except Exception as e:
                last_exception = e
                logger.error(f"请求异常（尝试 {attempt + 1}/{max_retries}）: {e}，等待 {2 ** attempt:.2f} 秒后重试")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)

        logger.error(f"达到最大重试次数 {max_retries}，最终失败")
        raise last_exception

    def _make_request(self, url: str, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> requests.Response:
        """发送请求 - 模拟真实浏览器，包含完善的反爬机制

        Args:
            url: 请求URL
            params: URL参数
            headers: 自定义请求头

        Returns:
            requests.Response 对象

        Raises:
            requests.exceptions.HTTPError: HTTP错误
            requests.exceptions.Timeout: 请求超时
            requests.exceptions.ConnectionError: 连接错误
        """
        # 检查是否可以爬取（达到限制则等待）
        if not self.scheduler.can_crawl():
            raise Exception("已达到爬取限制，请等待下一时段")
        
        # 智能延迟
        delay_time = self._smart_delay()

        # 完整的浏览器请求头
        request_headers = {
            'User-Agent': self._get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'Referer': 'https://www.basketball-reference.com/',
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'DNT': '1'
        }

        if headers:
            request_headers.update(headers)

        start_time = time.time()
        logger.info(f"发起请求: URL={url}, 参数={params}")

        # 发送请求
        response = self.session.get(url, params=params, headers=request_headers, timeout=self.TIMEOUT)

        elapsed_time = time.time() - start_time
        logger.info(f"请求完成: URL={url}, 状态码={response.status_code}, 耗时={elapsed_time:.2f}秒, 延迟={delay_time:.2f}秒")

        # 更新Cookie
        self.cookie_manager.update_from_response(response)
        
        # 记录请求
        self.scheduler.record_request()

        # 处理错误状态码
        if response.status_code == 429:
            wait_time = self._handle_rate_limit()
            logger.warning(f"收到429状态码，重新发起请求")
            response = self.session.get(url, params=params, headers=request_headers, timeout=self.TIMEOUT)
            logger.info(f"重试请求完成: URL={url}, 状态码={response.status_code}")
        elif response.status_code == 403:
            wait_time = self._handle_forbidden()
            logger.warning(f"收到403状态码，重新发起请求")
            response = self.session.get(url, params=params, headers=request_headers, timeout=self.TIMEOUT)
            logger.info(f"重试请求完成: URL={url}, 状态码={response.status_code}")

        response.raise_for_status()
        return response

class BBRefScraper(BaseScraper):
    """Basketball Reference 专用爬虫"""
    
    BASE_URL = "https://www.basketball-reference.com"
    
    def get_player_page(self, player_id):
        """获取球员页面"""
        url = f"{self.BASE_URL}/players/{player_id[0].lower()}/{player_id}.html"
        response = self._make_request(url)
        return response.text
    
    def get_player_list(self, letter):
        """获取字母开头的球员列表"""
        url = f"{self.BASE_URL}/players/{letter.lower()}/"
        response = self._make_request(url)
        return response.text

if __name__ == "__main__":
    scraper = BBRefScraper(delay_min=20, delay_max=40)
    print("=" * 80)
    print("🚀 优化版反爬爬虫已配置完成")
    print("=" * 80)
    print(f"📋 User-Agent 数量: {len(scraper.USER_AGENTS)}")
    print(f"⏱️ 请求延迟: {scraper.delay_min}-{scraper.delay_max}秒")
    print(f"📊 每日限制: {scraper.scheduler.daily_limit} 次")
    print(f"📊 每小时限制: {scraper.scheduler.hourly_limit} 次")
    print(f"⏰ 当前时段: {'高峰' if scraper.scheduler.is_peak_hour() else '低峰'}")
    print("=" * 80)
    print("\n⚠️  注意：当前IP可能已被封禁，请等待24-48小时后再测试")
    print("💡 建议：使用现有数据库进行数据分析")