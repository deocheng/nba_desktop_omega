"""NBACore v8 §2 — Configuration Layer.

Single source of truth for all runtime configuration.
Loaded from .env (manual parser, no python-dotenv dependency) + env var overrides.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

# ── Path Resolution (PyInstaller-aware, inherited from v7) ──
if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(sys._MEIPASS).resolve()
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BUNDLE_DIR = Path(__file__).resolve().parents[2]
    BASE_DIR = BUNDLE_DIR


def _load_dotenv() -> None:
    """Manual .env loader (v8 forbids extra deps for core bootstrap)."""
    for env_path in (BASE_DIR / ".env", BUNDLE_DIR / ".env"):
        if not env_path.exists():
            continue
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        break


_load_dotenv()


def _get(key: str, default: str) -> str:
    return os.getenv(key, default)


def _get_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _get_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, str(default)).strip().lower()
    return raw in ("1", "true", "yes", "on")


# ── Database (v7 used port 5433) ──
DB_HOST: str = _get("DB_HOST", "localhost")
DB_PORT: int = _get_int("DB_PORT", 5433)
DB_NAME: str = _get("DB_NAME", "nba")
DB_USER: str = _get("DB_USER", "postgres")
DB_PASSWORD: str = _get("DB_PASSWORD", "postgres")

DB_CONFIG: dict = {
    "host": DB_HOST,
    "port": DB_PORT,
    "database": DB_NAME,
    "user": DB_USER,
    "password": DB_PASSWORD,
}


def db_dsn() -> str:
    """Return a psycopg2-compatible DSN string."""
    return (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )


# ── Server ──
SERVER_HOST: str = _get("SERVER_HOST", "127.0.0.1")
SERVER_PORT: int = _get_int("SERVER_PORT", 5577)

# ── Cache (Disk Cache, Phase 2 will consume) ──
CACHE_DIR: Path = BASE_DIR / _get("CACHE_DIR", ".cache/metric_engine")

# ── App ──
APP_NAME: str = _get("APP_NAME", "NBACore Studio v8")
APP_VERSION: str = _get("APP_VERSION", "8.0.0")
DEBUG: bool = _get_bool("DEBUG", False)
LOG_LEVEL: str = _get("LOG_LEVEL", "INFO").upper()

# ── NBA Season Helper ──
def current_season() -> int:
    """NBA season: if month >= October, belongs to next year's season."""
    d = date.today()
    return d.year + 1 if d.month >= 10 else d.year


# ── v8 §6 Forbidden Patterns (checked by runtime_guard) ──
FORBIDDEN_SQL_PREFIXES = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
    "CREATE", "TRUNCATE", "GRANT", "REVOKE", "MERGE", "VACUUM",
)
