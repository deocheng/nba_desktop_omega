"""NBACore v8 §6 — Player weight write-path (DESIGNATED WRITER, A3).

Single home for every weight-related mutation:
  - ``upsert_player_weight``      — crawler落库 (idempotent ON CONFLICT DO UPDATE)
  - ``derive_weight_kg``          — backfill weight_kg = ROUND(weight_lbs*0.453592)
  - ``backfill_dim_players_null`` — best-effort fill of the 3 NULL weight rows
                                     (no-op if BR has no page; never hard-overwrites)

All DDL/UPDATE use psycopg2.sql.Identifier for table/column names and %s for
values — no raw string interpolation of identifiers (v8 §6 red line). This is
the module the crawler calls instead of embedding SQL in its own body.
"""
from __future__ import annotations

import logging
from typing import Any

from psycopg2 import sql as psql
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from backend.core import config

logger = logging.getLogger("nbacore.data.weight_writer")

# lbs -> kg conversion factor (BR convention)
LBS_TO_KG = 0.453592

_pool: ThreadedConnectionPool | None = None


def init_pool() -> None:
    """Lazily initialize the dedicated weight write pool (1-10 connections)."""
    global _pool
    if _pool is not None:
        return
    _pool = ThreadedConnectionPool(1, 10, **config.DB_CONFIG, cursor_factory=RealDictCursor)
    logger.info("weight_writer write pool initialized")


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


def _conn():
    if _pool is None:
        init_pool()
    assert _pool is not None
    return _pool.getconn()


def _put(conn) -> None:
    if _pool is not None:
        _pool.putconn(conn)


def _require_table(table: str, allowed: tuple[str, ...]) -> None:
    """Validate a weight-bearing table name against a trusted allowlist."""
    if table not in allowed:
        raise ValueError(f"weight_writer: table {table!r} not in allowed {allowed}")


# ── Crawler upsert (idempotent) ──

def upsert_player_weight(
    player_id: str,
    player_name: str | None,
    weight_lbs: int | None,
    weight_kg: int | None,
    height: str | None = None,
    born: str | None = None,
    position: str | None = None,
    shoots: str | None = None,
) -> None:
    """Idempotent upsert of one player's weight row into player_weight_history.

    Mirrors the crawler's prior ``save_player`` semantics (PK on player_id,
    ON CONFLICT DO UPDATE) so re-runs are safe. Called by the crawler via
    :func:`backend.data_layer.weight_writer.upsert_player_weight`.

    Args:
        player_id: BBR player id (PK).
        player_name: display name (best-effort; may be None on thin pages).
        weight_lbs / weight_kg: parsed weights (either may be None).
        height / born / position / shoots: optional bio fields.
    """
    table = "player_weight_history"
    _require_table(table, ("player_weight_history",))
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {tbl} "
                    "(player_id, player_name, weight_lbs, weight_kg, height, born, position, shoots) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (player_id) DO UPDATE SET "
                    "player_name = EXCLUDED.player_name, "
                    "weight_lbs = EXCLUDED.weight_lbs, "
                    "weight_kg = EXCLUDED.weight_kg, "
                    "height = EXCLUDED.height, "
                    "born = EXCLUDED.born, "
                    "position = EXCLUDED.position, "
                    "shoots = EXCLUDED.shoots, "
                    "scraped_at = CURRENT_TIMESTAMP"
                ).format(tbl=psql.Identifier(table)),
                (
                    player_id, player_name, weight_lbs, weight_kg,
                    height, born, position, shoots,
                ),
            )
        conn.commit()
    finally:
        _put(conn)


# ── Derived kg backfill (no BR needed) ──

def derive_weight_kg(table: str = "player_weight_history") -> int:
    """Backfill weight_kg from weight_lbs where kg is NULL.

    ``weight_kg = ROUND(weight_lbs * {LBS_TO_KG})`` — pure derivation, no
    network. Idempotent: only touches NULL-kg rows that have lbs.

    Args:
        table: target weight table (trusted allowlist).

    Returns:
        int: number of rows updated.
    """
    _require_table(table, ("player_weight_history", "dim_players"))
    kg_col = "weight_kg"
    lbs_col = "weight_lbs"
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "UPDATE {tbl} "
                    "SET {kg} = ROUND({lbs} * %s) "
                    "WHERE {kg} IS NULL AND {lbs} IS NOT NULL"
                ).format(
                    tbl=psql.Identifier(table),
                    kg=psql.Identifier(kg_col),
                    lbs=psql.Identifier(lbs_col),
                ),
                (LBS_TO_KG,),
            )
            updated = cur.rowcount
        conn.commit()
        logger.info("derive_weight_kg: %s -> updated %d rows", table, updated)
        return updated
    finally:
        _put(conn)


def backfill_dim_players_null(
    candidates: list[str] | None = None,
) -> int:
    """Best-effort fill of dim_players weight NULLs from player_weight_history.

    For the 3 known NULL rows (mitchmu01/wertira01/leedi01) we copy lbs/kg from
    player_weight_history when present. Rows with no BR page stay NULL (the
    crawler leaves them NULL) — this function only copies existing data, it
    never invents a weight.

    Args:
        candidates: optional subset of player_ids to attempt (defaults to all
            NULL-weight rows in dim_players).

    Returns:
        int: number of dim_players rows updated.
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            if candidates:
                cur.execute(
                    psql.SQL(
                        "UPDATE dim_players d SET "
                        "weight_lbs = h.weight_lbs, weight_kg = h.weight_kg "
                        "FROM player_weight_history h "
                        "WHERE d.player_id = h.player_id "
                        "AND d.weight_lbs IS NULL "
                        "AND d.player_id = ANY(%s) "
                        "AND h.weight_lbs IS NOT NULL"
                    ),
                    (candidates,),
                )
            else:
                cur.execute(
                    "UPDATE dim_players d SET "
                    "weight_lbs = h.weight_lbs, weight_kg = h.weight_kg "
                    "FROM player_weight_history h "
                    "WHERE d.player_id = h.player_id "
                    "AND d.weight_lbs IS NULL "
                    "AND h.weight_lbs IS NOT NULL"
                )
            updated = cur.rowcount
        conn.commit()
        logger.info("backfill_dim_players_null: updated %d rows", updated)
        return updated
    finally:
        _put(conn)


def weight_coverage(table: str = "dim_players") -> dict[str, Any]:
    """Return weight population stats for QA / monitoring."""
    _require_table(table, ("dim_players", "player_weight_history"))
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "SELECT COUNT(*) AS total, "
                    "COUNT(weight_lbs) AS with_lbs, "
                    "COUNT(weight_kg) AS with_kg "
                    "FROM {tbl}"
                ).format(tbl=psql.Identifier(table)),
            )
            row = cur.fetchone()
        return dict(row) if row else {}
    finally:
        _put(conn)
