"""Load a draft_corrections CSV (from verify_draft_player_ids.py) into the
draft_pick_corrections table (A1-2 -> A1-3 store).

Usage:
    env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
        PYTHONPATH="$(pwd)" .venv/Scripts/python.exe \
        scripts/draft_a1_load_corrections.py docs/diagnostics/draft_corrections.csv
"""
from __future__ import annotations

import csv
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from backend.data_layer import draft_quality


def _to_float(v: str | None) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def main(csv_path: str) -> None:
    if not os.path.exists(csv_path):
        print(f"[load] CSV not found: {csv_path}")
        return
    draft_quality.init_pool()
    try:
        draft_quality.ensure_corrections_table()
        rows = []
        with open(csv_path, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append({
                    "wrong_id": r.get("player_id") or "",
                    "correct_id": (r.get("correct_id") or "") or None,
                    "status": r.get("status") or "error",
                    "page_name": (r.get("page_name") or "") or None,
                    "evidence": (r.get("evidence") or "") or None,
                    "confidence": _to_float(r.get("confidence")),
                })
        n = draft_quality.bulk_insert_corrections(rows)
        print(f"[load] inserted {n} new correction rows from {csv_path}")
    finally:
        draft_quality.close_pool()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: draft_a1_load_corrections.py <corrections.csv>")
        raise SystemExit(1)
    main(sys.argv[1])
