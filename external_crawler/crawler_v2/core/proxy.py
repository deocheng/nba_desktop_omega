#!/usr/bin/env python3
"""
core/proxy.py — 可插拔代理 Provider（借鉴 MediaCrawler proxy/：base_proxy + providers/* 都实现 ProxyProvider）。

v2 关键改进：把旧 cf_breaker 的 "cf_clearance 绑定 IP ~30-60min 过期" 逻辑
建模为 **带 TTL 的 Provider** —— 过期自动触发重新获取（登录/CDP 刷新），
而不是散落在爬虫各处的手搓计时。换付费代理池（如 MediaCrawler 的快代理/豌豆HTTP）
只要新增一个 Provider 子类，爬取逻辑一行不动。
"""
import abc
import time
import logging
from typing import List, Optional

log = logging.getLogger("br_crawler_v2.proxy")


class IpInfo:
    def __init__(self, host: str, port: int, username: str = "", password: str = ""):
        self.host = host
        self.port = port
        self.username = username
        self.password = password

    def http_url(self) -> str:
        if self.username:
            return f"http://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}"

    def __repr__(self):
        return f"IpInfo({self.host}:{self.port})"


class ProxyProvider(abc.ABC):
    """统一代理接口（对应 MediaCrawler ProxyProvider.get_proxy）。"""

    @abc.abstractmethod
    def get_proxy(self, num: int = 1) -> List[IpInfo]:
        ...

    @abc.abstractmethod
    def healthy(self) -> bool:
        ...


class StaticProxyProvider(ProxyProvider):
    """固定单代理（默认 127.0.0.1:12334，旧 recrawl 脚本的本地出口）。无 TTL。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 12334):
        self._ip = IpInfo(host, port)

    def get_proxy(self, num: int = 1) -> List[IpInfo]:
        return [self._ip] * max(1, num)

    def healthy(self) -> bool:
        return True


class CfClearanceProvider(ProxyProvider):
    """带 cf_clearance TTL 的 Provider（封装旧 cf_breaker 的过期重认证逻辑）。

    - 每次 get_proxy 返回当前代理（或 None 表示需重认证）。
    - 超过 ttl_min 未刷新 → 认为 clearance 失效，调用 refresh() 重新获取
      （由使用方注入具体刷新动作：登录 / CDP 重新过 CF）。
    - 这样 cf_breaker 的 "5 次连续 CF → 600s 冷却" 可改成在 refresh() 内部实现，
      爬取循环只关心 "给我一个有效代理"。
    """

    def __init__(self, base: ProxyProvider, ttl_min: int = 45,
                 refresh=None, on_expired=None):
        self._base = base
        self._ttl = ttl_min * 60
        self._refresh = refresh          # callable() -> None，执行重新过 CF/登录
        self._on_expired = on_expired    # callable() -> None，打点/统计
        self._issued_at = 0.0
        self._current: Optional[IpInfo] = None

    def _is_fresh(self) -> bool:
        if not self._current:
            return False
        return (time.time() - self._issued_at) < self._ttl

    def get_proxy(self, num: int = 1) -> List[IpInfo]:
        if not self._is_fresh():
            if self._on_expired:
                try:
                    self._on_expired()
                except Exception:  # noqa: BLE001
                    pass
            if self._refresh:
                try:
                    self._refresh()
                except Exception as e:  # noqa: BLE001
                    log.error("[proxy] cf_clearance 刷新失败: %s", e)
                    return []
            self._current = self._base.get_proxy(1)[0]
            self._issued_at = time.time()
        return [self._current] * max(1, num)

    def healthy(self) -> bool:
        return self._base.healthy()

    def force_refresh(self):
        self._issued_at = 0.0
        self.get_proxy(1)
