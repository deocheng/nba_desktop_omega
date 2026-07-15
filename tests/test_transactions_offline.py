"""Offline parse + gold-validation tests for transactions_crawl (no DB, no network).

Proves the parser reproduces the hand-verified DET gold data verbatim:
  * 35 transaction lines (the README's "36" counts a Schroder near-duplicate
    that was intentionally excluded from the verbatim gold; the captured page
    and the gold both carry 35 substantive rows),
  * correct inter-word spaces (the historical concat bug is gone),
  * per-(date, description) multi-set equality with the gold file.

Run from the repo root:
    python -m pytest tests/test_transactions_offline.py -v
"""

from __future__ import annotations

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from transactions_crawl.fetch import fetch_transactions_page  # noqa: E402
from transactions_crawl.parse import parse_transactions  # noqa: E402
from transactions_crawl.validate import assert_parse_matches_gold  # noqa: E402

DET_DIR = os.path.join(ROOT, "det2026_br")
DET_HTML = os.path.join(DET_DIR, "DET_2026_transactions_raw.html")
DET_GOLD = os.path.join(DET_DIR, "DET_2026_transactions_verbatim.txt")

HTML = open(DET_HTML, encoding="utf-8").read()


def _gold_lines():
    out = []
    for line in open(DET_GOLD, encoding="utf-8").read().splitlines():
        if not line.strip():
            continue
        date, _, desc = line.partition("\t")
        out.append((date, desc))
    return out


def test_parse_count_matches_gold():
    rows = parse_transactions(HTML, team_abbr="DET")
    gold = _gold_lines()
    # parser must reproduce the gold verbatim (count + content)
    assert len(rows) == len(gold), f"parsed {len(rows)} != gold {len(gold)}"
    # sanity: a non-empty, transaction-shaped result
    assert len(rows) >= 30


def test_parse_matches_gold_multiset():
    rows = parse_transactions(HTML, team_abbr="DET")
    parsed = {(r.transaction_date, r.description) for r in rows}
    gold = set(_gold_lines())
    assert parsed == gold, "parsed (date, description) differs from gold"


def test_offline_fetch():
    html = fetch_transactions_page("DET", 2026, offline_dir=DET_DIR)
    assert "Pistons" in html


def test_no_concat_bug():
    rows = parse_transactions(HTML, team_abbr="DET")
    # the specific good row must be present (correct spaces, no glue)
    assert ("2025-07-07", "The Detroit Pistons signed Caris LeVert to a multi-year contract.") in {
        (r.transaction_date, r.description) for r in rows
    }
    # global concat-bug guard: "The Detroit Pistons signed" appears, and no
    # description has "Pistons" immediately followed by an uppercase letter.
    descriptions = [r.description for r in rows]
    assert any("The Detroit Pistons signed" in d for d in descriptions)
    assert not any(re.search(r"Pistons[A-Z]", d) for d in descriptions)


def test_validate_helper():
    summary = assert_parse_matches_gold(DET_HTML, DET_GOLD)
    gold = _gold_lines()
    assert summary["parsed"] == len(gold)
    assert summary["gold"] == len(gold)
