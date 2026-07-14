#!/usr/bin/env python3
"""
NBA Daily Crawler - Standalone Edition
=======================================
整合所有Basketball Reference数据表的爬取规则，支持：
1. 自动启动PostgreSQL数据库
2. 使用undetected_chromedriver绕过Cloudflare
3. 默认爬取当天BR数据
4. 通过日志判断是否需要向前回填
5. team_game_splits等全部表的统一管理

用法:
  python nba_daily_crawler.py                    # 爬取今天的数据（默认）
  python nba_daily_crawler.py --date 2026-07-01  # 爬取指定日期
  python nba_daily_crawler.py --backfill 7       # 回填最近7天
  python nba_daily_crawler.py --table team_game_splits  # 只爬指定表
  python nba_daily_crawler.py --full-season 2026 # 爬取整个赛季
  python nba_daily_crawler.py --check            # 只检查状态不爬取
  python nba_daily_crawler.py --list-tables      # 列出所有支持的表
"""

# ============================================================
# 清除代理环境变量（必须在import之前执行）
# ============================================================
import os as _os
for _key in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
             'http_proxy', 'https_proxy', 'all_proxy']:
    _os.environ.pop(_key, None)

import sys
import time
import json
import random
import logging
import argparse
import subprocess
import socket
import re
import pickle
import atexit
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup

import psycopg2

try:
    import undetected_chromedriver as uc
except ImportError:
    print("缺少 undetected_chromedriver，正在安装...")
    subprocess.check_call([sys.executable, '-m', 'pip', 'install',
                           'undetected-chromedriver', '-q'])
    import undetected_chromedriver as uc


# ============================================================
# 配置
# ============================================================

class Config:
    # 数据库
    DB_HOST = 'localhost'
    DB_PORT = 5433
    DB_NAME = 'nba'
    DB_USER = 'postgres'
    DB_PASSWORD = 'postgres'

    # PostgreSQL服务名（Windows）
    PG_SERVICE_NAMES = [
        'postgresql-x64-17',
        'postgresql-x64-16',
        'postgresql-x64-15',
        'postgresql-x64-14',
        'postgresql-17',
        'postgresql-16',
        'postgresql-15',
    ]

    # BBRef
    BASE_URL = 'https://www.basketball-reference.com'

    # 速率限制
    REQUEST_INTERVAL_MIN = 10
    REQUEST_INTERVAL_MAX = 13
    MAX_REQUESTS_PER_DAY = 300
    MAX_RETRIES = 3

    # 路径
    LOG_DIR = r'C:\Users\Administrator\nba_data\logs'
    DATA_DIR = r'C:\Users\Administrator\nba_data'
    STATUS_FILE = _os.path.join(DATA_DIR, 'crawl_status.json')

    # 赛季配置
    REGULAR_SEASON_START_MONTH = 10
    PLAYOFF_END_MONTH = 6

    # 数据库缩写 -> BBRef缩写 映射
    DB_TO_BR_ABBR = {
        'BKN': 'BRK',
        'PHX': 'PHO',
        'CHA': 'CHO',
    }
    # 反向映射
    BR_TO_DB_ABBR = {v: k for k, v in DB_TO_BR_ABBR.items()}

    # Chrome版本（自动检测，回退到149）
    CHROME_VERSION_MAIN = None  # 运行时自动检测


# ============================================================
# Chrome版本检测
# ============================================================

def detect_chrome_version():
    """从Windows注册表检测Chrome主版本号"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Google\Chrome\BLBeacon'
        )
        version, _ = winreg.QueryValueEx(key, 'version')
        winreg.CloseKey(key)
        major = int(version.split('.')[0])
        print(f"[Chrome] 检测到版本: {version} (major={major})")
        return major
    except Exception:
        print("[Chrome] 无法从注册表检测版本，使用默认 149")
        return 149


# ============================================================
# 日志系统
# ============================================================

class CrawlLogger:
    """爬取日志管理，用于判断是否需要回填"""

    def __init__(self):
        _os.makedirs(Config.LOG_DIR, exist_ok=True)
        _os.makedirs(Config.DATA_DIR, exist_ok=True)

        today = date.today().strftime('%Y%m%d')
        self.log_file = _os.path.join(Config.LOG_DIR, f'crawl_{today}.log')

        self.logger = logging.getLogger('nba_crawler')
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()

        fh = logging.FileHandler(self.log_file, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s'))
        self.logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s'))
        self.logger.addHandler(ch)

    def info(self, msg): self.logger.info(msg)
    def warning(self, msg): self.logger.warning(msg)
    def error(self, msg): self.logger.error(msg)
    def debug(self, msg): self.logger.debug(msg)

    def load_status(self):
        if _os.path.exists(Config.STATUS_FILE):
            with open(Config.STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            'last_crawl_date': None,
            'last_full_season': None,
            'tables': {},
            'daily_history': [],
        }

    def save_status(self, status):
        with open(Config.STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status, f, indent=2, ensure_ascii=False)

    def get_last_crawl_date(self, table_name=None):
        status = self.load_status()
        if table_name and table_name in status['tables']:
            return status['tables'][table_name].get('last_date')
        return status.get('last_crawl_date')

    def get_missing_dates(self, table_name, end_date=None):
        """获取需要回填的日期列表"""
        if end_date is None:
            end_date = date.today()

        last_date = self.get_last_crawl_date(table_name)
        if last_date is None:
            return [end_date - timedelta(days=i) for i in range(7, 0, -1)]

        last = datetime.strptime(last_date, '%Y-%m-%d').date()
        if last >= end_date:
            return []

        missing = []
        current = last + timedelta(days=1)
        while current <= end_date:
            if (current.month >= Config.REGULAR_SEASON_START_MONTH
                    or current.month <= Config.PLAYOFF_END_MONTH):
                missing.append(current)
            current += timedelta(days=1)
        return missing

    def record_success(self, table_name, crawl_date, records=0, errors=0):
        status = self.load_status()
        today_str = date.today().strftime('%Y-%m-%d')

        if table_name not in status['tables']:
            status['tables'][table_name] = {}

        date_str = (crawl_date.strftime('%Y-%m-%d')
                    if isinstance(crawl_date, date) else crawl_date)

        status['tables'][table_name].update({
            'last_date': date_str,
            'last_run': today_str,
            'records': records,
            'errors': errors,
        })
        status['last_crawl_date'] = today_str

        status['daily_history'].append({
            'date': today_str,
            'table': table_name,
            'records': records,
            'errors': errors,
        })
        status['daily_history'] = status['daily_history'][-200:]
        self.save_status(status)


# ============================================================
# 数据库管理
# ============================================================

class DatabaseManager:
    """PostgreSQL数据库自动启动和连接管理"""

    @staticmethod
    def is_port_open(host='localhost', port=5433):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    @staticmethod
    def start_postgresql():
        for service_name in Config.PG_SERVICE_NAMES:
            try:
                result = subprocess.run(
                    ['net', 'start', service_name],
                    capture_output=True, text=True, timeout=30
                )
                if (result.returncode == 0
                        or '已经启动' in result.stdout
                        or 'already started' in result.stdout.lower()):
                    return True, f'Started service: {service_name}'
            except Exception:
                continue

        # 方法2: pg_ctl
        for pg_ver in ['17', '16', '15', '14']:
            pg_dir = rf'C:\Program Files\PostgreSQL\{pg_ver}'
            pg_ctl = _os.path.join(pg_dir, 'bin', 'pg_ctl.exe')
            data_dir = _os.path.join(pg_dir, 'data')
            if _os.path.exists(pg_ctl):
                try:
                    result = subprocess.run(
                        [pg_ctl, 'start', '-D', data_dir, '-w'],
                        capture_output=True, text=True, timeout=30
                    )
                    if result.returncode == 0:
                        return True, f'Started via pg_ctl: {pg_dir}'
                except Exception:
                    continue

        return False, 'Could not start PostgreSQL'

    @staticmethod
    def ensure_database_running():
        if DatabaseManager.is_port_open():
            return True

        print('[DB] PostgreSQL未运行，正在启动...')
        success, msg = DatabaseManager.start_postgresql()
        if success:
            print(f'[DB] {msg}')
            for _ in range(10):
                time.sleep(1)
                if DatabaseManager.is_port_open():
                    print('[DB] PostgreSQL已就绪')
                    return True
            print('[DB] 端口已开放但连接超时')
            return False
        else:
            print(f'[DB] 启动失败: {msg}')
            return False

    @staticmethod
    def get_connection():
        return psycopg2.connect(
            host=Config.DB_HOST, port=Config.DB_PORT,
            database=Config.DB_NAME, user=Config.DB_USER,
            password=Config.DB_PASSWORD
        )


# ============================================================
# 浏览器管理（undetected_chromedriver）
# ============================================================

class BrowserManager:
    """使用undetected_chromedriver管理Chrome浏览器，绕过Cloudflare"""

    def __init__(self, logger):
        self.logger = logger
        self.driver = None
        self.request_count = 0
        self.last_request_time = 0
        self._atexit_registered = False
        # CF 通过后的 cookie 持久化文件（落盘，跨会话复用，避免为过 CF 反复重开浏览器）
        self.COOKIE_FILE = _os.path.join(
            _os.path.dirname(_os.path.abspath(__file__)), '.br_cf_cookies.pkl')

        if Config.CHROME_VERSION_MAIN is None:
            Config.CHROME_VERSION_MAIN = detect_chrome_version()

    @staticmethod
    def _is_cf_page(page):
        """检测是否为Cloudflare挑战页面"""
        if not page or len(page) < 3000:
            return True
        cf_indicators = [
            'Just a moment', 'cf-challenge', 'challenge-platform',
            'cdn-cgi/challenge', 'cf-browser-verification',
            'cf-mitigated', 'Checking your browser',
            'Enable JavaScript and cookies', 'attentionRequired',
        ]
        return any(ind in page for ind in cf_indicators)

    def _navigate_and_wait(self, url, cf_timeout=60):
        """导航到URL并等待Cloudflare通过（全程复用同一浏览器，不重开）"""
        # 方法1: 直接用driver.get（UC会自动处理大部分Cloudflare）
        try:
            self.driver.get(url)
            self.request_count += 1
        except Exception:
            # urllib3超时(120s)——页面仍在后台加载
            self.request_count += 1

        # 等待2秒让可能的Cloudflare重定向完成
        time.sleep(2)

        # 快速检查：是否已获得实际页面
        page = self._try_get_real_page()
        if page is not None:
            return page

        # 方法2: 轮询等待Cloudflare挑战完成（同一个浏览器内重试，不重启）
        self.logger.debug(f'Cloudflare挑战中，轮询等待: {url}')
        for i in range(cf_timeout // 2):
            time.sleep(2)
            page = self._try_get_real_page()
            if page is not None:
                return page

        return None

    def _try_get_real_page(self):
        """取页面源码；若已通过CF则返回并持久化cookie，否则返回None。"""
        try:
            page = self.driver.page_source
        except Exception:
            return None
        if not self._is_cf_page(page):
            self._save_cookies()  # CF已通过，落盘以便跨会话复用，下次免挑战
            return page
        return None

    def _load_cookies(self):
        """启动后注入上次持久化的CF cookie，跳过重新挑战（无需为过CF重开浏览器）。"""
        if not _os.path.exists(self.COOKIE_FILE):
            return
        try:
            with open(self.COOKIE_FILE, 'rb') as f:
                cookies = pickle.load(f)
            # add_cookie 要求先访问对应域名，先轻量导航到 BASE_URL 建立上下文
            try:
                self.driver.get(Config.BASE_URL + '/')
                time.sleep(1)
            except Exception:
                pass
            injected = 0
            for c in cookies:
                try:
                    self.driver.add_cookie(c)
                    injected += 1
                except Exception:
                    pass
            self.logger.info(
                f'[Browser] 已注入 {injected}/{len(cookies)} 个 CF cookie，'
                f'后续导航可跳过 Cloudflare 挑战')
        except Exception as e:
            self.logger.warning(f'[Browser] cookie 载入失败（将重新过 CF）: {e}')

    def _save_cookies(self):
        """把当前会话的 cookie（含 cf_clearance 等）持久化到磁盘。"""
        try:
            cookies = self.driver.get_cookies()
            with open(self.COOKIE_FILE, 'wb') as f:
                pickle.dump(cookies, f)
        except Exception:
            pass

    def _register_atexit(self):
        """注册进程退出时回收浏览器，避免异常退出留下孤儿进程。"""
        if not self._atexit_registered:
            atexit.register(self.quit)
            self._atexit_registered = True

    def start(self):
        """启动Chrome浏览器（单次会话，全程复用，绝不中途关闭/重开）。

        单会话铁律（对齐'CF通过后不要频繁关闭重开浏览器'的要求）：
          - 本方法只应在整批任务开始时调用一次；
          - CF 二次挑战只在同一个 driver 内重新导航，不重启浏览器；
          - 启动时注入上次持久化的 CF cookie，可跳过重新挑战，也就无需为过 CF 而重开。
        """
        self.logger.info('[Browser] 启动 undetected_chromedriver（单次会话，全程复用）...')
        options = uc.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')

        # 本地预置 chromedriver 优先：绕过 uc 联网查版本
        # （googlechromelabs.com 在当前代理下不可达会直接导致启动崩）。
        # 仅当缓存目录存在匹配 version_main 的 driver 时才启用，否则回退默认行为。
        driver_path = None
        try:
            _ver_main = Config.CHROME_VERSION_MAIN or 0
            _cache_root = _os.path.join(
                _os.path.expanduser('~'), '.cache', 'undetected_chromedriver')
            if _os.path.isdir(_cache_root):
                for _d in _os.listdir(_cache_root):
                    if _d.startswith(f"{_ver_main}."):
                        for _root, _dirs, _files in _os.walk(_os.path.join(_cache_root, _d)):
                            if 'chromedriver.exe' in _files:
                                driver_path = _os.path.join(_root, 'chromedriver.exe')
                                break
                    if driver_path:
                        break
        except Exception:
            driver_path = None

        _chrome_kwargs = dict(options=options,
                              version_main=Config.CHROME_VERSION_MAIN)
        if driver_path and _os.path.exists(driver_path):
            _chrome_kwargs['driver_executable_path'] = driver_path
            self.logger.info(f'[Browser] 使用本地预置 chromedriver: {driver_path}')
        self.driver = uc.Chrome(**_chrome_kwargs)
        self.logger.info('[Browser] Chrome已启动')
        self.last_request_time = time.time()
        self._load_cookies()        # 复用上次 CF 通过的 cookie，避免重新挑战/重开浏览器
        self._register_atexit()     # 异常退出也回收浏览器，杜绝孤儿进程
        return self.driver

    def fetch_page(self, url, wait_for_cf=True, cf_timeout=40):
        """获取页面HTML，自动处理Cloudflare挑战"""
        if self.driver is None:
            self.start()

        # 速率限制
        self._rate_limit()

        self.logger.debug(f'Fetching: {url}')

        # 非阻塞导航 + Cloudflare等待
        page = self._navigate_and_wait(url, cf_timeout=cf_timeout)
        if page is not None:
            return page

        # 第一次失败，等待后重试一次
        self.logger.warning(f'页面加载失败，10秒后重试: {url}')
        time.sleep(10)
        page = self._navigate_and_wait(url, cf_timeout=cf_timeout)
        if page is not None:
            return page

        self.logger.error(f'重试仍失败: {url}')
        return None

    def fetch_soup(self, url, **kwargs):
        """获取页面并返回BeautifulSoup对象"""
        html = self.fetch_page(url, **kwargs)
        if html is None:
            return None
        return BeautifulSoup(html, 'lxml')

    def _rate_limit(self):
        """执行速率限制"""
        now = time.time()
        elapsed = now - self.last_request_time
        wait = random.uniform(
            Config.REQUEST_INTERVAL_MIN, Config.REQUEST_INTERVAL_MAX)
        if elapsed < wait:
            sleep_time = wait - elapsed
            self.logger.debug(f'Rate limit: sleeping {sleep_time:.1f}s')
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def get_request_count(self):
        return self.request_count

    def quit(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None


# ============================================================
# 工具函数
# ============================================================

def to_float(v):
    if v is None or v == '' or v == '-':
        return None
    try:
        return float(v)
    except Exception:
        return None

def to_int(v):
    if v is None or v == '' or v == '-':
        return None
    try:
        return int(float(v))
    except Exception:
        return None

def extract_db_abbr_from_cell(cell):
    """从球队名称单元格 <a href="/teams/BRK/2025.html"> 中提取 BR 缩写并转数据库缩写。

    cell_map 仅保留 cell.get_text()，会丢失 <a> 标签里的 href。
    这里保留原始 cell 元素，直接从 href 解析球队缩写，避免对全名做 [:3] 切片。
    """
    if cell is None:
        return ''
    a_tag = cell.find('a', href=lambda x: x and '/teams/' in x)
    if a_tag is None:
        return ''
    m = re.search(r'/teams/([A-Z]{3})/', a_tag.get('href', ''))
    if not m:
        return ''
    return normalize_team_abbr(m.group(1))


def normalize_team_abbr(abbr):
    """BBRef缩写转数据库缩写"""
    return Config.BR_TO_DB_ABBR.get(abbr, abbr)

def db_to_br_abbr(abbr):
    """数据库缩写转BBRef缩写"""
    return Config.DB_TO_BR_ABBR.get(abbr, abbr)

def get_season_for_date(d):
    """根据日期获取NBA赛季年份（赛季结束年）"""
    if d.month >= 10:
        return d.year + 1
    return d.year

def normalize_split_type(split_id, split_value):
    """将BBRef的split_id/split_value标准化为数据库split_type"""
    sv = split_value.lower().strip()

    # 直接映射
    direct_map = {
        'total': 'total',
        'home': 'home',
        'road': 'away',
        'pre': 'pre_all_star',
        'post': 'post_all_star',
        'wins': 'wins',
        'losses': 'losses',
    }
    if sv in direct_map:
        return direct_map[sv]

    # 月份
    months = ['october', 'november', 'december', 'january',
              'february', 'march', 'april', 'may', 'june']
    if sv in months:
        return sv

    # 星期
    days = ['monday', 'tuesday', 'wednesday', 'thursday',
            'friday', 'saturday', 'sunday']
    if sv in days:
        return sv

    # 其他：用下划线连接
    return sv.replace(' ', '_').replace('-', '_')


# ============================================================
# 表爬取规则定义
# ============================================================

TABLE_RULES = {
    # === 每日爬取（赛季中）===
    'games': {
        'frequency': 'daily',
        'url_pattern': '/leagues/NBA_{season}_games-{month}.html',
        'description': '比赛赛程和结果',
    },
    'team_game_splits': {
        'frequency': 'daily',
        'url_pattern': '/teams/{team}/{season}/splits/',
        'description': '球队比赛分项统计',
        'per_team': True,
    },
    'player_gamelog': {
        'frequency': 'daily',
        'url_pattern': '/players/{letter}/{player_id}/gamelog/{season}',
        'description': '球员比赛日志',
        'per_player': True,
    },
    'play_by_play': {
        'frequency': 'daily',
        'url_pattern': '/boxscores/pbp/{game_id}.html',
        'description': '逐回合数据',
        'per_game': True,
    },
    'transactions': {
        'frequency': 'daily',
        'url_pattern': '/friv/transactions.fcgi',
        'description': '交易记录',
    },

    # === 赛季级爬取 ===
    'player_per_game': {
        'frequency': 'seasonal',
        'url_pattern': '/leagues/NBA_{season}_per_game.html',
        'description': '球员场均统计',
        'table_id': 'per_game_stats',
    },
    'player_totals': {
        'frequency': 'seasonal',
        'url_pattern': '/leagues/NBA_{season}_totals.html',
        'description': '球员总计统计',
        'table_id': 'totals_stats',
    },
    'player_advanced': {
        'frequency': 'seasonal',
        'url_pattern': '/leagues/NBA_{season}_advanced.html',
        'description': '球员高阶数据',
        'table_id': 'advanced_stats',
    },
    'player_per_36_minutes': {
        'frequency': 'seasonal',
        'url_pattern': '/leagues/NBA_{season}_per_minute.html',
        'description': '球员每36分钟数据',
        'table_id': 'per_minute_stats',
    },
    'player_per_100_poss': {
        'frequency': 'seasonal',
        'url_pattern': '/leagues/NBA_{season}_per_poss.html',
        'description': '球员每100回合数据',
        'table_id': 'per_poss_stats',
    },
    'player_shooting': {
        'frequency': 'seasonal',
        'url_pattern': '/leagues/NBA_{season}_shooting.html',
        'description': '球员投篮分布',
        'table_id': 'shooting_stats',
    },
    'team_totals': {
        'frequency': 'seasonal',
        'url_pattern': '/leagues/NBA_{season}.html',
        'description': '球队总计',
    },
    'player_season_splits': {
        'frequency': 'seasonal',
        'url_pattern': '/players/{letter}/{player_id}/splits/{season}',
        'description': '球员赛季分项',
        'per_player': True,
    },
    'end_of_season_teams': {
        'frequency': 'seasonal',
        'url_pattern': '/awards/awards_{season}.html',
        'description': '最佳阵容',
    },
    'player_award_shares': {
        'frequency': 'seasonal',
        'url_pattern': '/awards/awards_{season}.html',
        'description': '奖项投票',
    },

    # === 静态数据 ===
    'player_bio': {
        'frequency': 'static',
        'url_pattern': '/players/{letter}/{player_id}.html',
        'description': '球员基本信息',
        'per_player': True,
    },
    'coach_bio': {
        'frequency': 'static',
        'url_pattern': '/coaches/{letter}/{coach_id}.html',
        'description': '教练信息',
    },
    'draft_picks': {
        'frequency': 'static',
        'url_pattern': '/draft/NBA_{season}.html',
        'description': '选秀数据',
    },
    'all_star_selections': {
        'frequency': 'seasonal',
        'url_pattern': '/allstar/{season}.html',
        'description': '全明星阵容',
    },
}


# ============================================================
# 爬取器实现
# ============================================================

class TableCrawler:
    """通用表爬取器"""

    def __init__(self, browser, logger, db_conn):
        self.browser = browser
        self.logger = logger
        self.conn = db_conn

    # ---- team_game_splits ----

    def crawl_team_game_splits(self, season, teams=None):
        """爬取球队比赛分项统计"""
        self.logger.info(f'=== 爬取 team_game_splits (赛季 {season}) ===')
        total_imported = 0
        total_skipped = 0
        total_updated = 0
        errors = []

        cur = self.conn.cursor()

        # 获取要爬取的球队列表
        if teams is None:
            cur.execute(
                "SELECT DISTINCT team_code FROM team_mapping "
                "WHERE is_active = true ORDER BY team_code")
            teams = [r[0] for r in cur.fetchall()]

        self.logger.info(f'  共 {len(teams)} 支球队需要爬取')

        for idx, team_abbr in enumerate(teams):
            br_abbr = db_to_br_abbr(team_abbr)
            url = f'{Config.BASE_URL}/teams/{br_abbr}/{season}/splits/'

            self.logger.info(
                f'  [{idx+1}/{len(teams)}] {team_abbr} (BR:{br_abbr})')

            soup = self.browser.fetch_soup(url)
            if soup is None:
                self.logger.warning(f'    跳过 {team_abbr}: 无法获取页面')
                errors.append(f'{team_abbr}: fetch failed')
                continue

            table = soup.find('table', id='team_splits')
            if not table:
                self.logger.warning(f'    跳过 {team_abbr}: 未找到splits表格')
                errors.append(f'{team_abbr}: no splits table')
                continue

            tbody = table.find('tbody')
            if not tbody:
                errors.append(f'{team_abbr}: no tbody')
                continue

            imported = 0
            skipped = 0
            updated = 0
            current_split_id = ''

            for tr in tbody.find_all('tr'):
                cells = tr.find_all(['td', 'th'])
                if len(cells) < 5:
                    continue

                # 构建 data-stat -> value 映射
                cell_map = {}
                for cell in cells:
                    stat = cell.get('data-stat', '')
                    if stat:
                        cell_map[stat] = cell.get_text(strip=True)

                split_value = cell_map.get('split_value', '')

                # 跳过表头行
                if split_value == 'Value' or split_value == '':
                    # 但要更新 current_split_id
                    sid = cell_map.get('split_id', '')
                    if sid and sid != 'Split':
                        current_split_id = sid
                    continue

                # 更新 current_split_id（每组的第一个数据行）
                sid = cell_map.get('split_id', '')
                if sid and sid != 'Split':
                    current_split_id = sid

                # 跳过 Total 行（可选保留）
                if split_value == 'Total':
                    split_type = 'total'
                else:
                    split_type = normalize_split_type(
                        current_split_id, split_value)

                if not split_type:
                    continue

                # 提取数据
                games = to_int(cell_map.get('g'))
                pts = to_float(cell_map.get('pts'))
                fg_pct = to_float(cell_map.get('fg_pct'))
                fg3_pct = to_float(cell_map.get('fg3_pct'))
                ft_pct = to_float(cell_map.get('ft_pct'))
                reb = to_int(cell_map.get('trb'))
                ast = to_int(cell_map.get('ast'))
                stl = to_int(cell_map.get('stl'))
                blk = to_int(cell_map.get('blk'))
                tov = to_int(cell_map.get('tov'))
                pf = to_int(cell_map.get('pf'))
                # plus_minus = pts - opp_pts
                opp_pts = to_float(cell_map.get('opp_pts'))
                plus_minus = None
                if pts is not None and opp_pts is not None:
                    plus_minus = round(pts - opp_pts, 1)

                # 检查是否已存在
                cur.execute(
                    "SELECT 1 FROM team_game_splits "
                    "WHERE season = %s AND team_abbr = %s "
                    "AND split_type = %s",
                    (season, team_abbr, split_type)
                )
                if cur.fetchone():
                    # 更新已有记录
                    try:
                        cur.execute("""
                            UPDATE team_game_splits
                            SET games=%s, pts=%s, fg_pct=%s, fg3_pct=%s,
                                ft_pct=%s, reb=%s, ast=%s, stl=%s, blk=%s,
                                tov=%s, pf=%s, plus_minus=%s
                            WHERE season=%s AND team_abbr=%s AND split_type=%s
                        """, (games, pts, fg_pct, fg3_pct, ft_pct, reb,
                              ast, stl, blk, tov, pf, plus_minus,
                              season, team_abbr, split_type))
                        updated += 1
                    except Exception as e:
                        errors.append(
                            f'{team_abbr} {split_type}: {str(e)[:60]}')
                        self.conn.rollback()
                    continue

                # 插入新记录
                try:
                    cur.execute("""
                        INSERT INTO team_game_splits
                        (season, team_abbr, split_type, games, pts,
                         fg_pct, fg3_pct, ft_pct, reb, ast, stl, blk,
                         tov, pf, plus_minus)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s)
                    """, (season, team_abbr, split_type, games, pts,
                          fg_pct, fg3_pct, ft_pct, reb, ast, stl, blk,
                          tov, pf, plus_minus))
                    imported += 1
                except Exception as e:
                    errors.append(f'{team_abbr} {split_type}: {str(e)[:60]}')
                    self.conn.rollback()

            self.conn.commit()
            total_imported += imported
            total_skipped += skipped
            total_updated += updated
            self.logger.info(
                f'    {team_abbr}: imported={imported}, '
                f'updated={updated}, skipped={skipped}')

        cur.close()
        self.logger.info(
            f'=== team_game_splits 完成: '
            f'imported={total_imported}, updated={total_updated}, '
            f'errors={len(errors)} ===')
        if errors:
            for e in errors[:5]:
                self.logger.error(f'  ERROR: {e}')

        return total_imported + total_updated, total_skipped, errors

    # ---- daily games ----

    def crawl_daily_games(self, target_date, whole_month=False):
        """爬取指定日期的比赛结果。

        Args:
            target_date: 目标日期。
            whole_month: 为 True 时处理该月 schedule 页上的所有比赛
                （用于回填），不再按 target_date 单日过滤。
        """
        season = get_season_for_date(target_date)
        month_name = target_date.strftime('%B').lower()

        # NBA Cup 总决赛精确元组集：(game_date, away_abbr, home_abbr)
        # 季中赛只有「总决赛」是额外多打、不计入常规赛战绩（半决赛在拉斯维加斯也计入）。
        # BR 的 Notes 文案对小组赛/淘汰赛不区分，故用精确对阵判定；未来新季追加 1 个元组即可。
        NBA_CUP_FINALS = {
            ('2023-12-09', 'IND', 'LAL'),  # 2023-24 决赛 @ T-Mobile Arena
            ('2024-12-17', 'MIL', 'OKC'),  # 2024-25 决赛 @ T-Mobile Arena
            ('2025-12-16', 'SAS', 'NYK'),  # 2025-26 决赛 @ T-Mobile Arena (SAS@NYK, NYK 胜)
        }
        url = (f'{Config.BASE_URL}/leagues/'
               f'NBA_{season}_games-{month_name}.html')

        self.logger.info(f'=== 爬取 games (日期 {target_date}) ===')

        soup = self.browser.fetch_soup(url)
        if soup is None:
            return 0, 0, ['fetch failed']

        table = soup.find('table', id='schedule')
        if not table:
            return 0, 0, ['schedule table not found']

        imported = 0
        skipped = 0
        errors = []
        target_date_str = target_date.strftime('%Y-%m-%d')

        cur = self.conn.cursor()
        tbody = table.find('tbody')
        if not tbody:
            return 0, 0, ['no tbody']

        for tr in tbody.find_all('tr'):
            if tr.get('class') and 'over_header' in tr.get('class', []):
                continue

            cell_map = {}
            visitor_cell = None
            home_cell = None
            for cell in tr.find_all(['td', 'th']):
                stat = cell.get('data-stat', '')
                if stat:
                    cell_map[stat] = cell.get_text(strip=True)
                    if stat == 'visitor_team_name':
                        visitor_cell = cell
                    elif stat == 'home_team_name':
                        home_cell = cell

            game_date_str = cell_map.get('date_game', '')
            if not game_date_str:
                continue

            # 尝试多种日期格式
            game_date = None
            for fmt in ['%a, %b %d, %Y', '%Y-%m-%d']:
                try:
                    game_date = datetime.strptime(
                        game_date_str, fmt).strftime('%Y-%m-%d')
                    break
                except ValueError:
                    continue

            if game_date is None:
                continue
            if not whole_month and game_date != target_date_str:
                continue

            # 获取boxscore链接（严格匹配 BR 字母数字 id，过滤导航页 index.fcgi 等脏链接）
            boxscore_link = tr.find(
                'a', href=lambda x: x and re.search(
                    r'/boxscores/\d{8,}[A-Z]{3}\.html$', x))
            boxscore_url = ''
            game_id = ''
            if boxscore_link:
                boxscore_url = boxscore_link['href']
                game_id = boxscore_url.split('/')[-1].replace('.html', '')

            if not game_id:
                continue

            # 从球队名称单元格的 href 解析 DB 缩写（不依赖全名切片，避免 Orlando->Orl 不匹配）
            away_team_abbr = extract_db_abbr_from_cell(visitor_cell)
            away_pts = to_int(cell_map.get('visitor_pts'))
            home_team_abbr = extract_db_abbr_from_cell(home_cell)
            home_pts = to_int(cell_map.get('home_pts'))

            # --- NBA Cup 总决赛识别 ---
            remarks = cell_map.get('game_remarks', '')
            if (game_date, away_team_abbr, home_team_abbr) in NBA_CUP_FINALS:
                season_type = 'NBA Cup'
            else:
                season_type = 'Regular Season'
                if 'In-Season Tournament' in remarks or 'NBA Cup' in remarks:
                    self.logger.warning(
                        f'{game_id}: 检测到 NBA Cup 标记({remarks!r}) 但未匹配已知总决赛元组，'
                        f'仍按 Regular Season 处理（如需标 NBA Cup 请在 NBA_CUP_FINALS 补充）。')

            # 幂等 UPSERT：按 (game_date, home_team_abbr, away_team_abbr) 匹配，
            # 已存在则补全 BR id / url（绝不插重复行），不存在则 INSERT。
            # game_id 统一用 BR 字母数字 id（= boxscore_url 末段去 .html）；
            # nba_api_id 暂不写入（爬虫只负责 BR 侧，数字 id 由 nba_api 回填）。
            cur.execute(
                "SELECT game_id, nba_api_id FROM games "
                "WHERE game_date = %s AND home_team_abbr = %s "
                "AND away_team_abbr = %s",
                (game_date, home_team_abbr, away_team_abbr))
            row = cur.fetchone()
            if row:
                # 已存在 -> 补全 BR id / url，保留 nba_api_id 与比分，不重复插入
                try:
                    cur.execute(
                        "UPDATE games SET game_id = %s, boxscore_url = %s, "
                        "br_crawled_id = %s, season_type = %s "
                        "WHERE game_date = %s AND home_team_abbr = %s "
                        "AND away_team_abbr = %s",
                        (game_id, boxscore_url, game_id, season_type, game_date,
                         home_team_abbr, away_team_abbr))
                    skipped += 1
                except Exception as e:
                    errors.append(f'{game_id}: {str(e)[:60]}')
                    self.conn.rollback()
            else:
                # 新比赛 -> INSERT，game_id = BR，nba_api_id 暂 NULL
                try:
                    cur.execute(
                        "INSERT INTO games "
                        "(game_id, game_date, season, season_type, "
                        "away_team_abbr, home_team_abbr, away_pts, home_pts, "
                        "boxscore_url, br_crawled_id, source) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, "
                        "%s, %s, 'BBRef') "
                        "ON CONFLICT DO NOTHING",
                        (game_id, game_date, season, season_type, away_team_abbr,
                         home_team_abbr, away_pts, home_pts,
                         boxscore_url, game_id))
                    imported += 1
                except Exception as e:
                    errors.append(f'{game_id}: {str(e)[:60]}')
                    self.conn.rollback()

        self.conn.commit()
        cur.close()
        self.logger.info(
            f'=== games 完成: imported={imported}, skipped={skipped} ===')
        return imported, skipped, errors

    # ---- season player stats ----

    def crawl_season_player_stats(self, season, stat_type):
        """爬取赛季级球员统计（通用框架）"""
        url_map = {
            'player_per_game': f'/leagues/NBA_{season}_per_game.html',
            'player_totals': f'/leagues/NBA_{season}_totals.html',
            'player_advanced': f'/leagues/NBA_{season}_advanced.html',
            'player_per_36_minutes': f'/leagues/NBA_{season}_per_minute.html',
            'player_per_100_poss': f'/leagues/NBA_{season}_per_poss.html',
            'player_shooting': f'/leagues/NBA_{season}_shooting.html',
        }
        table_id_map = {
            'player_per_game': 'per_game_stats',
            'player_totals': 'totals_stats',
            'player_advanced': 'advanced_stats',
            'player_per_36_minutes': 'per_minute_stats',
            'player_per_100_poss': 'per_poss_stats',
            'player_shooting': 'shooting_stats',
        }

        if stat_type not in url_map:
            return 0, 0, [f'unknown stat_type: {stat_type}']

        url = f'{Config.BASE_URL}{url_map[stat_type]}'
        self.logger.info(f'=== 爬取 {stat_type} (赛季 {season}) ===')

        soup = self.browser.fetch_soup(url)
        if soup is None:
            return 0, 0, ['fetch failed']

        table = soup.find('table', id=table_id_map[stat_type])
        if not table:
            return 0, 0, [f'table {table_id_map[stat_type]} not found']

        tbody = table.find('tbody')
        if not tbody:
            return 0, 0, ['no tbody']

        # 统计行数
        data_rows = [r for r in tbody.find_all('tr')
                     if not r.get('class')
                     or 'over_header' not in r.get('class', [])]
        row_count = len(data_rows)
        self.logger.info(f'  找到 {row_count} 行数据')

        # 检查数据库中已有多少
        cur = self.conn.cursor()
        db_table = stat_type.replace('player_', 'player_')
        try:
            cur.execute(
                f"SELECT count(*) FROM {db_table} WHERE season = %s",
                (season,))
            existing = cur.fetchone()[0]
        except Exception:
            existing = 0
        cur.close()

        if existing > 0:
            self.logger.info(
                f'  数据库已有 {existing} 条，跳过（使用专用导入器更新）')
            return existing, 0, []

        self.logger.info(
            f'  数据库无数据，需使用专用导入器导入 {row_count} 行')
        self.logger.info(
            f'  提示: 请使用 combine_server.py + 浏览器方式导入完整数据')
        return row_count, 0, []

    # ---- team totals ----

    def crawl_team_totals(self, season):
        """爬取球队赛季总计（检查模式）"""
        url = f'{Config.BASE_URL}/leagues/NBA_{season}.html'
        self.logger.info(f'=== 检查 team_totals (赛季 {season}) ===')

        soup = self.browser.fetch_soup(url)
        if soup is None:
            return 0, 0, ['fetch failed']

        imported = 0
        for table_id in ['totals_team', 'per_game_team']:
            table = soup.find('table', id=table_id)
            if not table:
                continue
            tbody = table.find('tbody')
            if not tbody:
                continue
            rows = [r for r in tbody.find_all('tr')
                    if not r.get('class')
                    or 'over_header' not in r.get('class', [])]
            imported += len(rows)

        self.logger.info(f'=== team_totals: {imported} teams found ===')
        return imported, 0, []


# ============================================================
# 爬取编排器
# ============================================================

class CrawlOrchestrator:
    """爬取编排器 - 根据日期和日志决定爬取什么"""

    def __init__(self):
        self.logger = CrawlLogger()

        # 确保数据库运行
        if not DatabaseManager.ensure_database_running():
            self.logger.error('无法启动数据库，退出')
            sys.exit(1)

        self.conn = DatabaseManager.get_connection()
        self.browser = BrowserManager(self.logger)
        self.table_crawler = TableCrawler(
            self.browser, self.logger, self.conn)

    def is_in_season(self, d=None):
        if d is None:
            d = date.today()
        return d.month >= 10 or d.month <= 6

    def run_daily(self, target_date=None):
        """执行每日爬取"""
        if target_date is None:
            target_date = date.today()

        self.logger.info('=' * 50)
        self.logger.info(f'NBA Daily Crawler - 运行日期: {target_date}')
        self.logger.info('=' * 50)

        season = get_season_for_date(target_date)
        self.logger.info(f'当前赛季: {season}')

        if not self.is_in_season(target_date):
            self.logger.info(
                '当前不在NBA赛季中（7-9月休赛期），执行季节性检查')
            self._run_offseason_checks(season)
            self.browser.quit()
            return

        # 检查是否需要回填
        missing_dates = self.logger.get_missing_dates('games', target_date)
        if missing_dates:
            self.logger.info(
                f'检测到 {len(missing_dates)} 天缺失数据，开始回填...')
            for d in missing_dates:
                self.logger.info(f'  回填日期: {d}')
                self._crawl_daily_for_date(d)

        # 爬取今天的数据
        self._crawl_daily_for_date(target_date)

        self.logger.info('=' * 50)
        self.logger.info(
            f'爬取完成 - 总请求数: {self.browser.get_request_count()}')
        self.logger.info('=' * 50)
        self.browser.quit()

    def _crawl_daily_for_date(self, target_date):
        """爬取指定日期的所有日频数据"""
        # 1. 比赛结果
        imp, skip, errs = self.table_crawler.crawl_daily_games(target_date)
        self.logger.record_success('games', target_date, imp, len(errs))

        # 2. 球队分项统计（每天更新当赛季所有球队）
        season = get_season_for_date(target_date)
        imp2, skip2, errs2 = (
            self.table_crawler.crawl_team_game_splits(season))
        self.logger.record_success(
            'team_game_splits', target_date, imp2, len(errs2))

        self.logger.info(f'  日期 {target_date} 爬取完成')

    def _run_offseason_checks(self, season):
        """休赛期检查"""
        self.logger.info('执行休赛期检查...')
        self.browser.start()

        # 检查上赛季数据是否完整
        checks = [
            ('player_per_game', 'player_per_game'),
            ('player_totals', 'player_totals'),
            ('player_advanced', 'player_advanced'),
        ]

        for db_table, stat_type in checks:
            cur = self.conn.cursor()
            try:
                cur.execute(
                    f"SELECT count(*) FROM {db_table} WHERE season = %s",
                    (season,))
                count = cur.fetchone()[0]
            except Exception:
                count = 0
            cur.close()

            if count == 0:
                self.logger.info(
                    f'  {db_table} 缺失赛季 {season} 数据，开始爬取...')
                self.table_crawler.crawl_season_player_stats(
                    season, stat_type)
            else:
                self.logger.info(
                    f'  {db_table} 已有 {count} 条赛季 {season} 数据')

        # 休赛期也更新team_game_splits
        self.logger.info('  更新 team_game_splits...')
        imp, skip, errs = self.table_crawler.crawl_team_game_splits(season)
        self.logger.record_success(
            'team_game_splits', date.today(), imp, len(errs))

    def run_backfill(self, days):
        """回填最近N天的数据"""
        self.logger.info(f'=== 回填模式: 最近 {days} 天 ===')
        today = date.today()
        for i in range(days, 0, -1):
            d = today - timedelta(days=i)
            if self.is_in_season(d):
                self.logger.info(f'回填 {d}')
                self._crawl_daily_for_date(d)

        self.logger.info(
            f'回填完成 - 总请求数: {self.browser.get_request_count()}')
        self.browser.quit()

    def run_full_season(self, season):
        """爬取整个赛季的所有数据"""
        self.logger.info(f'=== 全赛季模式: {season} ===')
        self.browser.start()

        # 1. 赛季级球员统计
        stat_types = [
            'player_per_game', 'player_totals', 'player_advanced',
            'player_per_36_minutes', 'player_per_100_poss',
            'player_shooting'
        ]
        for st in stat_types:
            imp, skip, errs = (
                self.table_crawler.crawl_season_player_stats(season, st))
            self.logger.record_success(st, date.today(), imp, len(errs))

        # 2. 球队分项
        imp, skip, errs = (
            self.table_crawler.crawl_team_game_splits(season))
        self.logger.record_success(
            'team_game_splits', date.today(), imp, len(errs))

        # 3. 球队总计
        imp, skip, errs = self.table_crawler.crawl_team_totals(season)
        self.logger.record_success(
            'team_totals', date.today(), imp, len(errs))

        self.logger.info(
            f'全赛季爬取完成 - 总请求数: '
            f'{self.browser.get_request_count()}')
        self.browser.quit()

    def run_single_table(self, table_name, target_date=None,
                         season=None, teams=None):
        """只爬取指定表"""
        self.logger.info(f'=== 单表模式: {table_name} ===')
        self.browser.start()

        if table_name == 'team_game_splits':
            if season is None:
                season = get_season_for_date(target_date or date.today())
            imp, skip, errs = self.table_crawler.crawl_team_game_splits(
                season, teams)
            self.logger.record_success(
                table_name, target_date or date.today(), imp, len(errs))
        elif table_name == 'games':
            imp, skip, errs = self.table_crawler.crawl_daily_games(
                target_date or date.today())
            self.logger.record_success(
                table_name, target_date or date.today(), imp, len(errs))
        elif table_name in TABLE_RULES:
            rule = TABLE_RULES[table_name]
            self.logger.info(f'  规则: {rule}')
            if rule['frequency'] == 'seasonal':
                if season is None:
                    season = get_season_for_date(
                        target_date or date.today())
                if 'per_player' in rule:
                    self.logger.info(
                        f'  需要逐球员爬取，使用 --full-season 模式')
                else:
                    self.table_crawler.crawl_season_player_stats(
                        season, table_name)
            else:
                self.logger.info(f'  使用 --date 参数指定日期')
        else:
            self.logger.error(f'未知表名: {table_name}')
            self.logger.info(
                f'可用表: {", ".join(TABLE_RULES.keys())}')

        self.logger.info(
            f'单表爬取完成 - 总请求数: '
            f'{self.browser.get_request_count()}')
        self.browser.quit()

    def run_check(self):
        """只检查状态不爬取"""
        self.logger.info('=== 状态检查 ===')

        status = self.logger.load_status()
        self.logger.info(
            f'最后爬取日期: {status.get("last_crawl_date", "从未")}')
        self.logger.info(
            f'最后全赛季: {status.get("last_full_season", "从未")}')

        self.logger.info('\n各表状态:')
        for table_name, info in sorted(
                status.get('tables', {}).items()):
            self.logger.info(
                f'  {table_name:30s}: '
                f'last={info.get("last_date","?")}, '
                f'records={info.get("records",0)}, '
                f'errors={info.get("errors",0)}')

        # 检查缺失日期
        missing = self.logger.get_missing_dates('games')
        if missing:
            self.logger.info(f'\n需要回填的日期 ({len(missing)} 天):')
            for d in missing[:10]:
                self.logger.info(f'  {d}')
            if len(missing) > 10:
                self.logger.info(f'  ... 还有 {len(missing) - 10} 天')
        else:
            self.logger.info('\n数据是最新的，无需回填')

        # 数据库统计
        cur = self.conn.cursor()
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' ORDER BY table_name
        """)
        tables = [r[0] for r in cur.fetchall()]

        self.logger.info(f'\n数据库统计 ({len(tables)} 个表):')
        total_records = 0
        for t in tables:
            try:
                cur.execute(f"SELECT count(*) FROM {t}")
                cnt = cur.fetchone()[0]
                total_records += cnt
                if cnt > 0:
                    self.logger.info(f'  {t:35s}: {cnt:>12,}')
            except Exception:
                pass
        self.logger.info(f'  {"TOTAL":35s}: {total_records:>12,}')
        cur.close()

    def close(self):
        self.browser.quit()
        self.conn.close()


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='NBA Daily Crawler - Standalone Edition')
    parser.add_argument('--date', type=str, default=None,
                        help='指定爬取日期 (YYYY-MM-DD)')
    parser.add_argument('--backfill', type=int, default=None,
                        help='回填最近N天的数据')
    parser.add_argument('--table', type=str, default=None,
                        help='只爬取指定表')
    parser.add_argument('--full-season', type=int, default=None,
                        help='爬取整个赛季 (年份)')
    parser.add_argument('--season', type=int, default=None,
                        help='指定赛季年份（用于 --table 模式）')
    parser.add_argument('--check', action='store_true',
                        help='只检查状态不爬取')
    parser.add_argument('--list-tables', action='store_true',
                        help='列出所有支持的表')
    parser.add_argument('--teams', type=str, default=None,
                        help='指定球队（逗号分隔，如 BOS,LAL）')
    parser.add_argument('--month-backfill', type=str, default=None,
                        help='回填整月比赛 gameid（BR）：YYYY-MM，处理该月全部比赛')

    args = parser.parse_args()

    # 列出所有表
    if args.list_tables:
        print('支持的表:')
        for name, rule in sorted(TABLE_RULES.items()):
            print(f'  {name:30s} [{rule["frequency"]:8s}] '
                  f'{rule["description"]}')
        return

    orchestrator = CrawlOrchestrator()

    try:
        if args.check:
            orchestrator.run_check()
        elif args.full_season:
            orchestrator.run_full_season(args.full_season)
        elif args.backfill:
            orchestrator.run_backfill(args.backfill)
        elif args.table:
            target_date = None
            if args.date:
                target_date = datetime.strptime(
                    args.date, '%Y-%m-%d').date()
            teams = None
            if args.teams:
                teams = [t.strip() for t in args.teams.split(',')]
            orchestrator.run_single_table(
                args.table, target_date, args.season, teams)
        elif args.month_backfill:
            y, m = map(int, args.month_backfill.split('-'))
            target = date(y, m, 1)
            orchestrator.browser.start()
            imp, skip, errs = orchestrator.table_crawler.crawl_daily_games(
                target, whole_month=True)
            orchestrator.logger.record_success('games', target, imp, len(errs))
            orchestrator.logger.info(
                f'整月回填 {args.month_backfill}: '
                f'imported={imp}, updated(skipped)={skip}, errors={len(errs)}')
            if errs:
                for e in errs[:5]:
                    orchestrator.logger.error(f'  ERROR: {e}')
            orchestrator.browser.quit()
        else:
            target_date = None
            if args.date:
                target_date = datetime.strptime(
                    args.date, '%Y-%m-%d').date()
            orchestrator.run_daily(target_date)
    except KeyboardInterrupt:
        print('\n用户中断')
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f'错误: {e}')
    finally:
        orchestrator.close()


if __name__ == '__main__':
    main()
