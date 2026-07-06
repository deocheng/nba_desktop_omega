"""NBACore v8 §2 Layer 2 — Cache Engine.

diskcache-backed deterministic cache for metric computations.

Key strategy (v8 §5.3 determinism):
    - SHA256 of (metric_name | season | sorted(player_ids) | params_json)
    - params_json uses sort_keys=True (stable)
    - Value pickled with protocol=5 (fixed for byte-stable serialization)

v8 §6 forbidden list:
    - no eval/exec (pickle.loads is safe — only store our own Series)
"""
from __future__ import annotations

import hashlib
import json
import logging
import pickle
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd
from diskcache import Cache

from backend.core import config

logger = logging.getLogger("nbacore.metric.cache")

# Default cache directory — sibling to backend/ so it survives restarts.
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent.parent.parent / ".cache" / "metric_engine"

# TTL: 24h default (season data doesn't change mid-day).
_DEFAULT_TTL = 24 * 3600

_PICKLE_PROTOCOL = 5  # fixed for byte-stable serialization

# DiskCache timeout + retry settings (important for Windows EXE multi-worker
# scenarios where SQLite file-based locking can occasionally time out).
_CACHE_TIMEOUT = 5.0  # seconds — diskcache default is 1.0, too aggressive
_CACHE_RETRIES = 3    # number of retries on timeout before giving up


def _resolve_cache_dir() -> Path:
    """Resolve cache dir from config or fall back to default."""
    cfg_val = getattr(config, "METRIC_CACHE_DIR", None)
    if cfg_val:
        p = Path(cfg_val)
    else:
        p = _DEFAULT_CACHE_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def make_cache_key(
    metric_name: str,
    season: int,
    player_ids: list[str] | None,
    params: dict | None = None,
) -> str:
    """Build a deterministic SHA256 cache key.

    Args:
        metric_name: registered metric name
        season: NBA season int
        player_ids: list of BBR IDs (sorted for stability); None = all players
        params: optional dict of metric params (sort_keys=True)

    Returns: hex SHA256 string.
    """
    if player_ids is not None:
        ids_norm = sorted(str(p) for p in player_ids)
        ids_repr = ",".join(ids_norm)
    else:
        ids_repr = "*ALL*"
    params_norm = json.dumps(params or {}, sort_keys=True, default=str)
    payload = f"{metric_name}|{season}|{ids_repr}|{params_norm}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CacheEngine:
    """diskcache wrapper with explicit get/set/invalidate API.

    Windows / PyInstaller EXE safety:
    - explicit timeout to avoid indefinite SQLite lock waits
    - built-in retry logic for transient lock contention
    - graceful degradation: on persistent failure, returns None (cache miss)
      rather than crashing the request
    """

    def __init__(self, cache_dir: Path | str | None = None, ttl: int = _DEFAULT_TTL) -> None:
        self._dir = Path(cache_dir) if cache_dir else _resolve_cache_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache = Cache(str(self._dir), timeout=_CACHE_TIMEOUT)
        self._ttl = ttl
        logger.info(
            "CacheEngine initialized | dir=%s | ttl=%ds | timeout=%.1fs | retries=%d",
            self._dir, self._ttl, _CACHE_TIMEOUT, _CACHE_RETRIES,
        )

    def _with_retry(self, fn: Callable, default=None):
        """Execute a diskcache operation with retries on lock timeout.

        diskcache uses SQLite under the hood. On Windows with multiple
        workers / processes, concurrent writes can trigger OperationalError
        or timeout. Retry with exponential backoff before giving up.
        """
        last_exc = None
        for attempt in range(_CACHE_RETRIES):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if "lock" in str(exc).lower() or "timeout" in str(exc).lower() or "busy" in str(exc).lower():
                    wait = 0.1 * (2 ** attempt)  # 0.1s, 0.2s, 0.4s
                    logger.warning(
                        "cache op failed (attempt %d/%d), retrying in %.1fs | %s",
                        attempt + 1, _CACHE_RETRIES, wait, exc,
                    )
                    time.sleep(wait)
                else:
                    raise
        logger.error("cache op failed after %d retries | %s", _CACHE_RETRIES, last_exc)
        return default

    @property
    def dir(self) -> Path:
        return self._dir

    @property
    def ttl(self) -> int:
        return self._ttl

    def get(self, key: str) -> pd.Series | pd.DataFrame | None:
        """Return cached value or None. Hit/miss logged at debug level."""
        raw = self._with_retry(lambda: self._cache.get(key, default=None), default=None)
        if raw is None:
            logger.debug("cache MISS | key=%s", key[:12])
            return None
        try:
            value = pickle.loads(raw)
            logger.debug("cache HIT  | key=%s", key[:12])
            return value
        except Exception as exc:
            logger.warning("cache deserialization failed | key=%s | %s", key[:12], exc)
            self._with_retry(lambda: self._cache.delete(key), default=False)
            return None

    def set(self, key: str, value: pd.Series | pd.DataFrame) -> None:
        """Store value under key with TTL."""
        raw = pickle.dumps(value, protocol=_PICKLE_PROTOCOL)
        self._with_retry(lambda: self._cache.set(key, raw, expire=self._ttl), default=None)
        logger.debug("cache SET  | key=%s | bytes=%d", key[:12], len(raw))

    def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], pd.Series | pd.DataFrame],
    ) -> pd.Series | pd.DataFrame:
        """Idempotent get-or-compute. compute_fn only called on miss."""
        cached = self.get(key)
        if cached is not None:
            return cached
        value = compute_fn()
        if not isinstance(value, (pd.Series, pd.DataFrame)):
            raise TypeError(
                f"CacheEngine only supports pd.Series/pd.DataFrame, got {type(value).__name__}"
            )
        self.set(key, value)
        return value

    def invalidate(self, key: str) -> bool:
        result = self._with_retry(lambda: self._cache.delete(key), default=False)
        return bool(result)

    def invalidate_all(self) -> int:
        """Clear entire cache. Returns number of keys removed."""
        count = self._with_retry(lambda: len(self._cache), default=0)
        self._with_retry(lambda: self._cache.clear(), default=None)
        logger.info("cache cleared | removed=%d", count)
        return count

    def stats(self) -> dict:
        size = self._with_retry(lambda: self._cache.size(), default=0)
        count = self._with_retry(lambda: len(self._cache), default=0)
        return {"dir": str(self._dir), "size_bytes": size, "count": count}

    def close(self) -> None:
        self._cache.close()


# Module-level singleton (lazy-initialized)
_engine: CacheEngine | None = None


def get_engine() -> CacheEngine:
    """Public accessor — initializes on first call."""
    global _engine
    if _engine is None:
        _engine = CacheEngine()
    return _engine


def reset_engine() -> None:
    """For tests: tear down the singleton."""
    global _engine
    if _engine is not None:
        _engine.close()
        _engine = None
