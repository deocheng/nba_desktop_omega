"""NBACore v8 — AI 交易语义解析：trade_semantics 写层（§6 唯一含 SQL 的模块）。

架构约束（v8 §6 四层隔离）：
- 本模块是 trade_semantics 表的 **唯一** 读写收口点，所有 SQL 均为参数化常量。
- cba_aux_db / llm_provider 零 import psycopg2、零 SQL 子串；它们只调用本模块。
- 专用 psycopg2 连接池（范式同 workspace_db.py），DDL 幂等 CREATE TABLE IF NOT EXISTS。
- 无 eval/exec、无动态 SQL、无每球员循环。

配置：从 backend.core.config.DB_CONFIG 连接（键为 ``database``）。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from psycopg2.extras import Json, RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from backend.core import config

logger = logging.getLogger("nbacore.trade_semantics_db")

# ── 幂等 DDL（硬编码常量，非动态 SQL） ──
SQL_CREATE_TRADE_SEMANTICS = """
CREATE TABLE IF NOT EXISTS trade_semantics (
    id            SERIAL PRIMARY KEY,
    source_ref    TEXT NOT NULL UNIQUE,
    counterparties JSONB,
    players_out   JSONB,
    players_in    JSONB,
    picks         JSONB,
    cash          NUMERIC,
    notes         TEXT,
    model         TEXT,
    parsed_at     TIMESTAMP DEFAULT now()
);
"""

# jsonb 列名（读取时按需反序列化，避免全局注册影响既有连接）
_JSONB_FIELDS = ("counterparties", "players_out", "players_in", "picks")

_pool: Optional[ThreadedConnectionPool] = None
_schema_ready = False


def init_pool() -> None:
    """惰性初始化 trade_semantics 专用写连接池（1-5 连接）。"""
    global _pool
    if _pool is not None:
        return
    _pool = ThreadedConnectionPool(1, 5, **config.DB_CONFIG, cursor_factory=RealDictCursor)
    logger.info("trade_semantics_db pool initialized")


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("trade_semantics_db pool closed")


def ensure_schema() -> None:
    """幂等建表（memoized per process）。"""
    global _schema_ready
    if _schema_ready:
        return
    if _pool is None:
        init_pool()
    assert _pool is not None
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(SQL_CREATE_TRADE_SEMANTICS)
        conn.commit()
        _schema_ready = True
        logger.info("trade_semantics schema ensured")
    finally:
        _pool.putconn(conn)


def _conn():
    if _pool is None:
        init_pool()
    return _pool.getconn()


def _put(conn) -> None:
    _pool.putconn(conn)


def _coerce_jsonb(v: Any) -> Any:
    """将 jsonb 读取结果（可能 str 或已解析对象）规范化为 Python 对象。"""
    if v is None or isinstance(v, (list, dict)):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return v


def upsert_trade_semantics(source_ref: str, data: Dict[str, Any], model: str) -> None:
    """参数化 upsert（幂等：同 source_ref 覆盖，刷新 parsed_at）。"""
    ensure_schema()
    cash = data.get("cash")
    if cash is not None:
        try:
            cash = float(cash)
        except (TypeError, ValueError):
            cash = None
    sql = """
    INSERT INTO trade_semantics
        (source_ref, counterparties, players_out, players_in, picks, cash, notes, model)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (source_ref) DO UPDATE SET
        counterparties = EXCLUDED.counterparties,
        players_out    = EXCLUDED.players_out,
        players_in     = EXCLUDED.players_in,
        picks          = EXCLUDED.picks,
        cash           = EXCLUDED.cash,
        notes          = EXCLUDED.notes,
        model          = EXCLUDED.model,
        parsed_at      = now()
    """
    params = (
        source_ref,
        Json(data.get("counterparties") or []),
        Json(data.get("players_out") or []),
        Json(data.get("players_in") or []),
        Json(data.get("picks") or []),
        cash,
        data.get("notes") or "",
        model,
    )
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _put(conn)


def get_trade_semantics(source_ref: str) -> Optional[Dict[str, Any]]:
    """按 source_ref 读取一行；未命中返回 None。"""
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM trade_semantics WHERE source_ref = %s", (source_ref,)
            )
            row = cur.fetchone()
        if not row:
            return None
        rec = dict(row)
        for f in _JSONB_FIELDS:
            if f in rec:
                rec[f] = _coerce_jsonb(rec[f])
        if rec.get("cash") is not None:
            try:
                rec["cash"] = float(rec["cash"])
            except (TypeError, ValueError):
                pass
        return rec
    finally:
        _put(conn)


def exists_source_ref(source_ref: str) -> bool:
    """判断 source_ref 是否已落表（用于续跑跳过）。"""
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM trade_semantics WHERE source_ref = %s LIMIT 1",
                (source_ref,),
            )
            return cur.fetchone() is not None
    finally:
        _put(conn)


def delete_trade_semantics(source_ref: str) -> bool:
    """测试清理 / 管理用：按 source_ref 删除一行（写层内，§6 合规）。"""
    ensure_schema()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM trade_semantics WHERE source_ref = %s", (source_ref,)
            )
            n = cur.rowcount
        conn.commit()
        return n > 0
    finally:
        _put(conn)
