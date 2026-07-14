"""NBACore v8 §6 — Draft history data-quality writer (DESIGNATED WRITER, A1).

Holds every draft_picks / dim_draft_history mutation behind parameterized SQL:
  - ``snapshot_draft_history``  — T-A1-1 baseline backup (CREATE TABLE ... AS SELECT)
  - ``audit_draft_history_diffs`` — T-A1-1 list the 376 historical diff rows
  - ``export_audit_csv``        — T-A1-1 write the audit CSV
  - ``ensure_corrections_table``/``bulk_insert_corrections`` — A1-2 mapping store
  - ``apply_corrections`` / ``rollback_to_orig`` — A1-3 apply (round 2; dry-run safe)

All identifiers are bound with psycopg2.sql.Identifier; all values via %s.
The base table is ``dim_draft_history``; ``draft_picks`` is a VIEW over it, so
correcting the base table instantly reflects in the view. ``player_id_orig`` is
preserved on every update as the rollback anchor.
"""
from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from typing import Any, Iterable

from psycopg2 import sql as psql
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from backend.core import config

logger = logging.getLogger("nbacore.data.draft_quality")

_BASE_TABLE = "dim_draft_history"
_CORRECTIONS_TABLE = "draft_pick_corrections"
_DATE_RE = re.compile(r"^\d{8}$")

_pool: ThreadedConnectionPool | None = None


def init_pool() -> None:
    """Lazily initialize the dedicated draft-quality write pool (1-10)."""
    global _pool
    if _pool is not None:
        return
    _pool = ThreadedConnectionPool(1, 10, **config.DB_CONFIG, cursor_factory=RealDictCursor)
    logger.info("draft_quality write pool initialized")


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


# ── T-A1-1: snapshot + audit ──

def snapshot_draft_history(date_str: str | None = None) -> str:
    """Create a baseline backup of dim_draft_history.

    Table name: ``dim_draft_history_bak_YYYYMMDD`` (date validated, no
    injection). Idempotent-ish: if the backup already exists we skip and return
    its name (we never DROP/overwrite a prior snapshot).

    Args:
        date_str: ``YYYYMMDD``; defaults to today (local).

    Returns:
        str: the backup table name.
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    if not _DATE_RE.match(date_str):
        raise ValueError(f"snapshot_draft_history: date_str must be YYYYMMDD, got {date_str!r}")
    bak = f"{_BASE_TABLE}_bak_{date_str}"
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "SELECT to_regclass(%s) AS exists"
                ),
                (f"public.{bak}",),
            )
            exists = cur.fetchone()["exists"]
            if exists:
                logger.info("snapshot_draft_history: %s already exists, skip", bak)
                return bak
            cur.execute(
                psql.SQL(
                    "CREATE TABLE {bak} AS SELECT * FROM {base}"
                ).format(bak=psql.Identifier(bak), base=psql.Identifier(_BASE_TABLE))
            )
        conn.commit()
        logger.info("snapshot_draft_history: created %s", bak)
        return bak
    finally:
        _put(conn)


def audit_draft_history_diffs() -> list[dict]:
    """Return all dim_draft_history rows where player_id != player_id_orig.

    These are the 376 historical corrections (user decision A5) that must be
    re-verified before any further change. Read-only SELECT.
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "SELECT * FROM {base} "
                    "WHERE player_id IS DISTINCT FROM player_id_orig "
                    "ORDER BY season, player_id"
                ).format(base=psql.Identifier(_BASE_TABLE))
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        _put(conn)


def export_audit_csv(rows: Iterable[dict], path: str) -> int:
    """Write the audit rows to a CSV (T-A1-1 deliverable).

    Returns the number of rows written.
    """
    rows = list(rows)
    if not rows:
        logger.warning("export_audit_csv: no rows to write -> %s", path)
        return 0
    cols = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    logger.info("export_audit_csv: wrote %d rows -> %s", len(rows), path)
    return len(rows)


# ── A1-2: corrections mapping store ──

def ensure_corrections_table() -> None:
    """Create draft_pick_corrections if absent (idempotent)."""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "CREATE TABLE IF NOT EXISTS {tbl} ("
                    "  wrong_id TEXT,"
                    "  correct_id TEXT,"
                    "  status TEXT,"
                    "  page_name TEXT,"
                    "  evidence TEXT,"
                    "  confidence REAL,"
                    "  verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                    ")"
                ).format(tbl=psql.Identifier(_CORRECTIONS_TABLE))
            )
        conn.commit()
        logger.info("ensure_corrections_table: ready (%s)", _CORRECTIONS_TABLE)
    finally:
        _put(conn)


def existing_wrong_ids() -> set[str]:
    """Return wrong_ids already stored in draft_pick_corrections (for resume)."""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL("SELECT wrong_id FROM {tbl}").format(
                    tbl=psql.Identifier(_CORRECTIONS_TABLE)
                )
            )
            return {r["wrong_id"] for r in cur.fetchall()}
    finally:
        _put(conn)


def bulk_insert_corrections(rows: list[dict]) -> int:
    """Insert verified correction rows (idempotent: skips existing wrong_ids).

    Each row: wrong_id, correct_id, status, page_name, evidence, confidence.
    Returns number of newly inserted rows.
    """
    if not rows:
        return 0
    done = existing_wrong_ids()
    fresh = [r for r in rows if r.get("wrong_id") not in done]
    if not fresh:
        logger.info("bulk_insert_corrections: all %d already present, skip", len(rows))
        return 0
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                psql.SQL(
                    "INSERT INTO {tbl} "
                    "(wrong_id, correct_id, status, page_name, evidence, confidence) "
                    "VALUES (%s, %s, %s, %s, %s, %s)"
                ).format(tbl=psql.Identifier(_CORRECTIONS_TABLE)),
                [
                    (
                        r.get("wrong_id"),
                        r.get("correct_id"),
                        r.get("status"),
                        r.get("page_name"),
                        r.get("evidence"),
                        r.get("confidence"),
                    )
                    for r in fresh
                ],
            )
        conn.commit()
        logger.info("bulk_insert_corrections: inserted %d new rows", len(fresh))
        return len(fresh)
    finally:
        _put(conn)


def clear_corrections_by_status(status: str) -> int:
    """Delete all correction rows of a given status (parameterized, §6 safe).

    Used by the A1-3 exists_match loader to keep the audit store free of
    per-season duplicate rows (a player verified across several draft seasons
    collapses to one unique wrong_id). Returns the number of deleted rows.
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL("DELETE FROM {tbl} WHERE status = %s").format(
                    tbl=psql.Identifier(_CORRECTIONS_TABLE)
                ),
                (status,),
            )
            n = cur.rowcount
        conn.commit()
        logger.info("clear_corrections_by_status: deleted %d rows (status=%s)", n, status)
        return n
    finally:
        _put(conn)


# ── A1-3: apply / rollback (round 2; dry-run safe) ──

def _planned_updates(where_sql: "psql.Composed", params: tuple) -> int:
    """Count rows a correction UPDATE would touch (dry-run helper)."""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "SELECT COUNT(*) AS n FROM {base} WHERE {where}"
                ).format(base=psql.Identifier(_BASE_TABLE), where=where_sql),
                params,
            )
            return cur.fetchone()["n"]
    finally:
        _put(conn)


def apply_corrections(min_confidence: float = 0.8, dry_run: bool = True) -> dict:
    """Apply high-confidence corrections where a correct_id is known.

    UPDATE dim_draft_history SET player_id = correct_id
    WHERE player_id = wrong_id AND player_id IS DISTINCT FROM player_id_orig
    AND (wrong_id, correct_id) came from draft_pick_corrections with
    confidence >= min_confidence and correct_id IS NOT NULL.

    ``player_id_orig`` is preserved (rollback anchor). High-confidence
    ``exists_match`` rows already have correct_id == player_id (no-op).
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "SELECT wrong_id, correct_id FROM {tbl} "
                    "WHERE correct_id IS NOT NULL AND confidence >= %s"
                ).format(tbl=psql.Identifier(_CORRECTIONS_TABLE)),
                (min_confidence,),
            )
            pairs = [(r["wrong_id"], r["correct_id"]) for r in cur.fetchall()]
        planned = 0
        for wrong_id, correct_id in pairs:
            # Only count rows whose value would actually change. For high-confidence
            # exists_match rows correct_id == player_id, so this resolves to a true
            # no-op (matches the module docstring: "exists_match rows already have
            # correct_id == player_id (no-op)") and avoids pointless rewrites.
            where = psql.SQL(
                "player_id = %s AND player_id IS DISTINCT FROM player_id_orig "
                "AND player_id IS DISTINCT FROM %s"
            )
            planned += _planned_updates(where, (wrong_id, correct_id))
        if dry_run or not pairs:
            logger.info("apply_corrections: dry_run=%s planned=%d", dry_run, planned)
            return {"dry_run": dry_run, "planned": planned, "pairs": len(pairs)}
        # Execute
        executed = 0
        for wrong_id, correct_id in pairs:
            with conn.cursor() as cur:
                # Same value-change guard as the planned count: never rewrite a
                # column to its current value. Identifiers via sql.Identifier,
                # values via %s — §6 compliant, no dynamic SQL.
                cur.execute(
                    psql.SQL(
                        "UPDATE {base} SET player_id = %s "
                        "WHERE player_id = %s AND player_id IS DISTINCT FROM player_id_orig "
                        "AND player_id IS DISTINCT FROM %s"
                    ).format(base=psql.Identifier(_BASE_TABLE)),
                    (correct_id, wrong_id, correct_id),
                )
                executed += cur.rowcount
        conn.commit()
        logger.info("apply_corrections: executed updates=%d", executed)
        return {"dry_run": False, "planned": planned, "updated": executed, "pairs": len(pairs)}
    finally:
        _put(conn)


def rollback_to_orig(min_confidence: float = 0.8, dry_run: bool = True) -> dict:
    """Roll back high-confidence *wrong* historical corrections to player_id_orig.

    For draft_pick_corrections rows with status='mismatch' (BR confirms the id
    points at the wrong real player) and confidence >= min_confidence, revert
    dim_draft_history.player_id to player_id_orig.
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "SELECT wrong_id FROM {tbl} "
                    "WHERE status = 'mismatch' AND confidence >= %s"
                ).format(tbl=psql.Identifier(_CORRECTIONS_TABLE)),
                (min_confidence,),
            )
            wrong_ids = [r["wrong_id"] for r in cur.fetchall()]
        planned = 0
        for wid in wrong_ids:
            where = psql.SQL(
                "player_id = %s AND player_id IS DISTINCT FROM player_id_orig"
            )
            planned += _planned_updates(where, (wid,))
        if dry_run or not wrong_ids:
            logger.info("rollback_to_orig: dry_run=%s planned=%d", dry_run, planned)
            return {"dry_run": dry_run, "planned": planned, "wrong_ids": len(wrong_ids)}
        executed = 0
        for wid in wrong_ids:
            with conn.cursor() as cur:
                cur.execute(
                    psql.SQL(
                        "UPDATE {base} SET player_id = player_id_orig "
                        "WHERE player_id = %s AND player_id IS DISTINCT FROM player_id_orig"
                    ).format(base=psql.Identifier(_BASE_TABLE)),
                    (wid,),
                )
                executed += cur.rowcount
        conn.commit()
        logger.info("rollback_to_orig: executed updates=%d", executed)
        return {"dry_run": False, "planned": planned, "updated": executed, "wrong_ids": len(wrong_ids)}
    finally:
        _put(conn)
