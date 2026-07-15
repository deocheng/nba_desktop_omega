"""Offline tests for ``transactions_crawl.load`` (no real DB, mock psycopg2).

Verifies the defensive sequence-sync fix that prevents the
``duplicate key violates unique constraint "transactions_pkey"`` batch-SKIP
regression, without requiring a live database.

We monkeypatch ``transactions_crawl.load.get_conn`` with an in-memory fake
connection/cursor so we can inspect the exact SQL each routine executes.

Run from the repo root:
    python -m pytest transactions_crawl/tests -q
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

import pytest

from transactions_crawl import load as load_mod
from transactions_crawl.parse import TxnEntry


class FakeCursor:
    """Records executed SQL and lets us script fetchone() for the twin lookup."""

    def __init__(self, twin_id: Optional[int] = None) -> None:
        self.executed: List[Tuple[str, Tuple[Any, ...]]] = []
        self._twin_id = twin_id  # value returned by the twin SELECT's fetchone()

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> None:
        self.executed.append((sql, tuple(params)))

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        if self._twin_id is None:
            return None
        return (self._twin_id,)

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class FakeConn:
    """Minimal psycopg2 connection stand-in (``with conn`` commits, no-op)."""

    def __init__(self, twin_id: Optional[int] = None) -> None:
        self._twin_id = twin_id
        self.closed = False
        self._cursor: Optional[FakeCursor] = None

    def cursor(self) -> FakeCursor:
        self._cursor = FakeCursor(twin_id=self._twin_id)
        return self._cursor

    def __enter__(self) -> "FakeConn":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None  # commit/rollback is a no-op for the fake

    def close(self) -> None:
        self.closed = True


def _normalized(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_sync_id_sequence_generates_correct_setval(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_sync_id_sequence`` must run a setval(...) with is_called=true."""
    conn = FakeConn()
    cur = conn.cursor()
    monkeypatch.setattr(load_mod, "get_conn", lambda: conn)

    load_mod._sync_id_sequence(cur)

    assert len(cur.executed) == 1, "应仅执行一条 setval 语句"
    sql, params = cur.executed[0]
    norm = _normalized(sql)
    assert "setval" in norm
    # 序列名通过参数占位符传入，需匹配模块常量
    assert params == (load_mod._ID_SEQUENCE,)
    # 关键语义：GREATEST(COALESCE(max(id), 1))，且第三个参数 is_called=true
    assert "GREATEST" in norm and "COALESCE" in norm
    assert "max(id)" in norm
    # third positional arg of setval must be the literal boolean true
    assert re.search(r",\s*true\s*\)\s*$", norm), (
        "setval 必须带第三个参数 true（is_called=true），保证下次 nextval=max(id)+1"
    )


def test_upsert_calls_sync_before_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """``upsert_transactions`` 必须在任何写入前调用一次序列同步。"""
    conn = FakeConn()  # twin_id=None -> clean INSERT path
    monkeypatch.setattr(load_mod, "get_conn", lambda: conn)

    rows = [
        TxnEntry(
            transaction_date="2025-07-07",
            team_abbr="DET",
            transaction_type="signed",
            description="The Detroit Pistons signed Caris LeVert to a multi-year contract.",
        )
    ]
    written = load_mod.upsert_transactions(rows)
    assert written == 1

    # 第一条执行的语句必须是 _sync_id_sequence 的 setval
    first_sql, _ = conn._cursor.executed[0]
    assert "setval" in _normalized(first_sql), "同步序列必须是写入前第一条语句"

    # 后续语句保持既有孪生/插入逻辑不变：SELECT twin 然后 INSERT ... ON CONFLICT
    sqls = [_normalized(s) for s, _ in conn._cursor.executed]
    assert any("REPLACE(description" in s and "REPLACE(%s" in s for s in sqls), (
        "孪生去重（REPLACE 空格无关比较）逻辑应保持不变"
    )
    assert any(
        "INSERT INTO transactions" in s and "ON CONFLICT (transaction_date, team_abbr, description)" in s
        for s in sqls
    ), "幂等 INSERT ... ON CONFLICT DO UPDATE 逻辑应保持不变"


def test_upsert_twin_repair_path_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """存在孪生时走 UPDATE 修复路径，且序列同步仍先执行。"""
    conn = FakeConn(twin_id=10)  # 返回孪生 id=10 -> UPDATE 修复
    monkeypatch.setattr(load_mod, "get_conn", lambda: conn)

    rows = [
        TxnEntry(
            transaction_date="1995-01-01",
            team_abbr="ATL",
            transaction_type="signed",
            description="The Atlanta Hawks signed Someone to a contract.",
        )
    ]
    written = load_mod.upsert_transactions(rows)
    assert written == 1

    sqls = [_normalized(s) for s, _ in conn._cursor.executed]
    assert "setval" in sqls[0], "序列同步必须在前"
    assert any("UPDATE transactions" in s and "WHERE id = %s" in s for s in sqls), (
        "孪生存在时应走 UPDATE 修复路径"
    )
    # 孪生命中时不应再触发 INSERT
    assert not any("INSERT INTO transactions" in s for s in sqls)


def test_upsert_empty_rows_no_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """空列表不应连接/同步/写入。"""
    calls = {"get_conn": 0}

    def _fake_get_conn():
        calls["get_conn"] += 1
        return FakeConn()

    monkeypatch.setattr(load_mod, "get_conn", _fake_get_conn)
    assert load_mod.upsert_transactions([]) == 0
    assert calls["get_conn"] == 0, "空列表不应打开连接"
