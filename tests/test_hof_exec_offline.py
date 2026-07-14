"""Offline parse + gold-validation tests for hof_exec (no DB, no network).

Proves the parsers reproduce the hand-verified DET gold data:
  * HOF: 118 (season, player) entries, 23 distinct players
  * Executives: 22 tenures (the duplicate header row in the gold CSV is skipped)

Run from the repo root:
    pytest tests/test_hof_exec_offline.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hof_exec.fetch import fetch_team_page  # noqa: E402
from hof_exec.parse import (  # noqa: E402
    normalize_season,
    parse_executives_table,
    parse_hof_div,
)
from hof_exec.validate import assert_parse_matches_gold  # noqa: E402

DET_DIR = os.path.join(ROOT, "det2026_br")
HOF_HTML = open(os.path.join(DET_DIR, "DET_hof.html"), encoding="utf-8").read()
EXEC_HTML = open(os.path.join(DET_DIR, "DET_executives.html"), encoding="utf-8").read()


def test_hof_entry_count():
    rows = parse_hof_div(HOF_HTML)
    assert len(rows) == 118, f"expected 118 HOF entries, got {len(rows)}"
    distinct = {r.player_name for r in rows}
    assert len(distinct) == 23, f"expected 23 distinct HOFers, got {len(distinct)}"


def test_exec_entry_count():
    rows = parse_executives_table(EXEC_HTML)
    assert len(rows) == 22, f"expected 22 executives, got {len(rows)}"
    rks = [r.rk for r in rows]
    assert rks == list(range(1, 23)), f"rk sequence mismatch: {rks}"


def test_offline_fetch():
    html = fetch_team_page("DET", "hof", offline_dir=DET_DIR)
    assert "leaderboard_number" in html
    html2 = fetch_team_page("DET", "executives", offline_dir=DET_DIR)
    assert "Executive" in html2


def test_normalize_season():
    assert normalize_season("2010-11") == "2010-11"
    assert normalize_season("  2005-06  ") == "2005-06"
    assert normalize_season("2013-2014") == "2013-14"  # heuristic from 4-digit year
    assert normalize_season("not-a-season") is None


def test_parse_matches_gold():
    summary = assert_parse_matches_gold(
        html_dir=DET_DIR,
        gold_json=os.path.join(DET_DIR, "DET_hof_players.json"),
        gold_csv=os.path.join(DET_DIR, "DET_executives.csv"),
    )
    assert summary["hof_entries"] == 118
    assert summary["hof_distinct"] == 23
    assert summary["exec_entries"] == 22
