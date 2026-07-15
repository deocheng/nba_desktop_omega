"""Offline 30-team regression for the unified orchestrator (no DB, no network).

Proves the new ``crawl_team_pages`` wiring reproduces the hand-verified DET
gold for all three kinds, and that non-DET teams are gracefully SKIPped when
their offline files are absent. The load (upsert) layer is mocked so the test
runs without a database.

Mirrors the expectations in docs/team_crawl_design.md §3.1 and the existing
per-package offline tests (test_transactions_offline / test_hof_exec_offline),
but drives them through the orchestrator's ``run_team`` entry point.

Run from repo root:
    pytest tests/test_team_pages_offline.py -v
"""

from __future__ import annotations

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import crawl_team_pages  # noqa: E402
from hof_exec.parse import parse_executives_table, parse_hof_div  # noqa: E402
from transactions_crawl.parse import parse_transactions  # noqa: E402

DET_DIR = os.path.join(ROOT, "det2026_br")
DET_TXN_HTML = open(
    os.path.join(DET_DIR, "DET_2026_transactions_raw.html"), encoding="utf-8"
).read()
DET_HOF_HTML = open(os.path.join(DET_DIR, "DET_hof.html"), encoding="utf-8").read()
DET_EXEC_HTML = open(
    os.path.join(DET_DIR, "DET_executives.html"), encoding="utf-8"
).read()
DET_GOLD = os.path.join(DET_DIR, "DET_2026_transactions_verbatim.txt")


def _gold_lines():
    out = []
    for line in open(DET_GOLD, encoding="utf-8").read().splitlines():
        if not line.strip():
            continue
        date, _, desc = line.partition("\t")
        out.append((date, desc))
    return out


# --- parse-layer gold guards (concat-bug + multiset equality) -----------------

def test_det_transactions_parse_gold():
    rows = parse_transactions(DET_TXN_HTML, team_abbr="DET")
    assert len(rows) == 35, f"expected 35 txn rows, got {len(rows)}"
    parsed = {(r.transaction_date, r.description) for r in rows}
    gold = set(_gold_lines())
    assert parsed == gold, "parsed (date, description) differs from gold"
    # concat-bug guard: "Pistons" must never be immediately followed by A-Z
    assert not any(re.search(r"Pistons[A-Z]", r.description) for r in rows)


def test_det_hof_parse_gold():
    rows = parse_hof_div(DET_HOF_HTML, team_abbr="DET")
    assert len(rows) == 118, f"expected 118 HOF rows, got {len(rows)}"
    assert len({r.player_name for r in rows}) == 23


def test_det_executives_parse_gold():
    rows = parse_executives_table(DET_EXEC_HTML, team_abbr="DET")
    assert len(rows) == 22, f"expected 22 exec rows, got {len(rows)}"
    assert [r.rk for r in rows] == list(range(1, 23))


# --- orchestrator wiring (load mocked) ----------------------------------------

def _patch_loads(monkeypatch):
    """Replace the three upsert fns with counters; return the shared dict."""
    captured = {"txn": 0, "hof": 0, "exec": 0}

    def fake_txn(rows):
        captured["txn"] += len(rows)
        return len(rows)

    def fake_hof(rows):
        captured["hof"] += len(rows)
        return len(rows)

    def fake_exec(rows):
        captured["exec"] += len(rows)
        return len(rows)

    monkeypatch.setattr(crawl_team_pages, "upsert_transactions", fake_txn)
    monkeypatch.setattr(crawl_team_pages, "upsert_hof", fake_hof)
    monkeypatch.setattr(crawl_team_pages, "upsert_executives", fake_exec)
    return captured


def test_orchestrator_det_all_kinds(monkeypatch):
    captured = _patch_loads(monkeypatch)
    crawl_team_pages.run_team("DET", "all", 2000, 2026, DET_DIR)
    assert captured["txn"] == 35, captured
    assert captured["hof"] == 118, captured
    assert captured["exec"] == 22, captured


def test_orchestrator_non_det_skipped_offline(monkeypatch):
    """A team with no offline fixtures must be skipped, not crash."""
    captured = _patch_loads(monkeypatch)
    # BOS has no files under det2026_br -> all fetches FileNotFoundError -> SKIP
    crawl_team_pages.run_team("BOS", "all", 2000, 2026, DET_DIR)
    assert captured == {"txn": 0, "hof": 0, "exec": 0}


def test_orchestrator_kind_filter(monkeypatch):
    captured = _patch_loads(monkeypatch)
    crawl_team_pages.run_team("DET", "trans", 2000, 2026, DET_DIR)
    assert captured["txn"] == 35
    assert captured["hof"] == 0
    assert captured["exec"] == 0
