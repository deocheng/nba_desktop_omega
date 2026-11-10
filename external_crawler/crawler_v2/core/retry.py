#!/usr/bin/env python3
"""
core/retry.py — 借鉴 MediaCrawler 对 tenacity 的使用，但用纯 stdlib 实现，
避免为 v2 引入新增依赖（遵守"栈纪律"）。

用法：
    @retry(max_attempts=3, backoff=2.0, retry_on=(SessionGone,))
    def fetch(...): ...

等价于 tenacity 的 @retry(stop=stop_after_attempt(3), wait=wait_exponential(...))，
但零依赖、可审计。
"""
import functools
import time
import logging

log = logging.getLogger("br_crawler_v2.retry")


def retry(max_attempts: int = 3, backoff: float = 1.0,
          retry_on: tuple = (Exception,), sleep_base: float = 0.0):
    """装饰器：在 retry_on 内的异常上重试，最多 max_attempts 次。

    - backoff: 每次重试的退避基数（指数增长 backoff * 2**(n-1)）。
    - sleep_base: 可选固定底噪，避免对目标站过于规律（反爬友好）。
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except retry_on as e:  # noqa: B904
                    last = e
                    if attempt >= max_attempts:
                        break
                    wait = sleep_base + backoff * (2 ** (attempt - 1))
                    log.warning("[retry] %s 第 %d/%d 次失败: %s，%.2fs 后重试",
                                fn.__name__, attempt, max_attempts, e, wait)
                    time.sleep(wait)
            raise last
        return wrapper
    return deco


def retry_async(max_attempts: int = 3, backoff: float = 1.0,
               retry_on: tuple = (Exception,)):
    """async 版重试装饰器（与 retry 语义一致）。"""
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            last = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except retry_on as e:  # noqa: B904
                    last = e
                    if attempt >= max_attempts:
                        break
                    wait = backoff * (2 ** (attempt - 1))
                    log.warning("[retry] %s 第 %d/%d 次失败: %s，%.2fs 后重试",
                                fn.__name__, attempt, max_attempts, e, wait)
                    await __import__("asyncio").sleep(wait)
            raise last
        return wrapper
    return deco
