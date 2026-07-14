"""NBACore v8 §2 Layer 3 — /monitor router (pure orchestration).

Monitoring and stats endpoints. No business logic — just reports internal state.
"""
from __future__ import annotations

import time

from fastapi import APIRouter

from backend.core.db import ping
from backend.services.metric_engine import list_metrics

router = APIRouter(prefix="/monitor", tags=["monitor"])

_start_time = time.time()


@router.get("/stats")
def get_stats() -> dict:
    """Get system statistics (DB status, metrics count, uptime)."""
    db_alive = ping()
    uptime = time.time() - _start_time

    return {
        "uptime_seconds": round(uptime, 2),
        "uptime_display": _format_uptime(uptime),
        "database": {
            "connected": db_alive,
        },
        "metrics_registered": len(list_metrics()),
        "layers": {
            "data_layer": "active",
            "metric_engine": "active",
            "api_layer": "active",
            "context_engine": "active",
            "export_service": "active",
            "frontend": "active",
        },
        "endpoints": {
            "players": ["/players/search", "/players/{id}", "/players/seasons"],
            "metrics": ["/metrics/list", "/metrics/evaluate/{metric}"],
            "vs": ["/vs/compare"],
            "context": ["/context/similar", "/context/evolution", "/context/trend"],
            "export": ["/export/rankings", "/export/vs", "/export/player"],
            "batch": ["/batch/execute"],
            "monitor": ["/monitor/stats"],
        },
    }


def _format_uptime(seconds: float) -> str:
    """Format seconds into human-readable uptime."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"
