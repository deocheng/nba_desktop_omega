"""T-A1-1 — baseline snapshot + 376-row audit export.

Usage (from project root, venv, proxy unset):
    env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
        PYTHONPATH="$(pwd)" .venv/Scripts/python.exe scripts/draft_a1_snapshot_audit.py

Creates dim_draft_history_bak_YYYYMMDD (idempotent) and writes the 376
historical diff rows (player_id != player_id_orig) to
docs/diagnostics/draft_376_audit.csv for the A1-2 crawler + A1-3 apply step.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from backend.data_layer import draft_quality

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_CSV = os.path.join(ROOT, "docs", "diagnostics", "draft_376_audit.csv")


def main() -> None:
    draft_quality.init_pool()
    try:
        bak = draft_quality.snapshot_draft_history()
        print(f"[snapshot] backup table = {bak}")
        rows = draft_quality.audit_draft_history_diffs()
        print(f"[audit] historical diff rows (player_id != player_id_orig) = {len(rows)}")
        n = draft_quality.export_audit_csv(rows, OUT_CSV)
        print(f"[audit] wrote {n} rows -> {OUT_CSV}")
    finally:
        draft_quality.close_pool()


if __name__ == "__main__":
    main()
