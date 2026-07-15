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

防复发保障：``transactions.id`` 是 SERIAL（依赖 ``transactions_id_seq`` 默认
值），但历史数据若经 ``COPY`` 或显式 ``id`` 灌入后未同步该序列，会导致新
``INSERT`` 从较小的 id 分配并撞上已存在旧行的主键（``transactions_pkey``
冲突），使整批入库被 ``SKIP``。``upsert_transactions`` 在批量写入前会先调用
``_sync_id_sequence`` 将序列前进到 ``max(id)`` 之后，彻底规避该问题（不 ALTER
表、不加列）。
"""

from __future__ import annotations

import logging
from typing import List

from .config import get_conn
from .parse import TxnEntry

logger = logging.getLogger(__name__)

_SOURCE = "basketball-reference"

# 与 transactions.id 绑定的序列名（SERIAL 默认按 ``{table}_{col}_seq`` 命名）。
_ID_SEQUENCE = "transactions_id_seq"


def _sync_id_sequence(cur) -> None:
    """同步 ``transactions_id_seq`` 使其不小于当前 ``max(id)``。

    在批量写入前（事务内、循环外）调用一次即可，避免逐行重复同步。

    根因：当表经 ``COPY`` 或显式指定 ``id`` 灌入历史数据后，若没有同步序列，
    序列的 ``last_value`` 仍停留在旧值（远小于 ``max(id)``）。随后新
    ``INSERT`` 走默认值 ``nextval('transactions_id_seq')`` 会从过小的 id 分配，
    撞上已存在的旧行主键，触发 ``duplicate key violates unique constraint
    "transactions_pkey"``，导致整批 ``SKIP``、数据无法入库。

    语义：``setval(seq, GREATEST(COALESCE(max(id), 1)), true)`` 中第三个参数
    ``is_called=true`` 表示“该值已被调用过”，因此下一次 ``nextval`` 返回
    ``max(id) + 1``（而非 ``max(id)`` 本身），从而与既有最大主键安全错开。
    若表为空或 ``max(id)`` 为 NULL，则回退到 1。若序列当前已领先于 ``max(id)``，
    此处将其回退到 ``max(id)`` 也安全——因为没有任何已存在行的 id 大于
    ``max(id)``，下一次 ``nextval`` 仍不会冲突。

    Args:
        cur: 当前事务内的 psycopg2 cursor（与批量写入共用同一事务）。
    """
    cur.execute(
        """
        SELECT setval(
            %s,
            GREATEST(COALESCE((SELECT max(id) FROM transactions), 1)),
            true
        )
        """,
        (_ID_SEQUENCE,),
    )
    logger.debug("已同步序列 %s 至 max(id) 之后", _ID_SEQUENCE)


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
                # 防御性序列同步：批量写入前确保 transactions_id_seq 不落后
                # 于当前 max(id)。历史数据若经 COPY / 显式指定 id 灌入而未同步
                # 序列，会导致新 INSERT 从 id=1 分配并撞上旧行主键（pkey 冲突、
                # 整批 SKIP）。此处一次性同步即可根治，不必逐行调用。
                _sync_id_sequence(cur)
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
