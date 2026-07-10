"""NBACore v8 §2 / §6 — /data-import router (CSV bulk import), thin orchestration.

Architectural boundary (v8 §6):
    The API layer is pure orchestration. It only shapes the multipart request
    and delegates the actual DB write to `backend.services.import_engine.import_db`
    — the *designated writer* for the import feature. This router imports NO
    psycopg2 and contains NO SQL strings; all write-path logic (pool, catalog
    introspection, parameterized INSERT/TRUNCATE, type coercion) lives in the
    import_engine service, keeping `backend.core.db` SELECT-only for analytics.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.services.import_engine.import_db import (
    import_csv,
    list_public_tables,
)

logger = logging.getLogger("nbacore.routers.data_import")

router = APIRouter(prefix="/data-import", tags=["data-import"])


@router.get("/tables")
def list_import_tables() -> dict:
    """List public-schema tables available as import targets."""
    return {"tables": list_public_tables()}


@router.post("/upload")
async def upload_csv(
    file: UploadFile = File(...),
    target_table: str = Form("team_game_splits"),
    mode: str = Form("append"),
) -> dict:
    """Bulk-import a CSV file into a validated public table.

    Args:
        file: multipart CSV upload.
        target_table: destination public table (validated against catalog by
            the import_engine service).
        mode: "append" (INSERT) or "replace" (TRUNCATE then INSERT).

    Returns:
        dict: { inserted, errors, columns, table }

    Raises:
        HTTPException 400: invalid mode / unknown table / no matching columns /
            unreadable upload (mapped from import_engine.ValueError / read error).
    """
    # Read the upload in the API layer, then delegate the write. Decoding here
    # keeps the bytes handling in orchestration; the service consumes plain text.
    try:
        raw = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"failed to read upload: {exc}")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")

    if not text.strip():
        raise HTTPException(status_code=400, detail="uploaded CSV is empty")

    # Catalog validation + parameterized write happen in the designated writer.
    try:
        return import_csv(target_table, mode, text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
