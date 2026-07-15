"""Live-DB verification of the ``transactions_id_seq`` desync fix.

The offline test (``test_load_offline.py``) only checks the *text* of the SQL
via a fake cursor — it never executes anything. This test proves the fix
end-to-end against a real PostgreSQL: when ``transactions_id_seq`` lags behind
``max(id)`` (the historical batch-SKIP bug), ``upsert_transactions`` must NOT
raise ``duplicate key violates unique constraint "transactions_pkey"`` and must
correctly insert new rows whose ids are safely above the existing max, while
re-running the same rows is a no-op (idempotent).

SAFETY — we never touch production data:
  * ``load.get_conn`` is redirected to a throwaway schema ``qa_txn_seqtest``
    that owns its own ``transactions`` table and its own ``transactions_id_seq``
    sequence.
  * The connection's ``search_path`` is set to THAT schema ONLY (``pg_catalog``
    stays implicitly first), so every unqualified reference to ``transactions``
    / ``transactions_id_seq`` resolves inside the sandbox — never ``public``.
  * The schema is dropped in fixture teardown, so nothing is left behind.

Requires a live DB; skips cleanly otherwise (so offline CI stays green).

Run from the repo root:
    python -m pytest transactions_crawl/tests/test_load_seqsync_live.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hof_exec.config import get_conn  # real connection factory
import transactions_crawl.load as load_mod
from transactions_crawl.parse import TxnEntry

TEST_SCHEMA = "qa_txn_seqtest"


def _live_db_available() -> bool:
    try:
        c = get_conn()
    except Exception:
        return False
    try:
        with c.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    finally:
        c.close()


pytestmark = pytest.mark.skipif(
    not _live_db_available(), reason="no live DB available"
)


@pytest.fixture
def isolated_txn_schema(monkeypatch):
    """Create a throwaway schema (own table + own sequence) and redirect
    ``load.get_conn`` to a connection scoped to that schema only."""
    admin = get_conn()
    try:
        with admin:
            with admin.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
                cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
                cur.execute(
                    f"""
                    CREATE TABLE {TEST_SCHEMA}.transactions (
                        id SERIAL PRIMARY KEY,
                        transaction_date DATE NOT NULL,
                        team_abbr TEXT,
                        transaction_type TEXT,
                        description TEXT NOT NULL,
                        source TEXT DEFAULT 'basketball-reference',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        crawl_date DATE DEFAULT CURRENT_DATE
                    )
                    """
                )
                # Mirror the production unique constraint that the
                # ON CONFLICT (transaction_date, team_abbr, description) clause
                # relies on (transactions_transaction_date_team_abbr_description_key).
                cur.execute(
                    f"CREATE UNIQUE INDEX transactions_date_abbr_desc_key "
                    f"ON {TEST_SCHEMA}.transactions (transaction_date, team_abbr, description)"
                )
    finally:
        admin.close()

    def _patched_get_conn():
        # Fresh real connection, but confined to the sandbox schema only.
        conn = get_conn()
        with conn.cursor() as cur:
            # pg_catalog stays implicitly first; 'public' is intentionally excluded.
            cur.execute(f"SET search_path TO {TEST_SCHEMA}, pg_catalog")
        conn.commit()  # persist session GUC; avoid a dangling open txn
        return conn

    monkeypatch.setattr(load_mod, "get_conn", _patched_get_conn)

    yield

    cleanup = get_conn()
    try:
        with cleanup:
            with cleanup.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
    finally:
        cleanup.close()


def _seed_old_row_and_desync(high_id: int = 26242, seq_at: int = 14) -> None:
    """Insert legacy rows, then desync the sequence far behind ``max(id)``.

    We seed TWO legacy rows to faithfully reproduce the historical SKIP bug:
      * a high-id row (``high_id`` == 26242) — the table's true ``max(id)``;
      * a low-id row at ``seq_at + 1`` (== 15) — representing the bulk of the
        historically COPY-loaded rows that already occupy the low ids.
    The sequence is then reset to ``seq_at`` (14), so its next ``nextval``
    returns 15 and COLLIDES with the seeded low-id row — exactly the
    ``duplicate key violates unique constraint "transactions_pkey"`` that
    caused the batch to be SKIPped. With the fix, the sequence is advanced
    past ``max(id)`` before any insert, so the collision never happens.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {TEST_SCHEMA}, pg_catalog")
            cur.execute(
                f"INSERT INTO transactions (id, transaction_date, team_abbr, "
                f"transaction_type, description, source) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    high_id,
                    "2025-07-07",
                    "DET",
                    "signed",
                    "The Detroit Pistons signed Paul Reed to a multi-year contract.",
                    "basketball-reference",
                ),
            )
            cur.execute(
                f"INSERT INTO transactions (id, transaction_date, team_abbr, "
                f"transaction_type, description, source) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    seq_at + 1,  # 15 — the id the desynced sequence will emit
                    "2025-07-06",
                    "DET",
                    "signed",
                    "The Detroit Pistons signed Legacy Low Id Player.",
                    "basketball-reference",
                ),
            )
            # The historical desync: sequence last_value << max(id).
            cur.execute(f"SELECT setval('transactions_id_seq', %s, true)", (seq_at,))
        conn.commit()
    finally:
        conn.close()


def test_seq_sync_prevents_pkey_conflict(isolated_txn_schema):
    """Sequence behind max(id): upsert must NOT raise pkey conflict and must
    assign new ids above the existing max."""
    _seed_old_row_and_desync()

    rows = [
        TxnEntry(
            transaction_date="2025-07-08",
            team_abbr="DET",
            transaction_type="signed",
            description="The Detroit Pistons signed Caris LeVert to a multi-year contract.",
        ),
        TxnEntry(
            transaction_date="2025-07-09",
            team_abbr="DET",
            transaction_type="waived",
            description="The Detroit Pistons waived Player X.",
        ),
    ]
    # This is the assertion that proves the fix: no duplicate-key error.
    written = load_mod.upsert_transactions(rows)
    assert written == len(rows)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {TEST_SCHEMA}, pg_catalog")
            cur.execute("SELECT max(id), count(*) FROM transactions")
            mx, cnt = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    assert mx is not None and mx > 26242, (
        "new id must be above existing max to avoid pkey clash"
    )
    assert cnt == 4, "expected 2 seeded (low-id + high-id) + 2 new rows"


def test_idempotent_rerun_is_noop(isolated_txn_schema):
    """Re-running the same rows must be a no-op (ON CONFLICT DO UPDATE)."""
    _seed_old_row_and_desync()

    rows = [
        TxnEntry(
            transaction_date="2025-07-10",
            team_abbr="DET",
            transaction_type="signed",
            description="The Detroit Pistons signed Player Y to a contract.",
        )
    ]
    assert load_mod.upsert_transactions(rows) == 1
    # second run with identical data -> still idempotent, no duplicate
    assert load_mod.upsert_transactions(rows) == 1

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {TEST_SCHEMA}, pg_catalog")
            cur.execute(
                "SELECT count(*) FROM transactions WHERE description = %s",
                ("The Detroit Pistons signed Player Y to a contract.",),
            )
            n = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    assert n == 1, "re-running the same row must not create a duplicate"


def test_twin_repair_still_works(isolated_txn_schema):
    """The legacy space-less twin must still be repaired in place by UPDATE
    (pre-existing invariant must survive the sequence-sync change)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {TEST_SCHEMA}, pg_catalog")
            cur.execute(
                f"INSERT INTO transactions (transaction_date, team_abbr, "
                f"transaction_type, description, source) VALUES (%s, %s, %s, %s, %s)",
                (
                    "2025-07-11",
                    "DET",
                    "signed",
                    "TheDetroit PistonssignedMichael Curryas a free agent.",
                    "basketball-reference",
                ),
            )
            cur.execute(f"SELECT setval('transactions_id_seq', 1, true)")
        conn.commit()
    finally:
        conn.close()

    rows = [
        TxnEntry(
            transaction_date="2025-07-11",
            team_abbr="DET",
            transaction_type="signed",
            description="The Detroit Pistons signed Michael Curry as a free agent.",
        )
    ]
    assert load_mod.upsert_transactions(rows) == 1

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {TEST_SCHEMA}, pg_catalog")
            cur.execute(
                "SELECT description, count(*) FROM transactions "
                "WHERE transaction_date = %s AND team_abbr = %s GROUP BY description",
                ("2025-07-11", "DET"),
            )
            rows_out = cur.fetchall()
        conn.commit()
    finally:
        conn.close()

    assert len(rows_out) == 1, "twin must be repaired in place, not duplicated"
    assert rows_out[0][0] == (
        "The Detroit Pistons signed Michael Curry as a free agent."
    ), "twin description must be repaired to the space-correct form"
