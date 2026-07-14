"""NBACore v8 §2 Layer 3 — /system router (pure orchestration).

All data fetched via data_layer. This router contains NO SQL,
NO pandas, NO computation — only request shaping + data_layer calls.
"""
from __future__ import annotations

import os
import shutil
import time

from fastapi import APIRouter, HTTPException, Query

from backend.core.db import is_port_open, ping
from backend.data_layer import (
    get_status_summary,
    get_table_data,
    list_tables,
)

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
def health_check() -> dict:
    """Health check endpoint — DB connectivity, disk space, etc."""
    db_connected = False
    try:
        if is_port_open():
            db_connected = ping()
    except Exception:
        db_connected = False

    return {
        "status": "ok" if db_connected else "degraded",
        "database_connected": db_connected,
        "timestamp": time.time(),
    }


@router.get("/status")
def system_status(
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
) -> dict:
    """Full status dashboard — tables, records, teams, recent games, top scorers."""
    try:
        return get_status_summary(season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"status fetch failed: {exc}")


@router.get("/tables")
def list_all_tables() -> dict:
    """List all database tables with row counts."""
    try:
        tables = list_tables()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"list tables failed: {exc}")
    return {"tables": tables, "total": len(tables)}


@router.get("/tables/{table_name}")
def browse_table(
    table_name: str,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    per_page: int = Query(50, ge=1, le=500, description="Rows per page"),
    search: str = Query("", description="Search string (matches text columns)"),
    sort_by: str = Query("", description="Column to sort by"),
    sort_order: str = Query("ASC", description="Sort direction: ASC or DESC"),
) -> dict:
    """Browse a table with pagination, search, and sorting."""
    try:
        rows, total, columns = get_table_data(
            table_name=table_name,
            page=page,
            per_page=per_page,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"table fetch failed: {exc}")

    total_pages = (total + per_page - 1) // per_page if per_page > 0 else 0
    return {
        "columns": columns,
        "rows": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }
