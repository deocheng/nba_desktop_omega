"""NBACore v8 §6 — Video Library designated writer + read helpers.

Mirrors ``import_engine.import_db``: this module is the *only* place in the
video library feature that imports psycopg2 for writes. The API/router layer
never touches psycopg2 directly (v8 §2 / §5.5).

v8 §6 compliance:
    - Dedicated ``ThreadedConnectionPool`` for game_videos DML (writes only).
    - All writes are parameterized (``%s`` placeholders, no dynamic SQL).
    - All reads (dim_games / game_videos SELECT) go through ``core.db.batch_query``
      (SELECT-only validated).
    - No eval()/exec(); per-row failures in bulk import are caught and reported.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from backend.core import config
from backend.core import db as core_db

logger = logging.getLogger("nbacore.services.video_library_engine")

_pool: ThreadedConnectionPool | None = None


# ── Dedicated write pool (v8 §2 / §6 designated writer) ──

def init_pool() -> None:
    """Lazily initialize the dedicated video_library write pool (1-10 conns)."""
    global _pool
    if _pool is not None:
        return
    _pool = ThreadedConnectionPool(1, 10, **config.DB_CONFIG, cursor_factory=RealDictCursor)
    logger.info("video_library_engine write pool initialized")


def close_pool() -> None:
    """Close all connections in the dedicated write pool."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("video_library_engine write pool closed")


def _conn():
    """Borrow a connection from the dedicated write pool."""
    if _pool is None:
        init_pool()
    assert _pool is not None
    return _pool.getconn()


def _put(conn) -> None:
    """Return a connection to the dedicated write pool."""
    if _pool is not None:
        _pool.putconn(conn)


# ── Write path: game_videos UPSERT / DELETE / BULK ──

def upsert_video_source(
    gameid: str,
    season: str,
    source: str,
    video_url: Optional[str],
    local_path: Optional[str],
    video_offset_seconds: float,
) -> Dict[str, Any]:
    """Insert or update a game_videos row (UPSERT on (gameid, season)).

    All values are bound via parameterized ``%s`` placeholders. Returns the
    resulting row as a dict.
    """
    sql = """
        INSERT INTO game_videos (gameid, season, source, video_url, local_path, video_offset_seconds)
        VALUES (%s, %s::integer, %s, %s, %s, %s)
        ON CONFLICT (gameid, season) DO UPDATE SET
            source = EXCLUDED.source,
            video_url = EXCLUDED.video_url,
            local_path = EXCLUDED.local_path,
            video_offset_seconds = EXCLUDED.video_offset_seconds
        RETURNING id, gameid, season, source, video_url, local_path,
                  video_offset_seconds, created_at
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (
                str(gameid),
                int(season),
                source,
                video_url,
                local_path,
                float(video_offset_seconds),
            ))
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else {}
    except Exception:
        conn.rollback()
        raise
    finally:
        _put(conn)


def delete_video_source(gameid: str, season: str) -> int:
    """Delete the game_videos row for (gameid, season). Returns deleted count."""
    sql = "DELETE FROM game_videos WHERE gameid = %s AND season = %s::integer"
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (str(gameid), int(season)))
            deleted = cur.rowcount
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        _put(conn)


def bulk_import(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Batch UPSERT video sources. Per-row failures are caught and reported.

    Args:
        items: List of dicts with keys matching UpsertVideoSourceRequest fields.

    Returns:
        Dict with ``inserted``, ``updated``, ``rejected`` keys.
    """
    inserted = 0
    updated = 0
    rejected: List[Dict[str, Any]] = []

    # Validate gameids exist in dim_games before writing (batch SELECT).
    gameids = list({it["gameid"] for it in items})
    valid_ids = _validate_gameids(gameids, items[0]["season"] if items else "")
    valid_set = set(valid_ids)

    conn = _conn()
    try:
        with conn.cursor() as cur:
            for idx, item in enumerate(items):
                gid = item.get("gameid", "")
                season = item.get("season", "")
                if gid not in valid_set:
                    rejected.append({
                        "row": idx,
                        "gameid": gid,
                        "reason": f"gameid '{gid}' not found in dim_games for season {season}",
                    })
                    continue
                try:
                    # RETURNING (xmax = 0) distinguishes INSERT (true) from
                    # UPDATE (false) in PostgreSQL's ON CONFLICT DO UPDATE.
                    # Per-row commit isolates failures so a single bad row
                    # does not roll back previously committed rows.
                    cur.execute(
                        """
                        INSERT INTO game_videos
                            (gameid, season, source, video_url, local_path, video_offset_seconds)
                        VALUES (%s, %s::integer, %s, %s, %s, %s)
                        ON CONFLICT (gameid, season) DO UPDATE SET
                            source = EXCLUDED.source,
                            video_url = EXCLUDED.video_url,
                            local_path = EXCLUDED.local_path,
                            video_offset_seconds = EXCLUDED.video_offset_seconds
                        RETURNING (xmax = 0) AS was_inserted
                        """,
                        (
                            str(gid),
                            int(season),
                            item.get("source", "other"),
                            item.get("video_url"),
                            item.get("local_path"),
                            float(item.get("video_offset_seconds", 0.0)),
                        ),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    if row and row.get("was_inserted"):
                        inserted += 1
                    else:
                        updated += 1
                except Exception as exc:
                    conn.rollback()
                    rejected.append({
                        "row": idx,
                        "gameid": gid,
                        "reason": str(exc),
                    })
                    continue
    except Exception:
        conn.rollback()
        raise
    finally:
        _put(conn)

    return {
        "inserted": inserted,
        "updated": updated,
        "rejected": rejected,
    }


# ── Read path: game_videos (via core.db.batch_query, SELECT-only) ──

def get_video_source(gameid: str, season: str) -> Optional[Dict[str, Any]]:
    """Read a single game_videos row for (gameid, season). Returns None if absent."""
    sql = """
        SELECT id, gameid, season, source, video_url, local_path,
               video_offset_seconds, created_at
        FROM game_videos
        WHERE gameid = %s AND season = %s::integer
    """
    rows = core_db.batch_query(sql, (str(gameid), int(season)))
    return rows[0] if rows else None


def get_video_source_by_id(media_id: int) -> Optional[Dict[str, Any]]:
    """Read a single game_videos row by primary key ``id`` (for media endpoint)."""
    sql = """
        SELECT id, gameid, season, source, video_url, local_path,
               video_offset_seconds, created_at
        FROM game_videos
        WHERE id = %s
    """
    rows = core_db.batch_query(sql, (int(media_id),))
    return rows[0] if rows else None


def list_games_with_flag(
    season: Optional[str] = None,
    team: Optional[str] = None,
    date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List games from dim_games LEFT JOIN game_videos (has_video badge).

    Uses ``core.db.batch_query`` (SELECT-only). Filters are applied via
    parameterized WHERE clauses. No dynamic SQL — column names are hardcoded.
    """
    clauses: List[str] = []
    params: List[Any] = []

    if season:
        clauses.append("g.season = %s::integer")
        params.append(int(season))
    if team:
        clauses.append("(g.home_team_abbr = %s OR g.away_team_abbr = %s)")
        params.extend([team, team])
    if date:
        clauses.append("g.game_date = %s::date")
        params.append(date)

    where = " AND ".join(clauses) if clauses else "TRUE"

    sql = f"""
        SELECT g.game_id,
               g.season,
               g.game_date,
               g.home_team_abbr,
               g.away_team_abbr,
               g.home_pts,
               g.away_pts,
               gv.source AS video_source,
               gv.id AS video_id
        FROM dim_games g
        LEFT JOIN game_videos gv ON gv.gameid = g.game_id AND gv.season = g.season
        WHERE {where}
        ORDER BY g.game_date DESC NULLS LAST, g.game_id
        LIMIT 500
    """
    return core_db.batch_query(sql, tuple(params) if params else ())


def _validate_gameids(gameids: List[str], season: str) -> List[str]:
    """Check which gameids exist in dim_games for the given season."""
    if not gameids:
        return []
    # Use batch_query with ANY array (SELECT-only, parameterized)
    sql = """
        SELECT game_id FROM dim_games
        WHERE season = %s::integer AND game_id = ANY(%s)
    """
    rows = core_db.batch_query(sql, (int(season), list(gameids)))
    return [r["game_id"] for r in rows]
