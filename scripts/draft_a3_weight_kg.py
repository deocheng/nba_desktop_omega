"""T-A3-1 — derive weight_kg from weight_lbs (no BR needed) + best-effort
backfill of the 3 NULL weight rows in dim_players.

Idempotent: only NULL-kg rows with a non-null lbs are touched.

Usage:
    env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
        PYTHONPATH="$(pwd)" .venv/Scripts/python.exe scripts/draft_a3_weight_kg.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from backend.data_layer import weight_writer


def main() -> None:
    weight_writer.init_pool()
    try:
        pwh = weight_writer.derive_weight_kg("player_weight_history")
        print(f"[derive] player_weight_history weight_kg updated = {pwh}")
        dp = weight_writer.derive_weight_kg("dim_players")
        print(f"[derive] dim_players weight_kg updated = {dp}")
        backfilled = weight_writer.backfill_dim_players_null()
        print(f"[backfill] dim_players NULL-weight rows copied = {backfilled}")
        print("[coverage] dim_players =", weight_writer.weight_coverage("dim_players"))
        print("[coverage] player_weight_history =", weight_writer.weight_coverage("player_weight_history"))
    finally:
        weight_writer.close_pool()


if __name__ == "__main__":
    main()
