"""A1-3 — apply high-confidence corrections / roll back wrong ones (round 2).

DEFAULT is dry-run (no writes). Pass --execute to actually UPDATE
dim_draft_history. Every update preserves player_id_orig as the rollback anchor.

Usage:
    env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
        PYTHONPATH="$(pwd)" .venv/Scripts/python.exe \
        scripts/draft_a1_apply.py [--execute] [--min-confidence 0.8]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from backend.data_layer import draft_quality


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply draft corrections (dry-run default)")
    ap.add_argument("--execute", action="store_true", help="Actually UPDATE (default: dry-run)")
    ap.add_argument("--min-confidence", type=float, default=0.8)
    args = ap.parse_args()

    draft_quality.init_pool()
    try:
        draft_quality.ensure_corrections_table()
        apply_res = draft_quality.apply_corrections(
            min_confidence=args.min_confidence, dry_run=not args.execute
        )
        rollback_res = draft_quality.rollback_to_orig(
            min_confidence=args.min_confidence, dry_run=not args.execute
        )
        print("[apply_corrections]", apply_res)
        print("[rollback_to_orig]", rollback_res)
    finally:
        draft_quality.close_pool()


if __name__ == "__main__":
    main()
