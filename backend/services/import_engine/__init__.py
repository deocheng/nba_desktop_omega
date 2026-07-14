"""NBACore v8 §6 — CSV import engine (designated write-path service).

Public surface for the CSV import feature. The API router consumes only these
names; all psycopg2 access is fenced inside `import_db` (the dedicated writer),
mirroring `backend.services.workspace_engine.workspace_db`.
"""
from __future__ import annotations

from backend.services.import_engine.import_db import (
    close_pool,
    import_csv,
    init_pool,
    list_public_tables,
)

__all__ = [
    "import_csv",
    "list_public_tables",
    "init_pool",
    "close_pool",
]
