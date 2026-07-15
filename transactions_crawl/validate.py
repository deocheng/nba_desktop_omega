"""transactions_crawl/validate.py — assert offline parse output matches gold.

Used by the pytest suite to prove the parser reproduces the hand-verified
DET gold data verbatim (35 transaction lines, correct spaces, no concat bug).
"""

from __future__ import annotations

import os
import re

from .parse import parse_transactions


def _abbr_from_path(html_path: str) -> str | None:
    """Derive the 3-letter team abbreviation from a filename like
    ``DET_2026_transactions_raw.html`` -> ``'DET'``."""
    base = os.path.basename(html_path)
    m = re.match(r"^([A-Za-z]{3})_", base)
    return m.group(1).upper() if m else None


def _read_gold(gold_path: str) -> list[tuple[str, str]]:
    """Read the gold verbatim file into ``(date, description)`` pairs.

    Each non-empty line is ``YYYY-MM-DD<TAB>description``.
    """
    pairs: list[tuple[str, str]] = []
    with open(gold_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            date, _, desc = line.partition("\t")
            pairs.append((date, desc))
    return pairs


def assert_parse_matches_gold(html_path: str, gold_path: str) -> dict:
    """Parse the raw HTML and compare against the gold file.

    Returns a summary dict; raises ``AssertionError`` on any mismatch (count
    or per-pair multi-set equality) or on the presence of the concat bug.
    """
    with open(html_path, "r", encoding="utf-8") as fh:
        html = fh.read()

    abbr = _abbr_from_path(html_path)
    parsed = parse_transactions(html, team_abbr=abbr)
    parsed_pairs = [(r.transaction_date, r.description) for r in parsed]

    gold_pairs = _read_gold(gold_path)

    assert len(parsed_pairs) == len(gold_pairs), (
        f"parsed count {len(parsed_pairs)} != gold count {len(gold_pairs)}"
    )

    parsed_set = set(parsed_pairs)
    gold_set = set(gold_pairs)
    assert parsed_set == gold_set, (
        "parsed (date, description) multi-set differs from gold:\n"
        f"  only in parsed: {parsed_set - gold_set}\n"
        f"  only in gold:   {gold_set - parsed_set}"
    )

    # concat-bug guard: "Pistons" must always be followed by a space.
    for _, desc in parsed_pairs:
        assert not re.search(r"Pistons[A-Z]", desc), (
            f"concat bug detected: {desc!r}"
        )

    return {
        "parsed": len(parsed_pairs),
        "gold": len(gold_pairs),
        "team_abbr": abbr,
    }
