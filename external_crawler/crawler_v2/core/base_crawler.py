#!/usr/bin/env python3
"""
core/base_crawler.py — 爬虫基类（借鉴 MediaCrawler base/base_crawler.py 的模板方法）。

统一契约（所有 BR 数据源适配器都遵循）：
    fetch()      -> 取原始页（HTML/JSON），可走代理 Provider + 限流 + 缓存
    parse()      -> 把原始页解析成结构化行（复用既有 parse 函数，不重造）
    normalize()  -> 字段对齐/清洗（franchise code 修正、坐标系一致性等）
    store()      -> 经 Store 抽象层幂等落库

并内置：
    - RateLimiter（旧 br_fill_pbp.RateLimiter 的滚动窗口硬限速，<=15 req/min）
    - SessionGone 异常 + 自动重建（旧 build_driver/fetch_pbp_soup 的语义）
    - 重试装饰器（core/retry.py）

子类只需实现 fetch/parse/normalize，store 用基类默认（PGStore）。
"""
import abc
import logging
import time
from typing import Any, Dict, List, Optional

from .cache import AbsCache, CacheFactory
from .proxy import ProxyProvider, StaticProxyProvider
from .retry import retry
from .store import Store, StoreFactory

log = logging.getLogger("br_crawler_v2.base")


class SessionGone(Exception):
    """会话失效（driver 崩溃 / CDP 断开 / invalid session id）。"""


class RateLimiter:
    """BR 请求硬上限：最小间隔 + 滚动 60s 窗口（旧 br_fill_pbp.RateLimiter 原样保留）。"""

    def __init__(self, max_per_minute: int = 15, min_interval: float = 4.5):
        self.max_per_minute = max(1, int(max_per_minute))
        self.min_interval = max(1.0, float(min_interval))
        self._times: List[float] = []
        self._last = 0.0

    def wait(self):
        now = time.time()
        sleep_for = 0.0
        since_last = now - self._last
        if since_last < self.min_interval:
            sleep_for = self.min_interval - since_last
        cutoff = now - 60.0
        self._times = [t for t in self._times if t > cutoff]
        if len(self._times) >= self.max_per_minute:
            sleep_for = max(sleep_for, self._times[0] + 60.0 - now)
        if sleep_for > 0:
            time.sleep(sleep_for)
        now = time.time()
        self._times.append(now)
        self._last = now


class BaseCrawler(abc.ABC):
    def __init__(self, *, cache: AbsCache = None, proxy: ProxyProvider = None,
                 store: Store = None, rate_per_min: int = 15, min_interval: float = 4.5,
                 cache_ttl: int = 0, cache_dir: str = None):
        self.cache = cache or CacheFactory.create("local", ttl=cache_ttl, persist_dir=cache_dir)
        self.proxy = proxy or StaticProxyProvider()
        self.store = store or StoreFactory.create("pg")
        self.limiter = RateLimiter(rate_per_min, min_interval)
        self.dry_run = False

    # ---- 子类必须实现 ----
    @abc.abstractmethod
    def fetch(self, target: Any) -> Any:
        """取原始页。抛 SessionGone 表示会话失效需重建。"""
        ...

    @abc.abstractmethod
    def parse(self, raw: Any, target: Any) -> List[Dict[str, Any]]:
        """原始页 -> 结构化行。复用既有 parse 函数。"""
        ...

    @abc.abstractmethod
    def normalize(self, rows: List[Dict[str, Any]], target: Any) -> List[Dict[str, Any]]:
        """字段对齐/清洗。默认原样返回。"""
        ...

    # ---- 子类可选覆盖 ----
    def store_table(self) -> str:
        raise NotImplementedError("子类需声明目标表名")

    def store_columns(self) -> List[str]:
        raise NotImplementedError("子类需声明列名")

    def key_columns(self) -> List[str]:
        return ["gameid"]

    # ---- 基类流水线 ----
    @retry(max_attempts=3, retry_on=(SessionGone,))
    def process_one(self, target: Any) -> Dict[str, Any]:
        """单目标全流程：fetch→parse→normalize→store。带限流 + 重试。"""
        self.limiter.wait()
        cache_key = self._cache_key(target)
        cached = self.cache.get(cache_key)
        if cached is not None:
            rows = cached
        else:
            raw = self.fetch(target)
            rows = self.parse(raw, target)
            if rows:
                self.cache.set(cache_key, rows)
        rows = self.normalize(rows, target)
        written = 0
        if rows and not self.dry_run:
            written = self.store.save(
                self.store_table(), self.store_columns(), self.key_columns(), rows)
        return {"target": target, "rows": len(rows), "written": written}

    def _cache_key(self, target: Any) -> str:
        return f"{self.__class__.__name__}:{target}"

    def run(self, targets: List[Any]) -> Dict[str, int]:
        ok = fail = total = 0
        for t in targets:
            try:
                r = self.process_one(t)
                ok += 1
                total += r["rows"]
            except Exception as e:  # noqa: BLE001
                log.error("[run] 目标 %s 失败: %s", t, e)
                fail += 1
        return {"ok": ok, "fail": fail, "rows": total}
