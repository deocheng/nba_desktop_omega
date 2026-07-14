"""A1-3 — apply the 94 high-confidence exists_match corrections (player_id -> correct_id).

Scope (per data-quality sign-off from the manager):
  * ONLY rows with status='exists_match' AND a non-empty correct_id are loaded/applied.
  * The 263 'mismatch' rows and 19 'skipped' rows are intentionally NOT processed here.
  * rollback_to_orig is NOT invoked by this script (mismatch handling is a separate,
    future, human-in-the-loop step).

Why this is safe / minimal (v8 §6):
  * All writes go through the designated ``draft_quality`` data-layer writer, which owns
    its own dedicated, parameterized psycopg2 pool (the same pattern as
    ``workspace_db.py``). No dynamic SQL: every identifier is bound with
    ``psycopg2.sql.Identifier`` and every value via ``%s``.
  * A baseline snapshot (``dim_draft_history_bak_YYYYMMDD``) is ensured before any write.
  * ``player_id_orig`` is never touched, so it remains the rollback anchor.

Outcome note:
  Every exists_match row already has ``player_id == correct_id`` and is present in
  ``dim_players`` (verified by the BR crawl). ``apply_corrections`` therefore performs a
  TRUE no-op (it only updates when the value would actually change), reporting 0 net
  data changes — i.e. these 94 candidates were already correctly corrected.

DEFAULT is dry-run. Pass --execute to invoke the (idempotent) UPDATE path.

Usage:
    env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
        PYTHONPATH="$(pwd)" .venv/Scripts/python.exe \
        scripts/draft_a1_apply_exists_match.py [--execute] \
        [--csv docs/diagnostics/draft_corrections.csv] [--min-confidence 0.8]
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from backend.data_layer import draft_quality

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_CSV = os.path.join(ROOT, "docs", "diagnostics", "draft_corrections.csv")


def _to_float(v: str | None) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def load_exists_match(csv_path: str) -> int:
    """Load ONLY high-confidence exists_match rows (correct_id non-empty).

    Maps CSV columns -> draft_pick_corrections:
        wrong_id   <- player_id
        correct_id <- correct_id
        status     <- 'exists_match'
        page_name  <- page_name
        evidence   <- evidence
        confidence <- confidence

    The same player can appear once per draft season in the CSV, so rows are
    de-duplicated by ``wrong_id`` before load (all share the same verified
    correct_id). The prior exists_match rows are cleared first so the store
    holds exactly one row per unique player — a clean, idempotent audit trail.
    """
    if not os.path.exists(csv_path):
        print(f"[load] CSV not found: {csv_path}")
        return 0
    seen: dict[str, dict] = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("status") or "") != "exists_match":
                continue
            correct = (r.get("correct_id") or "").strip()
            if not correct:
                continue  # only safely-correctable rows carry a verified id
            wid = (r.get("player_id") or "").strip()
            # last-write-wins; every duplicate shares the same correct_id
            seen[wid] = {
                "wrong_id": wid,
                "correct_id": correct,
                "status": "exists_match",
                "page_name": (r.get("page_name") or "") or None,
                "evidence": (r.get("evidence") or "") or None,
                "confidence": _to_float(r.get("confidence")),
            }
    rows = list(seen.values())
    draft_quality.clear_corrections_by_status("exists_match")
    n = draft_quality.bulk_insert_corrections(rows)
    print(
        f"[load] stored {len(rows)} unique exists_match correction rows "
        f"(from {csv_path}); inserted {n} this run"
    )
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Apply A1-3 exists_match corrections (dry-run default)"
    )
    ap.add_argument("--execute", action="store_true", help="Actually UPDATE (default: dry-run)")
    ap.add_argument("--min-confidence", type=float, default=0.8)
    ap.add_argument("--csv", default=DEFAULT_CSV)
    args = ap.parse_args()

    draft_quality.init_pool()
    try:
        # §6 safety: ensure baseline snapshot exists before any write (idempotent).
        bak = draft_quality.snapshot_draft_history()
        print(f"[snapshot] baseline backup = {bak}")

        draft_quality.ensure_corrections_table()
        load_exists_match(args.csv)

        # Apply only high-confidence exists_match corrections (idempotent, no-op-safe).
        dry = draft_quality.apply_corrections(
            min_confidence=args.min_confidence, dry_run=True
        )
        print("[apply_corrections dry-run]", dry)
        if args.execute:
            res = draft_quality.apply_corrections(
                min_confidence=args.min_confidence, dry_run=False
            )
            print("[apply_corrections execute]", res)
    finally:
        draft_quality.close_pool()


if __name__ == "__main__":
    main()
