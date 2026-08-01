"""NBACore v8 §2 Layer 3 — /draft router (pure orchestration, no SQL).

Serves draft_picks with weight (A2 JOIN-at-read) and an ``in_dim_players``
flag (A1-4) so the frontend can render "无资料" instead of a dead BR link.
No SQL / computation here — all data access goes through the data_layer.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from backend.data_layer.draft_loader import load_draft_picks_with_weight
from backend.services.metric_engine import get_player_bios

router = APIRouter(prefix="/draft", tags=["draft"])

# Default cap keeps the first paint light; the UI can page / filter by season.
_DEFAULT_LIMIT = 200
_MAX_LIMIT = 5000


@router.get("/history")
def draft_history(
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Max rows"),
    season: int = Query(None, ge=1900, le=2100, description="Filter by draft season"),
) -> dict:
    """Return draft_picks rows with weight_lbs/kg + in_dim_players flag.

    Each row carries ``in_dim_players`` (bool): False means the player's BBR id
    has no master-player page, so the UI should show "无资料" rather than link.
    """
    rows = load_draft_picks_with_weight(limit=limit, season=season)

    # 增量：附上本地头像（headshot_path/headshot_status），复用 player_bio 视图。
    # 仅做最小扩展：不影响 in_dim_players / weight 等既有字段与排序。
    _ids = [r.get("player_id") for r in rows if r.get("player_id")]
    _bios = {b["player_id"]: b for b in (get_player_bios(_ids) if _ids else [])}
    for r in rows:
        _b = _bios.get(r.get("player_id"), {})
        r["headshot_path"] = _b.get("headshot_path")
        r["headshot_status"] = _b.get("headshot_status")

    return {"count": len(rows), "rows": rows}
