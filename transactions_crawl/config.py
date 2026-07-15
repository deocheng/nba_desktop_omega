"""transactions_crawl/config.py — reuses hof_exec.config.

We deliberately do NOT re-implement the .env loader here. ``hof_exec.config``
is the single source of truth for:

  * ``PROJECT_ROOT``  — repo root (parent dir of hof_exec)
  * ``TEAM_ABBRS``    — 30 canonical NBA abbreviations
  * ``BR_TEAM_SLUGS`` — abbr -> BR url slug (BKN->BRK, CHA->CHO; else identity)
  * ``get_conn()``     — psycopg2 connection (DB password from ``.env`` DB_PASSWORD)
  * ``load_dotenv``    — minimal .env loader (run once at hof_exec.config import)

The DB password is therefore read only from the repo ``.env`` (never
hardcoded in this package).
"""

from __future__ import annotations

from hof_exec.config import (
    BR_TEAM_SLUGS,
    PROJECT_ROOT,
    TEAM_ABBRS,
    get_conn,
    load_dotenv,
)

__all__ = [
    "PROJECT_ROOT",
    "TEAM_ABBRS",
    "BR_TEAM_SLUGS",
    "get_conn",
    "load_dotenv",
]
