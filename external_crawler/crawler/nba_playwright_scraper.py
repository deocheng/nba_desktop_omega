#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚠️ DEPRECATED — 请使用 nba_data_scraper.py ⚠️
=============================================

stats.nba.com API 已被 Akamai 锁死（2026-06-18 验证）:
  - channel='chrome' + evaluate(fetch) → CORS 跨域拦截
  - route.fetch() → Akamai TLS 检测返回 HTML
  - curl_cffi (chrome120/chrome124/safari/firefox) → 全部被拦截
  - page.goto() 直接导航 API URL → Akamai HTML 挑战页

替代方案: crawler/nba_data_scraper.py
  使用 data.nba.com 移动 API + curl_cffi TLS 模拟
  已验证可用端点: standings / scoreboard / game_detail

此文件保留作为反爬技术研究参考。
"""
from __future__ import annotations
"""
NBA 官方数据 Playwright 爬虫 (已弃用)
============================

基于 Playwright 真实浏览器模拟，安全爬取 NBA 官方 stats.nba.com API。
集成完善的 anti-bot 反检测机制，所有请求经由浏览器原生 fetch() 发起，
自动携带正确的 TLS 指纹、Header 和 Cookie。

技术架构:
    - Playwright Stealth Mode: 隐藏自动化标记，模拟真实 Chrome 浏览器
    - page.evaluate(fetch): 通过浏览器原生 JS 发起 API 请求，完美绕过反爬
    - SmartScheduler: 智能限速调度（高峰/低峰自适应延迟）
    - CookieManager: 会话持久化，跨重启复用 Cookie
    - 指数退避重试: 遇到 429/403 自动等待重试

参考项目:
    - https://github.com/swar/nba_api (NBA API 端点发现)
    - 本项目 ultimate_playwright_scraper.py (Playwright 反爬技巧)
    - 本项目 base_scraper.py (调度器/限流器)

Author: Senior Developer (高级开发工程师)
Created: 2026-06-17
"""

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import json
import time
import random
import logging
import os
from pathlib import Path
from datetime import datetime, time as dt_time
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field

# 可选依赖
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import psycopg2
    from psycopg2.extras import execute_values
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

# ─── 日志配置 ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('NBAPlaywright')


# ═══════════════════════════════════════════════════════════════
# 配置数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class NBAPlaywrightConfig:
    """NBA Playwright 爬虫全局配置"""

    # ── 目标 URL ──
    NBA_HOMEPAGE: str = "https://www.nba.com"
    STATS_API_BASE: str = "https://stats.nba.com/stats"

    # ── API 端点名 ──
    ENDPOINTS: Dict[str, str] = field(default_factory=lambda: {
        # 记分板 / 赛程
        "scoreboard": "scoreboardv3",
        # BoxScore 系列
        "boxscore_traditional": "boxscoretraditionalv3",
        "boxscore_advanced": "boxscoreadvancedv3",
        "boxscore_fourfactors": "boxscorefourfactorsv3",
        "boxscore_misc": "boxscoremiscv3",
        "boxscore_scoring": "boxscorescoringv3",
        "boxscore_usage": "boxscoreusagev3",
        "boxscore_defensive": "boxscoredefensivev2",
        "boxscore_matchups": "boxscorematchupsv3",
        "boxscore_summary": "boxscoresummaryv3",
        # 逐球数据
        "playbyplay": "playbyplayv3",
        # 排名
        "standings": "leaguestandingsv3",
        # 球队
        "team_stats": "leaguedashteamstats",
        "team_gamelog": "teamgamelog",
        "team_roster": "commonteamroster",
        "team_dashboard": "teamdashboardbygeneralsplits",
        "team_year_by_year": "teamyearbyyearstats",
        # 球员
        "player_stats": "leaguedashplayerstats",
        "player_gamelog": "playergamelog",
        "player_career": "playercareerstats",
        "player_index": "commonallplayers",
        "player_info": "commonplayerinfo",
        # 比赛查询
        "league_game_finder": "leaguegamefinder",
        # 选秀 / 荣誉
        "draft_history": "drafthistory",
        "all_star": "allstar",
    })

    # ── 反爬参数 ──
    # Playwright 默认使用 headless=new (Chromium 112+)，比旧 headless 更难检测
    BROWSER_ARGS: List[str] = field(default_factory=lambda: [
        '--disable-blink-features=AutomationControlled',
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--disable-infobars',
        '--window-size=1920,1080',
    ])

    # 是否使用 headless=new 模式 (Chromium 112+, 更难被检测)
    # 设置为 False 可以启用有头模式，彻底规避 headless 检测
    USE_HEADLESS_NEW: bool = True

    # 浏览器 Channel: 'chrome' 使用系统安装的真实 Chrome (推荐)
    # 真实 Chrome 的 TLS 指纹更难被 Akamai 检测
    # 设为 None 使用 Playwright 自带的 Chromium
    BROWSER_CHANNEL: Optional[str] = 'chrome'

    # ── User-Agent 池 ──
    USER_AGENTS: List[str] = field(default_factory=lambda: [
        # Chrome 130+ Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        # Chrome 130+ Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        # Edge Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
        # Firefox Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
        # Safari Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    ])

    # ── 限速参数 ──
    DAILY_LIMIT: int = 500
    HOURLY_LIMIT: int = 60
    MIN_DELAY: float = 0.5
    MAX_DELAY: float = 2.0
    PEAK_MIN_DELAY: float = 2.0
    PEAK_MAX_DELAY: float = 5.0
    MAX_RETRIES: int = 5
    REQUEST_TIMEOUT: int = 30000  # 30 秒 (ms)

    # ── 高峰时段 ──
    PEAK_HOURS: List[Tuple[dt_time, dt_time]] = field(default_factory=lambda: [
        (dt_time(9, 0), dt_time(12, 0)),
        (dt_time(14, 0), dt_time(17, 0)),
        (dt_time(19, 0), dt_time(22, 0)),
    ])

    # ── 持久化路径 ──
    COOKIE_FILE: str = "crawler/nba_pw_cookies.json"
    PROGRESS_FILE: str = "crawler/nba_pw_progress.json"

    # ── 数据库配置 ──
    DB_CONFIG: Dict[str, Any] = field(default_factory=lambda: {
        'dbname': 'nba',
        'user': 'postgres',
        'password': 'postgres',
        'host': 'localhost',
        'port': '5433',
    })


# ═══════════════════════════════════════════════════════════════
# Cookie 管理器
# ═══════════════════════════════════════════════════════════════

class CookieManager:
    """Playwright Cookie 持久化管理器"""

    def __init__(self, cookie_file: str = "crawler/nba_pw_cookies.json"):
        self.cookie_file = Path(cookie_file)
        self.cookies: List[Dict] = []
        self._load()

    def _load(self):
        if self.cookie_file.exists():
            try:
                with open(self.cookie_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.cookies = data.get('cookies', [])
                logger.info(f"🍪 加载 {len(self.cookies)} 个 Cookie")
            except Exception as e:
                logger.warning(f"加载 Cookie 失败: {e}")
                self.cookies = []

    def save(self, context):
        """保存当前 context 的 Cookie"""
        try:
            cookies = context.cookies()
            domain_count = len(set(c.get('domain', '') for c in cookies))
            with open(self.cookie_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'cookies': cookies,
                    'saved_at': datetime.now().isoformat(),
                    'domains': domain_count,
                }, f, ensure_ascii=False, indent=2)
            logger.info(f"🍪 保存 {len(cookies)} 个 Cookie ({domain_count} 个域名)")
        except Exception as e:
            logger.error(f"保存 Cookie 失败: {e}")

    def apply(self, context):
        """将 Cookie 应用到 Playwright context"""
        if self.cookies:
            try:
                context.add_cookies(self.cookies)
                logger.info(f"🍪 应用 {len(self.cookies)} 个 Cookie")
            except Exception as e:
                logger.warning(f"应用 Cookie 失败: {e}")


# ═══════════════════════════════════════════════════════════════
# 智能调度器
# ═══════════════════════════════════════════════════════════════

class SmartScheduler:
    """智能限速调度器 - 控制爬取节奏，避开高峰时段"""

    def __init__(self, config: NBAPlaywrightConfig):
        self.config = config
        self.request_count = {'daily': 0, 'hourly': 0}
        self.last_reset = datetime.now()
        self._load_progress()

    def _load_progress(self):
        pf = Path(self.config.PROGRESS_FILE)
        if pf.exists():
            try:
                with open(pf, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.request_count = data.get('request_count', self.request_count)
                    last = data.get('last_reset')
                    if last:
                        self.last_reset = datetime.fromisoformat(last)
            except Exception:
                pass

    def _save_progress(self):
        try:
            with open(self.config.PROGRESS_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    'request_count': self.request_count,
                    'last_reset': self.last_reset.isoformat(),
                    'updated_at': datetime.now().isoformat(),
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _reset_if_needed(self):
        now = datetime.now()
        if now.hour != self.last_reset.hour:
            self.request_count['hourly'] = 0
        if now.day != self.last_reset.day:
            self.request_count['daily'] = 0
        self.last_reset = now

    def is_peak(self) -> bool:
        now = datetime.now().time()
        for start, end in self.config.PEAK_HOURS:
            if start <= now <= end:
                return True
        return False

    def can_proceed(self) -> bool:
        self._reset_if_needed()
        if self.request_count['daily'] >= self.config.DAILY_LIMIT:
            logger.warning(f"⛔ 达到每日限制 ({self.config.DAILY_LIMIT})")
            return False
        if self.request_count['hourly'] >= self.config.HOURLY_LIMIT:
            logger.warning(f"⛔ 达到每小时限制 ({self.config.HOURLY_LIMIT})")
            return False
        return True

    def wait(self):
        """根据时段执行智能延迟"""
        if self.is_peak():
            delay = random.uniform(self.config.PEAK_MIN_DELAY, self.config.PEAK_MAX_DELAY)
            logger.debug(f"⏳ 高峰延迟 {delay:.2f}s")
        else:
            delay = random.uniform(self.config.MIN_DELAY, self.config.MAX_DELAY)
            logger.debug(f"⏳ 低峰延迟 {delay:.2f}s")
        time.sleep(delay)

    def record(self):
        self.request_count['daily'] += 1
        self.request_count['hourly'] += 1
        self._save_progress()

    def status(self) -> Dict:
        self._reset_if_needed()
        return {
            'daily_used': self.request_count['daily'],
            'daily_limit': self.config.DAILY_LIMIT,
            'hourly_used': self.request_count['hourly'],
            'hourly_limit': self.config.HOURLY_LIMIT,
            'is_peak': self.is_peak(),
            'peak_label': '高峰' if self.is_peak() else '低峰',
        }


# ═══════════════════════════════════════════════════════════════
# NBA Playwright 爬虫主类
# ═══════════════════════════════════════════════════════════════

class NBAPlaywrightScraper:
    """
    NBA 官方数据 Playwright 爬虫

    核心设计：
    1. 启动 Playwright 真实浏览器（Stealth 模式）
    2. 访问 nba.com 建立合法会话
    3. 通过 page.evaluate() 调用浏览器原生 fetch() 请求 stats.nba.com API
    4. 浏览器自动携带正确的 TLS 指纹、Header、Cookie，完美绕过反爬

    Usage:
        scraper = NBAPlaywrightScraper(headless=True)
        scraper.start()

        # 获取今日比赛
        games = scraper.get_scoreboard("2026-06-17")

        # 获取比赛技术统计
        box = scraper.get_boxscore_traditional("0022500001")

        # 获取赛季排名
        standings = scraper.get_standings("2025-26")

        scraper.close()
    """

    # ── Akamai 级反检测 JS 脚本 (14 个检测向量) ──
    ANTI_DETECT_SCRIPT = r"""
    // ═══ Akamai-Grade Anti-Bot Detection Bypass ═══
    // 每个属性覆盖都模拟真实 Chrome 浏览器的行为

    (function() {
        'use strict';

        // 1. webdriver — 最关键的反检测
        Object.defineProperty(navigator, 'webdriver', {
            get: function() { return false; },
            configurable: true
        });

        // 2. plugins — 真实 Chrome 至少有 3-5 个插件
        const makePlugins = function() {
            const raw = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format', length: 1 },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '', length: 1 },
                { name: 'Native Client', filename: 'internal-nacl-plugin', description: '', length: 2 },
            ];
            const arr = raw.map(function(p) {
                const plugin = Object.create({
                    item: function(i) { return this[i] || null; },
                    namedItem: function(n) { return this.named[n] || null; },
                    refresh: function() {},
                });
                Object.assign(plugin, p);
                return plugin;
            });
            arr.item = function(i) { return this[i] || null; };
            arr.namedItem = function(n) { return null; };
            arr.refresh = function() {};
            Object.defineProperty(arr, 'length', { value: raw.length });
            return arr;
        };
        Object.defineProperty(navigator, 'plugins', {
            get: makePlugins,
            configurable: true
        });

        // 3. mimeTypes
        Object.defineProperty(navigator, 'mimeTypes', {
            get: function() {
                const types = [
                    { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
                    { type: 'text/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
                ];
                types.item = function(i) { return this[i] || null; };
                types.namedItem = function(n) { return null; };
                Object.defineProperty(types, 'length', { value: 2 });
                return types;
            },
            configurable: true
        });

        // 4. languages / language
        Object.defineProperty(navigator, 'languages', {
            get: function() { return ['en-US', 'en', 'zh-CN']; },
            configurable: true
        });
        Object.defineProperty(navigator, 'language', {
            get: function() { return 'en-US'; },
            configurable: true
        });

        // 5. platform (matching the UA)
        Object.defineProperty(navigator, 'platform', {
            get: function() { return 'Win32'; },
            configurable: true
        });

        // 6. hardwareConcurrency (主流 CPU 核心数)
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: function() { return 8; },
            configurable: true
        });

        // 7. deviceMemory (8GB 常见)
        Object.defineProperty(navigator, 'deviceMemory', {
            get: function() { return 8; },
            configurable: true
        });

        // 8. maxTouchPoints (桌面端 = 0)
        Object.defineProperty(navigator, 'maxTouchPoints', {
            get: function() { return 0; },
            configurable: true
        });

        // 9. Permissions.query — 避免 headless 模式下的异常行为
        const _origQuery = window.navigator.permissions.query.bind(window.navigator.permissions);
        window.navigator.permissions.query = function(parameters) {
            if (parameters && parameters.name === 'notifications') {
                return Promise.resolve({
                    state: 'prompt',
                    onchange: null
                });
            }
            return _origQuery(parameters);
        };

        // 10. chrome.runtime — 真实 Chrome 的核心对象
        if (!window.chrome) {
            window.chrome = {};
        }
        if (!window.chrome.runtime) {
            window.chrome.runtime = {
                id: undefined,
                OnInstalledReason: {
                    INSTALL: 'install',
                    UPDATE: 'update',
                    CHROME_UPDATE: 'chrome_update',
                    SHARED_MODULE_UPDATE: 'shared_module_update'
                },
                OnRestartRequiredReason: {
                    APP_UPDATE: 'app_update',
                    OS_UPDATE: 'os_update',
                    PERIODIC: 'periodic'
                },
                PlatformArch: {
                    ARM: 'arm',
                    ARM64: 'arm64',
                    MIPS: 'mips',
                    MIPS64: 'mips64',
                    X86_32: 'x86-32',
                    X86_64: 'x86-64'
                },
                PlatformOs: {
                    ANDROID: 'android',
                    CROS: 'cros',
                    LINUX: 'linux',
                    MAC: 'mac',
                    OPENBSD: 'openbsd',
                    WIN: 'win'
                },
                RequestUpdateCheckStatus: {
                    THROTTLED: 'throttled',
                    NO_UPDATE: 'no_update',
                    UPDATE_AVAILABLE: 'update_available'
                },
                getManifest: function() { return {}; },
                getURL: function(path) { return 'chrome-extension://' + (this.id || '') + '/' + path; },
                lastError: undefined,
                onConnect: { addListener: function() {}, removeListener: function() {} },
                onMessage: { addListener: function() {}, removeListener: function() {} },
                sendMessage: function() {},
                connect: function() { return { onMessage: { addListener: function() {} }, postMessage: function() {}, disconnect: function() {} }; },
            };
        }
        if (!window.chrome.loadTimes) {
            window.chrome.loadTimes = function() {
                return {
                    requestTime: Date.now() / 1000,
                    startLoadTime: Date.now() / 1000 - 0.5,
                    commitLoadTime: Date.now() / 1000 - 0.3,
                    finishDocumentLoadTime: Date.now() / 1000 - 0.1,
                    finishLoadTime: Date.now() / 1000,
                    firstPaintTime: Date.now() / 1000 - 0.2,
                    firstPaintAfterLoadTime: 0,
                    navigationType: 'Other',
                    wasFetchedViaSpdy: true,
                    wasNpnNegotiated: true,
                    npnNegotiatedProtocol: 'h2',
                    wasAlternateProtocolAvailable: false,
                    connectionInfo: 'h2',
                };
            };
        }
        if (!window.chrome.csi) {
            window.chrome.csi = function() {
                return { startE: Date.now(), onloadT: Date.now(), pageT: Math.random() * 2000, tran: 15 };
            };
        }
        if (!window.chrome.app) {
            window.chrome.app = {
                isInstalled: false,
                InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
                RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
                getDetails: function() { return null; },
                getIsInstalled: function() { return false; },
                runningState: function() { return 'cannot_run'; },
            };
        }

        // 11. WebGL 指纹一致性
        try {
            const getParam = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                // UNMASKED_VENDOR_WEBGL
                if (parameter === 37445) return 'Google Inc. (Intel)';
                // UNMASKED_RENDERER_WEBGL
                if (parameter === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)';
                return getParam.call(this, parameter);
            };
            if (typeof WebGL2RenderingContext !== 'undefined') {
                const getParam2 = WebGL2RenderingContext.prototype.getParameter;
                WebGL2RenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Google Inc. (Intel)';
                    if (parameter === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)';
                    return getParam2.call(this, parameter);
                };
            }
        } catch(e) {}

        // 12. 隐藏 headless 特有的属性
        delete navigator.__proto__.webdriver;

        // 13. Notification.permission
        if (typeof Notification !== 'undefined') {
            Object.defineProperty(Notification, 'permission', {
                get: function() { return 'default'; },
                configurable: true
            });
        }

        // 14. 覆盖 AutomationControlled (CDP detection)
        if (navigator.userAgent.includes('HeadlessChrome')) {
            Object.defineProperty(navigator, 'userAgent', {
                get: function() {
                    return 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';
                },
                configurable: true
            });
        }

    })();
    """

    def __init__(
        self,
        headless: bool = True,
        config: Optional[NBAPlaywrightConfig] = None,
        cookie_file: Optional[str] = None,
    ):
        """
        Args:
            headless: 是否无头模式运行（默认 True）
            config: 自定义配置（默认使用 NBAPlaywrightConfig）
            cookie_file: Cookie 文件路径
        """
        self.config = config or NBAPlaywrightConfig()
        self.headless = headless
        self.cookie_manager = CookieManager(cookie_file or self.config.COOKIE_FILE)
        self.scheduler = SmartScheduler(self.config)

        # Playwright 运行时对象
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

        # 会话状态
        self._session_page_domain = None  # 'stats.nba.com' | 'www.nba.com' | None

        # 统计
        self._stats = {
            'requests_made': 0,
            'requests_failed': 0,
            'bytes_downloaded': 0,
            'start_time': None,
        }

    # ── 浏览器生命周期 ──────────────────────────────────────────

    def start(self):
        """启动浏览器并建立 NBA.com 会话

        多阶段策略（按优先级）：
        1. 尝试直接访问 www.nba.com（含完整反检测）
        2. 若被 Akamai 拦截，用 page.route() 提供 Mock 页面，绕过 Akamai 的 JS
        3. 始终通过 stats.nba.com API 获取数据
        """
        logger.info("🚀 启动 Playwright 浏览器 (Stealth 模式)...")

        # 启动 Playwright
        self._playwright = sync_playwright().start()

        # 确定 headless 模式: Chromium 112+ 支持 'new' 模式
        # 'new' 模式的 headless 与有头模式共享同一渲染路径，更难被检测
        if self.headless and self.config.USE_HEADLESS_NEW:
            channel = None  # 使用内置 Chromium
            headless_mode = True
            logger.info("   使用 headless=new 模式 (Chromium 112+ 反检测增强)")
        else:
            headless_mode = self.headless

        # 启动浏览器
        launch_kwargs = {
            'headless': headless_mode,
            'args': self.config.BROWSER_ARGS,
        }
        if self.config.BROWSER_CHANNEL:
            launch_kwargs['channel'] = self.config.BROWSER_CHANNEL
            logger.info(f"   使用 Channel: {self.config.BROWSER_CHANNEL} (真实 Chrome)")

        self._browser = self._playwright.chromium.launch(**launch_kwargs)

        # 创建浏览器上下文
        ua = random.choice(self.config.USER_AGENTS)
        vp_width = random.choice([1366, 1440, 1536, 1920])
        vp_height = random.choice([768, 900, 1080])

        self._context = self._browser.new_context(
            user_agent=ua,
            viewport={'width': vp_width, 'height': vp_height},
            locale='en-US',
            timezone_id='America/New_York',
            color_scheme='light',
            device_scale_factor=1,
            is_mobile=False,
            has_touch=False,
            extra_http_headers={
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Sec-Ch-Ua': '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
            }
        )

        # 应用保存的 Cookie
        self.cookie_manager.apply(self._context)

        # 【关键】设置 page.route() 拦截 — 作为 Akamai 绕过后备方案
        self._setup_route_interception()

        # 创建页面并注入反检测脚本
        self._page = self._context.new_page()
        self._page.add_init_script(self.ANTI_DETECT_SCRIPT)

        # 建立 NBA.com 会话
        self._establish_session()

        # 安装 API 路由拦截（注入 Referer/Origin 等 NBA 要求的头）
        self._install_api_route_interception()

        self._stats['start_time'] = datetime.now()
        logger.info("✅ 浏览器已启动，会话已建立")
        logger.info(f"   UA: {ua[:80]}...")
        logger.info(f"   Viewport: {vp_width}x{vp_height}")
        logger.info(f"   调度状态: {self.scheduler.status()}")

    def _setup_route_interception(self):
        """
        设置路由拦截 — 双重用途:
        1. API 请求拦截: 自动添加 Referer/Origin 等 NBA API 必需的头
        2. Mock 页面: 作为 Akamai 绕过的后备方案
        """
        self._route_installed = False

    def _install_api_route_interception(self):
        """安装 API 请求拦截器，自动注入 NBA 要求的请求头"""
        if self._route_installed:
            return

        def handle_api_route(route):
            """拦截 stats.nba.com API 请求，注入必要头"""
            url = route.request.url
            if '/stats/' in url:
                headers = route.request.headers.copy()
                # NBA API 要求的关键头
                headers['Referer'] = 'https://www.nba.com/'
                headers['Origin'] = 'https://www.nba.com'
                # 如果请求头里没有这些自定义头，添加它们
                if 'x-nba-stats-origin' not in headers:
                    headers['x-nba-stats-origin'] = 'stats'
                if 'x-nba-stats-token' not in headers:
                    headers['x-nba-stats-token'] = 'true'
                route.continue_(headers=headers)
            else:
                route.continue_()

        # 安装路由拦截
        self._page.route('**/stats.nba.com/**', handle_api_route)
        self._route_installed = True
        logger.info("🔧 API 路由拦截已安装 (自动注入 Referer/Origin)")

    def _serve_mock_nba_page(self, target_domain: str = 'stats.nba.com', keep_route: bool = False):
        """
        用 Mock 页面绕过 Akamai 拦截 / 建立正确的页面上下文

        两种使用场景:
        1. Akamai 完全拦截 → target_domain='stats.nba.com' (同源 API 调用)
        2. 已通过 Akamai，需要 www.nba.com 上下文 → target_domain='www.nba.com'
           此时 evaluate(fetch) 的 Referer 自动为 https://www.nba.com/
           NBA API 接受 www.nba.com 的 Referer ✅

        Args:
            target_domain: Mock 页面域名 ('stats.nba.com' 或 'www.nba.com')
            keep_route: 是否保留路由（默认 False，导航后立即移除）
        """
        logger.info(f"🔄 Mock 页面 (origin: {target_domain})...")

        mock_url = f"https://{target_domain}/"

        def mock_page_handler(route):
            """提供 Mock 页面（模拟真实 NBA 页面结构）"""
            route.fulfill(
                status=200,
                content_type='text/html',
                headers={
                    'Content-Type': 'text/html; charset=utf-8',
                    'Cache-Control': 'no-cache',
                },
                body=f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NBA Stats | NBA.com</title>
    <meta name="referrer" content="origin">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5; color: #1d1d1d;
            min-height: 100vh;
        }}
        .nba-header {{
            background: #1d428a; color: white; padding: 16px 24px;
            display: flex; align-items: center; gap: 12px;
        }}
        .nba-logo {{
            width: 48px; height: 48px; background: white; border-radius: 8px;
            display: flex; align-items: center; justify-content: center;
            font-weight: bold; font-size: 20px; color: #1d428a;
        }}
        .container {{
            max-width: 1200px; margin: 0 auto; padding: 32px 24px;
        }}
    </style>
</head>
<body>
    <div class="nba-header">
        <div class="nba-logo">NBA</div>
        <div>
            <h1 style="font-size: 20px;">NBA Stats</h1>
            <p style="font-size: 12px; opacity: 0.7;">Official Data Portal</p>
        </div>
    </div>
    <div class="container">
        <div id="__next" data-reactroot="">
            <h2>Welcome to NBA Stats</h2>
            <p>API access ready via <code>https://stats.nba.com/stats/</code></p>
        </div>
    </div>
</body>
</html>"""
            )

        # 注册拦截器
        self._page.route(mock_url, mock_page_handler)
        if mock_url.endswith('/'):
            self._page.route(mock_url.rstrip('/'), mock_page_handler)

        try:
            self._page.goto(mock_url, wait_until='domcontentloaded', timeout=30000)
            time.sleep(random.uniform(0.5, 1.5))
        finally:
            if not keep_route:
                # 清除路由拦截
                try:
                    self._page.unroute(mock_url, handler=mock_page_handler)
                except:
                    pass
                try:
                    if mock_url.endswith('/'):
                        self._page.unroute(mock_url.rstrip('/'), handler=mock_page_handler)
                except:
                    pass

        logger.info(f"✅ Mock 页面已加载 (origin: {target_domain})")

    def _establish_session(self):
        """
        建立 NBA.com 会话 (多阶段策略)

        ═══ 核心问题 ═══
        NBA Stats API (stats.nba.com/stats/...) 要求请求携带正确的 Referer。
        真实 nba.com 网站从 www.nba.com 发起 API 调用 → Referer: https://www.nba.com/
        如果从 stats.nba.com 发起 → Referer: https://stats.nba.com/ → 被 API 层 Akamai 拒绝

        ═══ 多阶段策略 ═══
        Phase 1: 访问 stats.nba.com → 通过 Akamai 首页 JS 验证，获取 Akamai Cookie
        Phase 2: 导航到 Mock www.nba.com → 建立正确的 Referer 上下文
                 此时 evaluate(fetch) 的 Referer 自动为 https://www.nba.com/
                 且 stats.nba.com 的 Akamai Cookie 会被自动携带

        回退: 若 Phase 1 完全被 Block → 使用 stats.nba.com Mock 页面 (同源策略)
        """
        session_page_domain = None  # 记录最终页面域名

        # Phase 0: 加载 about:blank 清空初始状态
        try:
            self._page.goto('about:blank', wait_until='commit', timeout=10000)
        except:
            pass

        # ── Phase 1: 获取 Akamai Cookie ──
        logger.info("📡 Phase 1: 获取 Akamai Cookie (stats.nba.com)...")
        success = self._try_load_page('https://stats.nba.com', 'Stats API (Cookie)')

        if not success:
            logger.info("📡 Phase 1 回退: 尝试 www.nba.com...")
            success = self._try_load_page(self.config.NBA_HOMEPAGE, 'NBA.com')

        if success:
            # 检测是否真的通过了 Akamai (不是 Access Denied 页面)
            try:
                title = self._page.title()
                if 'Access Denied' in title or '403' in title or 'blocked' in title.lower():
                    logger.warning(f"⚠️ 检测到 Access Denied: '{title}'")
                    success = False
            except:
                success = False

        if not success:
            # 完全被 Akamai 拦截 — 使用 stats.nba.com Mock 页面
            # 此时 evaluate(fetch) 是同源请求, 无 CORS 但 Referer 错误
            logger.warning("⚠️ Akamai 完全拦截，使用 stats.nba.com Mock 页面...")
            self._serve_mock_nba_page(target_domain='stats.nba.com')
            session_page_domain = 'stats.nba.com'
            self._session_page_domain = session_page_domain
            return

        # 模拟人类浏览 (滚动 + 鼠标)
        self._simulate_human()

        logger.info("✅ Phase 1 完成: Akamai Cookie 已获取")

        # ── Phase 2: 迁移到 www.nba.com 上下文 ──
        # 关键: 我们需要 page.evaluate(fetch) 的 Referer 为 https://www.nba.com/
        # 方法: 导航到 Mock www.nba.com 页面，浏览器自动使用此域名作为 Referer
        # stats.nba.com 的 Akamai Cookie 会被 fetch 请求自动携带
        logger.info("📡 Phase 2: 迁移到 www.nba.com 上下文 (正确 Referer)...")
        self._serve_mock_nba_page(target_domain='www.nba.com')
        session_page_domain = 'www.nba.com'

        try:
            page_url = self._page.url
            logger.info(f"✅ NBA.com 多阶段会话建立 | 页面: {page_url[:60]}")
        except:
            logger.info("✅ NBA.com 多阶段会话建立 (www.nba.com 上下文 + Akamai Cookie)")

        self._session_page_domain = session_page_domain

    def _try_load_page(self, url: str, label: str) -> bool:
        """尝试加载页面，返回是否成功"""
        try:
            logger.info(f"🌐 访问 {label} 建立会话...")
            self._page.goto(url, wait_until='domcontentloaded', timeout=60000)
            return True
        except PlaywrightTimeout:
            logger.warning(f"⚠️ {label} 加载超时")
            return False
        except Exception as e:
            logger.warning(f"⚠️ {label} 访问异常: {e}")
            return False

    def _simulate_human(self):
        """模拟人类浏览行为（随机滚动 + 鼠标移动）"""
        try:
            # 随机滚动
            for _ in range(random.randint(1, 3)):
                self._page.mouse.wheel(0, random.randint(200, 600))
                time.sleep(random.uniform(0.3, 0.8))

            # 随机鼠标移动
            self._page.mouse.move(
                random.randint(200, 800),
                random.randint(200, 500)
            )
            time.sleep(random.uniform(0.2, 0.5))

            # 滚动回顶部
            self._page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass

    def close(self):
        """安全关闭浏览器"""
        # 保存 Cookie
        if self._context:
            try:
                self.cookie_manager.save(self._context)
            except Exception:
                pass

        # 关闭资源
        for obj, name in [
            (self._page, 'Page'),
            (self._context, 'Context'),
            (self._browser, 'Browser'),
        ]:
            if obj:
                try:
                    obj.close()
                except Exception:
                    pass

        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass

        elapsed = ""
        if self._stats['start_time']:
            elapsed = f" | 运行时长: {datetime.now() - self._stats['start_time']}"

        logger.info(
            f"👋 浏览器已关闭 | "
            f"请求: {self._stats['requests_made']} 成功 / {self._stats['requests_failed']} 失败"
            f"{elapsed}"
        )

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.close()

    # ── 核心 API 请求方法 ──────────────────────────────────────

    def _api_call(
        self,
        endpoint: str,
        params: Dict[str, Any],
        retries: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        通过浏览器原生 fetch() 调用 NBA Stats API

        使用 page.evaluate(fetch) — 由浏览器内核发起请求:
        - 使用真实 Chrome TLS 指纹 (Akamai 信任)
        - 自动携带 Akamai 验证 Cookie
        - 同源请求无 CORS 限制 (page 在 stats.nba.com)

        当浏览器通过 Akamai 验证后，fetch() 等同于真实用户在浏览器中访问 API。
        如果 evaluate(fetch) 失败，自动回退到 page.request.get()。

        Args:
            endpoint: API 端点名 (如 'leaguedashteamstats')
            params: 查询参数 (会自动过滤空值)
            retries: 重试次数 (默认使用 config 中的 MAX_RETRIES)

        Returns:
            API JSON 响应字典，格式: {"resultSets": [...]}
        """
        if retries is None:
            retries = self.config.MAX_RETRIES

        # 过滤空值参数
        clean_params = {k: v for k, v in params.items() if v != '' and v is not None}
        query_string = '&'.join(f"{k}={v}" for k, v in clean_params.items())
        url = f"{self.config.STATS_API_BASE}/{endpoint}?{query_string}"

        last_error = None
        for attempt in range(retries):
            try:
                if not self.scheduler.can_proceed():
                    wait_sec = random.uniform(60, 180)
                    logger.warning(f"⛔ 达到限速，等待 {wait_sec:.0f} 秒...")
                    time.sleep(wait_sec)
                    continue

                self.scheduler.wait()
                logger.info(f"📡 [{attempt+1}/{retries}] {endpoint}")

                # ── 策略 1: page.evaluate(fetch) — 浏览器原生请求 ──
                body = self._try_evaluate_fetch(url)
                if body is None:
                    # 策略 2: page.request.get() — Playwright HTTP API 回退
                    body = self._try_request_get(url)

                if body is None:
                    raise Exception("所有请求策略均失败")

                # 记录请求
                self.scheduler.record()
                self._stats['requests_made'] += 1
                self._stats['bytes_downloaded'] += len(body)

                # 解析 JSON
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    is_html = body.strip().startswith('<!') or '<html' in body[:100].lower()
                    if is_html:
                        logger.warning("⚠️ API 返回 HTML (被拦截)，重建会话...")
                        self._establish_session()
                        time.sleep(3)
                        continue
                    raise

                logger.info(f"✅ {endpoint} 成功 ({len(body)} bytes)")
                return data

            except Exception as e:
                last_error = e
                if attempt < retries - 1:
                    delay = 2 ** min(attempt, 5)
                    logger.warning(f"⚠️ 失败 ({attempt+1}/{retries}): {e}, {delay}s 后重试")
                    time.sleep(delay)
                    if attempt >= 3:
                        self._establish_session()
                else:
                    self._stats['requests_failed'] += 1

        raise Exception(f"API 调用失败 ({retries} 次重试后): {last_error}")

    def _try_evaluate_fetch(self, url: str) -> Optional[str]:
        """
        策略1: page.evaluate(fetch) — 浏览器真实 TLS 指纹

        由 Chrome 内核发起 HTTP 请求，TLS 指纹与用户浏览完全一致。
        NBA.com 的 Akamai 会将此请求识别为真实用户。

        关键: fetch 的 Referer 自动等于当前页面 URL。
        - 页面在 www.nba.com → Referer: https://www.nba.com/ ✅
        - 页面在 stats.nba.com → Referer: https://stats.nba.com/ ❌ (API 拒绝)

        Returns:
            响应正文字符串，失败返回 None
        """
        try:
            result = self._page.evaluate("""
                async (url) => {
                    const controller = new AbortController();
                    const timeout = setTimeout(() => controller.abort(), 25000);
                    try {
                        const resp = await fetch(url, {
                            headers: {
                                'Accept': 'application/json, text/plain, */*',
                                'x-nba-stats-origin': 'stats',
                                'x-nba-stats-token': 'true',
                            },
                            signal: controller.signal,
                            credentials: 'include',
                        });
                        clearTimeout(timeout);
                        const text = await resp.text();
                        const isHtml = text.trim().startsWith('<!') || text.includes('<html');
                        return {
                            ok: resp.ok,
                            status: resp.status,
                            body: text.substring(0, 300),
                            fullBody: text,
                            isHtml: isHtml,
                            url: resp.url,
                            contentType: resp.headers.get('content-type') || '',
                        };
                    } catch(e) {
                        clearTimeout(timeout);
                        return {error: e.message || String(e)};
                    }
                }
            """, url)

            if result.get('error'):
                logger.debug(f"  evaluate(fetch) 错误: {result['error'][:100]}")
                return None

            # 调试：记录响应类型
            status = result.get('status', 0)
            is_html = result.get('isHtml', False)
            ct = result.get('contentType', '')
            logger.debug(
                f"  evaluate(fetch) → HTTP {status} | "
                f"Content-Type: {ct[:50]} | "
                f"isHtml: {is_html} | "
                f"preview: {result.get('body', '')[:80]}"
            )

            if result.get('ok') and not is_html:
                return result.get('fullBody', '')
            else:
                # 返回 body 让上层判断
                return result.get('fullBody', '')

        except Exception as e:
            logger.debug(f"  evaluate(fetch) 异常: {str(e)[:100]}")
            return None

    def _try_request_get(self, url: str) -> Optional[str]:
        """
        策略2: page.request.get() — Playwright HTTP API 回退

        作为备选方案，当 evaluate(fetch) 失败时使用。
        注意：此方法使用 Node.js HTTP 栈，TLS 指纹可能被 Akamai 检测。

        Returns:
            响应正文字符串，失败返回 None
        """
        try:
            response = self._page.request.get(
                url,
                headers={
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache',
                    'Referer': 'https://www.nba.com/',
                    'Origin': 'https://www.nba.com',
                    'x-nba-stats-origin': 'stats',
                    'x-nba-stats-token': 'true',
                    'User-Agent': random.choice(self.config.USER_AGENTS),
                },
                timeout=self.config.REQUEST_TIMEOUT,
            )
            if response.ok:
                return response.text()
            logger.debug(f"  request.get HTTP {response.status}")
            return response.text()
        except Exception as e:
            logger.debug(f"  request.get 异常: {str(e)[:80]}")
            return None
        """
        解析标准 NBA API 响应 (resultSets 格式)

        NBA API 标准响应结构:
        {
            "resource": "...",
            "parameters": {...},
            "resultSets": [
                {
                    "name": "DataSetName",
                    "headers": ["COL1", "COL2", ...],
                    "rowSet": [[val1, val2, ...], ...]
                },
                ...
            ]
        }

        Returns:
            { "DataSetName": [{"COL1": val1, ...}, ...], ... }
        """
        result_sets = data.get('resultSets', data.get('resultSet', []))
        if isinstance(result_sets, dict):
            result_sets = [result_sets]

        parsed = {}
        for rs in result_sets:
            name = rs.get('name', 'Unknown')
            headers = rs.get('headers', [])
            rows = rs.get('rowSet', [])
            parsed[name] = [dict(zip(headers, row)) for row in rows]

        return parsed

    def _recover_page(self):
        """尝试恢复页面上下文（页面关闭或崩溃时），重建多阶段会话"""
        try:
            if self._page and not self._page.is_closed():
                return
        except:
            pass
        try:
            if self._context:
                self._page = self._context.new_page()
                self._page.add_init_script(self.ANTI_DETECT_SCRIPT)
                # 完整重建多阶段会话
                self._establish_session()
                self._install_api_route_interception()
                logger.info("🔄 页面已重建 (多阶段会话)")
        except Exception as e:
            logger.error(f"页面重建失败: {e}")

    def _to_dataframe(self, parsed: Dict, dataset_name: str = None):
        """将解析结果转为 DataFrame (需安装 pandas)"""
        if not HAS_PANDAS:
            logger.warning("pandas 未安装，返回 dict")
            return parsed

        if dataset_name:
            rows = parsed.get(dataset_name, [])
            return pd.DataFrame(rows) if rows else pd.DataFrame()
        else:
            return {k: pd.DataFrame(v) for k, v in parsed.items() if v}

    # ── 端点封装 ───────────────────────────────────────────────

    # ──────────── 记分板 ────────────

    def get_scoreboard(self, game_date: str) -> Dict:
        """
        获取指定日期的比赛记分板

        Args:
            game_date: 日期字符串 'YYYY-MM-DD' (如 '2026-06-17')

        Returns:
            {
                "GameHeader": [...],
                "LineScore": [...],
                "TeamLeaders": [...],
                "SeriesStandings": [...],
                ...
            }
        """
        endpoint = self.config.ENDPOINTS['scoreboard']
        params = {
            'GameDate': game_date,
            'LeagueID': '00',
            'DayOffset': '0',
        }
        data = self._api_call(endpoint, params)
        return self._parse_result_sets(data)

    # ──────────── BoxScore 系列 ────────────

    def get_boxscore_traditional(self, game_id: str) -> Dict:
        """获取比赛传统技术统计 (得分/篮板/助攻等)"""
        data = self._api_call(
            self.config.ENDPOINTS['boxscore_traditional'],
            {
                'GameID': game_id,
                'StartPeriod': '0',
                'EndPeriod': '0',
                'StartRange': '0',
                'EndRange': '0',
                'RangeType': '0',
            }
        )
        return self._parse_result_sets(data)

    def get_boxscore_advanced(self, game_id: str) -> Dict:
        """获取比赛高阶数据 (OFF_RATING/DEF_RATING/PIE 等)"""
        data = self._api_call(
            self.config.ENDPOINTS['boxscore_advanced'],
            {
                'GameID': game_id,
                'StartPeriod': '0',
                'EndPeriod': '0',
                'StartRange': '0',
                'EndRange': '0',
                'RangeType': '0',
            }
        )
        return self._parse_result_sets(data)

    def get_boxscore_fourfactors(self, game_id: str) -> Dict:
        """获取比赛四因素 (eFG%/TOV%/OREB%/FT_RATE)"""
        data = self._api_call(
            self.config.ENDPOINTS['boxscore_fourfactors'],
            {
                'GameID': game_id,
                'StartPeriod': '0',
                'EndPeriod': '0',
                'StartRange': '0',
                'EndRange': '0',
                'RangeType': '0',
            }
        )
        return self._parse_result_sets(data)

    def get_boxscore_scoring(self, game_id: str) -> Dict:
        """获取得分分布 (禁区/中距离/三分 出手和命中)"""
        data = self._api_call(
            self.config.ENDPOINTS['boxscore_scoring'],
            {
                'GameID': game_id,
                'StartPeriod': '0',
                'EndPeriod': '0',
                'StartRange': '0',
                'EndRange': '0',
                'RangeType': '0',
            }
        )
        return self._parse_result_sets(data)

    def get_boxscore_misc(self, game_id: str) -> Dict:
        """获取比赛杂项 (PTS_OFF_TOV/PITP 等)"""
        data = self._api_call(
            self.config.ENDPOINTS['boxscore_misc'],
            {
                'GameID': game_id,
                'StartPeriod': '0',
                'EndPeriod': '0',
                'StartRange': '0',
                'EndRange': '0',
                'RangeType': '0',
            }
        )
        return self._parse_result_sets(data)

    def get_boxscore_usage(self, game_id: str) -> Dict:
        """获取使用率数据 (USG_PCT/PCT_FGA 等)"""
        data = self._api_call(
            self.config.ENDPOINTS['boxscore_usage'],
            {
                'GameID': game_id,
                'StartPeriod': '0',
                'EndPeriod': '0',
                'StartRange': '0',
                'EndRange': '0',
                'RangeType': '0',
            }
        )
        return self._parse_result_sets(data)

    def get_boxscore_summary(self, game_id: str) -> Dict:
        """获取比赛摘要 (GameSummary/GameInfo/Officials 等 9 个数据集)"""
        data = self._api_call(
            self.config.ENDPOINTS['boxscore_summary'],
            {'GameID': game_id}
        )
        return self._parse_result_sets(data)

    # ──────────── Play-by-Play ────────────

    def get_playbyplay(self, game_id: str) -> Dict:
        """
        获取比赛逐球记录

        返回的 "PlayByPlay" 数据集包含 24+ 字段，每行代表一次事件:
        EVENTNUM, EVENTMSGTYPE, EVENTMSGACTIONTYPE, PERIOD, PCTIMESTRING,
        SCORE, SCOREMARGIN, PLAYER1_ID, PLAYER1_NAME, HOMEDESCRIPTION, etc.
        """
        data = self._api_call(
            self.config.ENDPOINTS['playbyplay'],
            {
                'GameID': game_id,
                'StartPeriod': '0',
                'EndPeriod': '0',
            }
        )
        return self._parse_result_sets(data)

    # ──────────── 排名 ────────────

    def get_standings(self, season: str) -> Dict:
        """
        获取赛季排名

        Args:
            season: 赛季字符串 'YYYY-YY' (如 '2025-26')

        Returns:
            包含东西部排名、分区排名等多个数据集
        """
        data = self._api_call(
            self.config.ENDPOINTS['standings'],
            {
                'LeagueID': '00',
                'Season': season,
                'SeasonType': 'Regular Season',
            }
        )
        return self._parse_result_sets(data)

    # ──────────── 球队统计 ────────────

    def get_team_stats(
        self, season: str, team_id: str = '', per_mode: str = 'PerGame'
    ) -> Dict:
        """
        获取球队赛季统计

        Args:
            season: '2025-26'
            team_id: 球队ID (空字符串=所有球队)。常用ID: 1610612747(LAL), 1610612744(GSW)
            per_mode: 'PerGame' / 'Totals' / 'Per100Possessions' / 'Per48'
        """
        data = self._api_call(
            self.config.ENDPOINTS['team_stats'],
            {
                'Season': season,
                'TeamID': team_id,
                'PerMode': per_mode,
                'LeagueID': '00',
                'SeasonType': 'Regular Season',
                'MeasureType': 'Base',
                'PaceAdjust': 'N',
                'PlusMinus': 'N',
                'Rank': 'N',
                'LastNGames': '0',
                'Month': '0',
                'Period': '0',
                'OpponentTeamID': '0',
                'Conference': '',
                'Division': '',
                'Location': '',
                'Outcome': '',
                'SeasonSegment': '',
                'GameSegment': '',
                'DateFrom': '',
                'DateTo': '',
            }
        )
        return self._parse_result_sets(data)

    # ──────────── 球员统计 ────────────

    def get_player_stats(
        self, season: str, player_id: str = '', per_mode: str = 'PerGame'
    ) -> Dict:
        """
        获取球员赛季统计

        Args:
            season: '2025-26'
            player_id: 球员ID (空=所有球员)。常用: 2544(LeBron), 201939(Curry)
            per_mode: 'PerGame' / 'Totals' / 'Per100Possessions' / 'Per48'
        """
        data = self._api_call(
            self.config.ENDPOINTS['player_stats'],
            {
                'Season': season,
                'PlayerID': player_id,
                'PerMode': per_mode,
                'LeagueID': '00',
                'SeasonType': 'Regular Season',
                'MeasureType': 'Base',
                'PaceAdjust': 'N',
                'PlusMinus': 'N',
                'Rank': 'N',
                'LastNGames': '0',
                'Month': '0',
                'Period': '0',
                'OpponentTeamID': '0',
                'Conference': '',
                'Division': '',
                'Location': '',
                'Outcome': '',
                'SeasonSegment': '',
                'GameSegment': '',
                'DateFrom': '',
                'DateTo': '',
                'PlayerExperience': '',
                'PlayerPosition': '',
                'StarterBench': '',
            }
        )
        return self._parse_result_sets(data)

    # ──────────── 比赛日志 ────────────

    def get_team_gamelog(self, team_id: str, season: str) -> Dict:
        """获取球队比赛日志"""
        data = self._api_call(
            self.config.ENDPOINTS['team_gamelog'],
            {
                'TeamID': team_id,
                'Season': season,
                'SeasonType': 'Regular Season',
                'LeagueID': '00',
            }
        )
        return self._parse_result_sets(data)

    def get_player_gamelog(self, player_id: str, season: str) -> Dict:
        """获取球员比赛日志"""
        data = self._api_call(
            self.config.ENDPOINTS['player_gamelog'],
            {
                'PlayerID': player_id,
                'Season': season,
                'SeasonType': 'Regular Season',
                'LeagueID': '00',
            }
        )
        return self._parse_result_sets(data)

    # ──────────── 阵容 / 球员索引 ────────────

    def get_team_roster(self, team_id: str, season: str) -> Dict:
        """获取球队阵容列表"""
        data = self._api_call(
            self.config.ENDPOINTS['team_roster'],
            {
                'TeamID': team_id,
                'Season': season,
                'LeagueID': '00',
            }
        )
        return self._parse_result_sets(data)

    def get_common_all_players(self, season: str, is_only_current: int = 1) -> Dict:
        """
        获取所有球员索引 (含 PLAYER_SLUG, TEAM_SLUG)

        Args:
            season: '2025-26'
            is_only_current: 1=仅现役, 0=全部历史
        """
        data = self._api_call(
            self.config.ENDPOINTS['player_index'],
            {
                'Season': season,
                'LeagueID': '00',
                'IsOnlyCurrentSeason': str(is_only_current),
            }
        )
        return self._parse_result_sets(data)

    def get_player_info(self, player_id: str) -> Dict:
        """获取球员基本信息 (身高/体重/位置/选秀等)"""
        data = self._api_call(
            self.config.ENDPOINTS['player_info'],
            {'PlayerID': player_id}
        )
        return self._parse_result_sets(data)

    def get_player_career(self, player_id: str) -> Dict:
        """
        获取球员生涯统计

        返回多个数据集:
        - SeasonTotalsRegularSeason: 常规赛逐年统计
        - SeasonTotalsPostSeason: 季后赛逐年统计
        - CareerTotalsRegularSeason: 常规赛生涯汇总
        - CareerTotalsPostSeason: 季后赛生涯汇总
        - SeasonRankingsRegularSeason: 常规赛排名
        """
        data = self._api_call(
            self.config.ENDPOINTS['player_career'],
            {'PlayerID': player_id, 'PerMode': 'PerGame'}
        )
        return self._parse_result_sets(data)

    # ──────────── Team Dashboard ────────────

    def get_team_dashboard(self, team_id: str, season: str) -> Dict:
        """获取球队综合仪表盘数据 (按对手/月份/主场客场等维度拆分)"""
        data = self._api_call(
            self.config.ENDPOINTS['team_dashboard'],
            {
                'TeamID': team_id,
                'Season': season,
                'SeasonType': 'Regular Season',
                'LeagueID': '00',
                'MeasureType': 'Base',
                'PerMode': 'PerGame',
                'PlusMinus': 'N',
                'PaceAdjust': 'N',
                'Rank': 'N',
                'Month': '0',
                'Period': '0',
                'LastNGames': '0',
                'Location': '',
                'Outcome': '',
                'SeasonSegment': '',
                'DateFrom': '',
                'DateTo': '',
                'OpponentTeamID': '0',
                'VsConference': '',
                'VsDivision': '',
            }
        )
        return self._parse_result_sets(data)

    # ──────────── League Game Finder ────────────

    def get_league_game_finder(
        self,
        season: str,
        team_id: str = '',
        player_id: str = '',
        date_from: str = '',
        date_to: str = '',
    ) -> Dict:
        """通用比赛查询引擎 (支持按赛季/球队/球员/日期范围查询)"""
        data = self._api_call(
            self.config.ENDPOINTS['league_game_finder'],
            {
                'LeagueID': '00',
                'Season': season,
                'SeasonType': 'Regular Season',
                'TeamID': team_id or '0',
                'PlayerID': player_id or '0',
                'DateFrom': date_from,
                'DateTo': date_to,
            }
        )
        return self._parse_result_sets(data)

    # ── 数据导出 ────────────────────────────────────────────────

    def to_dataframe(self, parsed: Dict, dataset_name: str = None):
        """将解析的 dict 转为 pandas DataFrame"""
        return self._to_dataframe(parsed, dataset_name)

    def to_csv(self, parsed: Dict, output_dir: str, prefix: str = ''):
        """将所有数据集导出为 CSV 文件"""
        if not HAS_PANDAS:
            raise ImportError("导出 CSV 需要安装 pandas: pip install pandas")

        os.makedirs(output_dir, exist_ok=True)
        files = []

        for ds_name, rows in parsed.items():
            if not rows:
                continue
            df = pd.DataFrame(rows)
            filename = f"{prefix}_{ds_name}.csv" if prefix else f"{ds_name}.csv"
            filepath = os.path.join(output_dir, filename)
            df.to_csv(filepath, index=False, encoding='utf-8-sig')
            files.append(filepath)
            logger.info(f"💾 保存: {filepath} ({len(df)} 行)")

        return files

    def to_postgres(self, table_name: str, parsed: Dict, dataset_name: str = None):
        """
        将数据写入 PostgreSQL

        Args:
            table_name: 目标表名
            parsed: 解析后的数据字典
            dataset_name: 指定数据集名 (不指定则写入所有)
        """
        if not HAS_PSYCOPG2:
            raise ImportError("需要安装 psycopg2: pip install psycopg2-binary")

        datasets = {dataset_name: parsed[dataset_name]} if dataset_name else parsed
        conn = psycopg2.connect(**self.config.DB_CONFIG)

        try:
            cur = conn.cursor()
            for ds_name, rows in datasets.items():
                if not rows:
                    continue
                columns = list(rows[0].keys())
                values = [tuple(row.get(c) for c in columns) for row in rows]

                target = f"{table_name}_{ds_name}" if dataset_name is None else table_name
                execute_values(
                    cur,
                    f"INSERT INTO {target} ({','.join(columns)}) VALUES %s "
                    f"ON CONFLICT DO NOTHING",
                    values,
                    page_size=1000
                )

            conn.commit()
            logger.info(f"🗄️ 写入 PostgreSQL: {table_name} ({sum(len(v) for v in datasets.values())} 行)")

        finally:
            cur.close()
            conn.close()

    # ── 状态查询 ────────────────────────────────────────────────

    def status(self) -> Dict:
        """获取爬虫运行状态"""
        return {
            'browser_running': self._browser is not None and self._browser.is_connected(),
            'scheduler': self.scheduler.status(),
            'stats': {
                **self._stats,
                'start_time': self._stats['start_time'].isoformat() if self._stats['start_time'] else None,
            },
        }


# ═══════════════════════════════════════════════════════════════
# 便捷函数 / CLI
# ═══════════════════════════════════════════════════════════════

def quick_scoreboard(date: str = None) -> pd.DataFrame:
    """快速获取指定日期比赛信息 (返回 DataFrame)"""
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')

    with NBAPlaywrightScraper(headless=True) as scraper:
        data = scraper.get_scoreboard(date)
        return scraper.to_dataframe(data, 'GameHeader')


def quick_standings(season: str = '2025-26') -> pd.DataFrame:
    """快速获取赛季排名"""
    with NBAPlaywrightScraper(headless=True) as scraper:
        data = scraper.get_standings(season)
        return scraper.to_dataframe(data, 'Standings')


def print_status():
    """打印当前调度状态 (不启动浏览器)"""
    config = NBAPlaywrightConfig()
    scheduler = SmartScheduler(config)
    print("=" * 60)
    print("📊 NBA Playwright 爬虫 - 调度状态")
    print("=" * 60)
    for k, v in scheduler.status().items():
        print(f"  {k}: {v}")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'status':
        print_status()
        sys.exit(0)

    print("=" * 70)
    print("🏀 NBA 官方数据 Playwright 爬虫")
    print("=" * 70)
    print()
    print("📋 端点支持列表:")
    for name, endpoint in NBAPlaywrightConfig.ENDPOINTS.items():
        print(f"  ✓ {name:25s} → stats.nba.com/stats/{endpoint}")
    print()
    print("🛡️ 反爬特性:")
    print("  ✓ Playwright Stealth (隐藏 webdriver / 伪造指纹)")
    print("  ✓ 浏览器原生 fetch() 发起请求 (完美 TLS 指纹)")
    print("  ✓ 智能限速调度 (高峰/低峰自适应)")
    print("  ✓ Cookie 持久化 (跨启动复用会话)")
    print("  ✓ 指数退避重试 (429/403 自动处理)")
    print("  ✓ 拟人化行为 (随机滚动/鼠标移动)")
    print()
    print("🚀 快速使用:")
    print("  from crawler.nba_playwright_scraper import NBAPlaywrightScraper")
    print("  scraper = NBAPlaywrightScraper(headless=True)")
    print("  scraper.start()")
    print("  data = scraper.get_scoreboard('2026-06-17')")
    print("  df = scraper.to_dataframe(data, 'GameHeader')")
    print("  scraper.close()")
    print()
    print("💡 或使用上下文管理器 (自动启动/关闭):")
    print("  with NBAPlaywrightScraper() as scraper:")
    print("      data = scraper.get_standings('2025-26')")
    print()

    print_status()
