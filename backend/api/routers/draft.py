"""NBACore v8 §2 Layer 3 — /draft router (pure orchestration, no SQL).

Serves draft_picks with weight (A2 JOIN-at-read) and an ``in_dim_players``
flag (A1-4) so the frontend can render "无资料" instead of a dead BR link.
No SQL / computation here — all data access goes through the data_layer.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from backend.data_layer.draft_loader import load_draft_picks_with_weight

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
    return {"count": len(rows), "rows": rows}
