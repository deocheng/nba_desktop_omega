"""v8.3.2 migration — create the ``analysis_flows`` table (idempotent).

This is the single schema migration for the Analytics Builder feature (T13).
It is safe to run repeatedly: every statement uses ``IF NOT EXISTS``.

Run with the project venv:
    .venv/Scripts/python.exe reconcile_2026-07-11/create_analysis_flows_table.py
"""
from __future__ import annotations

import sys

import os
import psycopg2

# make the project root importable when run as a standalone script
# file lives at <root>/reconcile_2026-07-11/create_analysis_flows_table.py
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# import project config (DB_CONFIG key is "database")
from backend.core import config


CREATE_SQL = """
CREATE TABLE IF NOT EXISTS analysis_flows (
    id             SERIAL PRIMARY KEY,
    workspace_id   INTEGER NOT NULL,
    name           TEXT NOT NULL DEFAULT 'flow',
    definition_json JSONB NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT now(),
    updated_at     TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_analysis_flows_ws ON analysis_flows(workspace_id);
"""


def main() -> int:
    dsn = config.db_dsn()
    print(f"[migrate] connecting to {config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_SQL)
        conn.commit()
        print("[migrate] analysis_flows table ensured (idempotent)")
        # verify
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='analysis_flows' "
                "ORDER BY ordinal_position"
            )
            cols = [r[0] for r in cur.fetchall()]
        print(f"[migrate] columns: {cols}")
        expected = {"id", "workspace_id", "name", "definition_json",
                    "created_at", "updated_at"}
        missing = expected - set(cols)
        if missing:
            print(f"[migrate] ERROR: missing columns {missing}", file=sys.stderr)
            return 1
        print("[migrate] OK — analysis_flows ready")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
