"""T01/T02 migration runner — executes the fixed SQL files via psycopg2.

Run from the project root:
    python sql/run_migrations.py

The SQL files (001/002/003) are fixed constants shipped with the code, NOT
dynamic SQL built from user input (v8 §6 compliant). Execution uses a
dedicated write connection (psycopg2), kept separate from the read-only
``batch_query`` pool used by the engine's data layer.

Note: DB is localhost — no HTTP proxy involved, but we clear proxy env vars
defensively in case the shell exported them.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow `import backend` when run as a script from the project root.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from psycopg2 import connect  # noqa: E402
from backend.core import config  # noqa: E402


def _dsn() -> str:
    return config.db_dsn()


def run_file(path: Path) -> None:
    """Execute every statement in a fixed SQL file on a write connection."""
    sql = path.read_text(encoding="utf-8")
    conn = connect(_dsn())
    try:
        with conn.cursor() as cur:
            # psycopg2 executes the whole script (multi-statement) in one call.
            cur.execute(sql)
        conn.commit()
        print(f"[ok] executed {path.name}")
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"[FAIL] {path.name}: {exc}")
        raise
    finally:
        conn.close()


def main() -> None:
    sql_dir = Path(__file__).resolve().parent
    ordered = [
        sql_dir / "001_create_league_salary_rules.sql",
        sql_dir / "002_seed_league_salary_rules_2025_26.sql",
        sql_dir / "003_backfill_two_way_flag.sql",
    ]
    for f in ordered:
        if not f.exists():
            raise FileNotFoundError(f"missing migration file: {f}")
        run_file(f)
    print("migrations complete")


if __name__ == "__main__":
    # Defensive: clear proxy vars so a stray HTTP proxy never intercepts localhost.
    for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.pop(_k, None)
    main()
