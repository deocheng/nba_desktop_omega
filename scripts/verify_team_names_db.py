"""scripts/verify_team_names_db.py — startup cross-check of common/team_names.

Run BEFORE a live crawl to confirm the code-hardened 30-team maps agree with
``dim_teams``. The check is by **abbr/slug alignment only** — ``dim_teams.team_name``
is Chinese, so English ``TEAM_FULL_NAME`` values are NOT compared to it.

Alignment rules (see common/team_names.check_against_db):
  * every canonical abbr's BR slug must resolve to a real dim_teams.team_abbr row;
  * every *active* dim_teams.team_abbr must reverse-map to a crawled canonical abbr.

Exit code 0 if consistent, 1 if any mismatch.

    python scripts/verify_team_names_db.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.team_names import (  # noqa: E402
    BR_TEAM_SLUGS,
    TEAM_ABBRS,
    TEAM_FULL_NAME,
    check_against_db,
)
from hof_exec.config import get_conn, load_dotenv  # noqa: E402

load_dotenv()


def main() -> int:
    print(f"Canonical abbrs: {len(TEAM_ABBRS)}")
    print(f"Full-name entries: {len(TEAM_FULL_NAME)}")

    try:
        conn = get_conn()
    except Exception as exc:  # noqa: BLE001
        print(f"DB connection failed: {type(exc).__name__}: {exc}")
        print("Cannot verify against dim_teams. Aborting (run with a live DB).")
        return 1

    try:
        result = check_against_db(conn)
    finally:
        conn.close()

    missing = result["missing_in_db"]
    extra = result["extra_in_db"]

    if missing:
        print("FAIL: canonical abbrs whose slug is NOT in dim_teams.team_abbr:")
        for a in missing:
            print(f"  - {a} (slug={BR_TEAM_SLUGS[a]})")
    if extra:
        print("FAIL: active dim_teams.team_abbr values not crawled by any canonical abbr:")
        for a in extra:
            print(f"  - {a}")

    if not missing and not extra:
        print("OK: TEAM_ABBRS / BR_TEAM_SLUGS align with dim_teams (abbr/slug).")
        return 0

    print("MISMATCH found — fix common/team_names.py or dim_teams before crawling.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
