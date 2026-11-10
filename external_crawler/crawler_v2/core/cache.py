#!/usr/bin/env python3
"""
core/cache.py — 缓存抽象层（借鉴 MediaCrawler cache/：abs_cache + local_cache + redis_cache + cache_factory）。

在 BR 场景里，缓存 = "修正缓冲"（旧 gamelog_cache / pbp_raw 的角色）。
关键语义：缓存是缓冲，DB 是权威源；DB 全量后缓存可删 / 可失效。
v2 把这一契约显式化：LocalCache 带 TTL + 可主动 invalidate；RedisCache 可选（guarded import）。
"""
import abc
import json
import logging
import os
import threading
import time

log = logging.getLogger("br_crawler_v2.cache")


class AbsCache(abc.ABC):
    @abc.abstractmethod
    def get(self, key: str):
        ...

    @abc.abstractmethod
    def set(self, key: str, value, ttl: int = 0):
        ...

    @abc.abstractmethod
    def delete(self, key: str):
        ...

    @abc.abstractmethod
    def exists(self, key: str) -> bool:
        ...


class LocalCache(AbsCache):
    """进程内 TTL 缓存（借鉴 MediaCrawler local_cache 的"过期即失效"语义）。

    用法：
        c = LocalCache(ttl=3600)
        c.set("gamelog:2023:12345", rows)
        rows = c.get("gamelog:2023:12345")   # 过期返回 None
    """

    def __init__(self, ttl: int = 0, persist_dir: str = None):
        self._ttl = ttl
        self._data = {}
        self._expire = {}
        self._lock = threading.Lock()
        self._persist_dir = persist_dir
        if persist_dir:
            os.makedirs(persist_dir, exist_ok=True)
            self._load_persisted()

    def get(self, key: str):
        with self._lock:
            if key not in self._data:
                return None
            exp = self._expire.get(key, 0)
            if exp and time.time() > exp:
                self._data.pop(key, None)
                self._expire.pop(key, None)
                self._maybe_persist(key, None)
                return None
            return self._data[key]

    def set(self, key: str, value, ttl: int = 0):
        with self._lock:
            self._data[key] = value
            self._expire[key] = (time.time() + (ttl or self._ttl)) if (ttl or self._ttl) else 0
            self._maybe_persist(key, value)

    def delete(self, key: str):
        with self._lock:
            self._data.pop(key, None)
            self._expire.pop(key, None)
            self._maybe_persist(key, None)

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def _maybe_persist(self, key: str, value):
        if not self._persist_dir:
            return
        path = os.path.join(self._persist_dir, f"{key}.cache.json")
        try:
            if value is None:
                if os.path.exists(path):
                    os.remove(path)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"v": value}, f)
        except Exception as e:  # noqa: BLE001
            log.debug("persist skip %s: %s", key, e)

    def _load_persisted(self):
        try:
            for fn in os.listdir(self._persist_dir):
                if fn.endswith(".cache.json"):
                    key = fn[: -len(".cache.json")]
                    with open(os.path.join(self._persist_dir, fn), encoding="utf-8") as f:
                        self._data[key] = json.load(f).get("v")
        except Exception as e:  # noqa: BLE001
            log.debug("load persisted skip: %s", e)


class RedisCache(AbsCache):
    """可选 Redis 缓存（guarded import，未装 redis 包时不可用，不影响本地模式）。"""

    def __init__(self, url: str = "redis://localhost:6379/0"):
        try:
            import redis  # type: ignore
        except ImportError:
            raise RuntimeError("redis 包未安装；用 LocalCache 即可，勿强行启用 RedisCache")
        self._r = redis.from_url(url)

    def get(self, key: str):
        v = self._r.get(key)
        return json.loads(v) if v else None

    def set(self, key: str, value, ttl: int = 0):
        self._r.set(key, json.dumps(value), ex=ttl or None)

    def delete(self, key: str):
        self._r.delete(key)

    def exists(self, key: str) -> bool:
        return bool(self._r.exists(key))


class CacheFactory:
    """工厂：据名字返回缓存实现（映射 MediaCrawler cache_factory）。"""
    @staticmethod
    def create(kind: str = "local", **kw) -> AbsCache:
        kind = (kind or "local").lower()
        if kind == "local":
            return LocalCache(ttl=kw.get("ttl", 0), persist_dir=kw.get("persist_dir"))
        if kind == "redis":
            return RedisCache(url=kw.get("url", "redis://localhost:6379/0"))
        raise ValueError(f"未知 cache kind: {kind}")
