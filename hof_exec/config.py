"""hof_exec/config.py — lightweight config + .env loader (no python-dotenv).

Exposes:
  * ``PROJECT_ROOT``  — repo root (parent dir of this package)
  * ``TEAM_ABBRS``    — 30 canonical NBA abbreviations (from common.bridge_constants._CANON)
  * ``BR_TEAM_SLUGS`` — abbr -> BR url slug (BKN->BRK, CHA->CHO; else identity)
  * ``get_conn()``     — psycopg2 connection (forwards to common.bridge_constants.get_pg_conn)

The DB password is read from ``os.environ["DB_PASSWORD"]`` (loaded from the
repo ``.env``) — it is NEVER hardcoded anywhere in this package.
"""

from __future__ import annotations

import os
import sys

# --- project root: this file is <root>/hof_exec/config.py -------------------
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_PKG_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Make ``common`` importable (it lives at the repo root).
# The 30-team reference maps are now a SINGLE SOURCE in common/team_names
# (TEAM_ABBRS, BR_TEAM_SLUGS, TEAM_FULL_NAME). Re-export from there (T02);
# do NOT redefine the slug map here or it forks the single source.
from common.team_names import (  # noqa: E402,F401
    BR_TEAM_SLUGS,
    TEAM_ABBRS,
    TEAM_FULL_NAME,
)


def load_dotenv(path: str | None = None) -> None:
    """Minimal .env loader (~12 lines). Reads KEY=VALUE lines into os.environ
    only for keys not already set. No third-party dependency.
    """
    env_path = path or os.path.join(PROJECT_ROOT, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


# Load .env at import so DB_PASSWORD is available for get_conn().
load_dotenv()


def get_conn():
    """Return a psycopg2 connection to the local nba DB.

    Forwards to ``common.bridge_constants.get_pg_conn`` when available (keeps
    a single DSN source of truth); otherwise falls back to a self-contained
    connect using DB_PASSWORD from the environment (never hardcoded).
    """
    try:
        from common.bridge_constants import get_pg_conn

        return get_pg_conn()
    except Exception:  # pragma: no cover - fallback only if common helper missing
        import psycopg2

        return psycopg2.connect(
            host="localhost",
            port=5433,
            dbname="nba",
            user="postgres",
            password=os.environ["DB_PASSWORD"],
        )
