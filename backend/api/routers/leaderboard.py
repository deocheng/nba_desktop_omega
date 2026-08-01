"""NBACore v8 §2 Layer 3 — /leaderboard router (pure orchestration).

Multi-dimensional player leaderboards.
All data fetched via data_layer. Sort whitelist validated at API layer
as defense-in-depth (data_layer also validates).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query

from backend.data_layer import get_player_advanced, get_player_per_game
from backend.services.metric_engine import get_player_bios

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])

# ── Whitelists (defense-in-depth; data_layer also validates) ──
_PER_GAME_SORTS = frozenset({
    "pts", "reb", "ast", "stl", "blk", "tov",
    "fg_pct", "fg3_pct", "ft_pct", "mp",
})

_ADVANCED_SORTS = frozenset({
    "per", "ts_pct", "usg_pct", "bpm", "vorp", "ws", "mp",
})

# API sort key → data_layer internal sort key mapping for advanced
_ADVANCED_SORT_MAP = {
    "per": "per",
    "ts_pct": "ts_percent",
    "usg_pct": "usg_percent",
    "bpm": "bpm",
    "vorp": "vorp",
    "ws": "ws",
    "mp": "mp",
}

_VALID_STAT_TYPES = frozenset({"per_game", "totals", "advanced"})


@router.get("/{stat_type}")
def leaderboard(
    stat_type: str = Path(..., description="Stat type: per_game, totals, advanced"),
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    limit: int = Query(50, ge=1, le=200, description="Max players to return"),
    sort: str = Query("pts", description="Sort column"),
) -> dict:
    """Multi-dimensional player leaderboard.

    stat_type:
        - per_game: Per-game basic stats (pts, reb, ast, stl, blk, etc.)
        - totals: Not yet available (returns 400)
        - advanced: Advanced metrics (per, ts_pct, usg_pct, bpm, vorp, ws)
    """
    if stat_type not in _VALID_STAT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stat_type '{stat_type}'. Valid: per_game, totals, advanced",
        )

    if stat_type == "totals":
        raise HTTPException(
            status_code=400,
            detail="totals stat_type is not yet available. Use per_game or advanced.",
        )

    sort_key = sort.lower().strip()

    try:
        if stat_type == "per_game":
            if sort_key not in _PER_GAME_SORTS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid sort '{sort}' for {stat_type}. Valid: {', '.join(sorted(_PER_GAME_SORTS))}",
                )
            rows = get_player_per_game(season=season, limit=limit, sort_by=sort_key)
        else:
            if sort_key not in _ADVANCED_SORTS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid sort '{sort}' for advanced. Valid: {', '.join(sorted(_ADVANCED_SORTS))}",
                )
            dl_sort = _ADVANCED_SORT_MAP.get(sort_key, sort_key)
            rows = get_player_advanced(season=season, limit=limit, sort_by=dl_sort)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"leaderboard fetch failed: {exc}")

    # 增量：附上本地头像（headshot_path/headshot_status），复用 player_bio 视图。
    # 仅做最小 SELECT 扩展语义的等价实现，不改变排序/分页逻辑。
    _ids = [r.get("player_id") for r in rows if r.get("player_id")]
    _bios = {b["player_id"]: b for b in (get_player_bios(_ids) if _ids else [])}
    for r in rows:
        _b = _bios.get(r.get("player_id"), {})
        r["headshot_path"] = _b.get("headshot_path")
        r["headshot_status"] = _b.get("headshot_status")

    return {
        "leaderboard": rows,
        "stat_type": stat_type,
        "sort": sort_key,
        "season": season,
    }
