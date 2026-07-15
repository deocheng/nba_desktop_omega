"""transactions_crawl/load.py — idempotent upsert into ``transactions``.

Upsert semantics (re-runnable, fixes the legacy concat bug):
  * **Twin de-duplication** — a "bad" legacy row (description glued together
    with no spaces, e.g. ``'TheDetroit PistonssignedMichael Curry...'``) is
    space-equal to the corrected row we now produce. For every entry we first
    look for a twin via ``REPLACE(description,' ','')`` equality on the same
    ``(transaction_date, team_abbr)``; if found we *repair* it in place
    (set the correct ``description`` + ``transaction_type``). Otherwise we
    ``INSERT ... ON CONFLICT (transaction_date, team_abbr, description) DO
    UPDATE`` so a clean re-run is a no-op.

The table schema is NEVER altered (no added/dropped columns).
"""

from __future__ import annotations

import logging
from typing import List

from .config import get_conn
from .parse import TxnEntry

logger = logging.getLogger(__name__)

_SOURCE = "basketball-reference"


def upsert_transactions(rows: List[TxnEntry]) -> int:
    """Upsert a list of ``TxnEntry`` into ``transactions``. Returns rows written/updated.

    Each entry either repairs a legacy space-less twin (``UPDATE``) or is
    inserted (``INSERT ... ON CONFLICT DO UPDATE``). The returned count is the
    number of entries processed (one write each), which under normal operation
    equals ``len(rows)``.
    """
    if not rows:
        return 0

    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                for r in rows:
                    abbr = r.team_abbr
                    desc = r.description
                    # 1) twin lookup: same date+abbr, space-agnostic description
                    cur.execute(
                        """
                        SELECT id
                        FROM transactions
                        WHERE transaction_date = %s
                          AND team_abbr = %s
                          AND REPLACE(description, ' ', '') = REPLACE(%s, ' ', '')
                        LIMIT 1
                        """,
                        (r.transaction_date, abbr, desc),
                    )
                    twin = cur.fetchone()
                    if twin is not None:
                        # repair the legacy/space-less twin in place
                        cur.execute(
                            """
                            UPDATE transactions
                            SET description = %s,
                                transaction_type = COALESCE(%s, transaction_type),
                                source = %s,
                                crawl_date = CURRENT_DATE
                            WHERE id = %s
                            """,
                            (desc, r.transaction_type, _SOURCE, twin[0]),
                        )
                    else:
                        # clean insert (idempotent on the unique constraint)
                        cur.execute(
                            """
                            INSERT INTO transactions
                                (transaction_date, team_abbr, transaction_type, description, source)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (transaction_date, team_abbr, description)
                            DO UPDATE SET
                                transaction_type = EXCLUDED.transaction_type,
                                source = EXCLUDED.source,
                                crawl_date = CURRENT_DATE
                            """,
                            (r.transaction_date, abbr, r.transaction_type, desc, _SOURCE),
                        )
        return len(rows)
    finally:
        conn.close()
