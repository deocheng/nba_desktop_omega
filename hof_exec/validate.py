"""hof_exec/validate.py — assert offline parse output matches gold fixtures.

Used by the pytest suite to prove the parsers reproduce the hand-verified
DET gold data (118 HoF season entries / 23 distinct players, 22 executives).
"""

from __future__ import annotations

import csv
import json
import os

from .parse import parse_executives_table, parse_hof_div


def assert_parse_matches_gold(html_dir: str, gold_json: str, gold_csv: str) -> dict:
    """Parse the DET HTML in ``html_dir`` and compare against the gold files.

    Returns a summary dict; raises ``AssertionError`` on any mismatch.
    """
    hof_html = open(os.path.join(html_dir, "DET_hof.html"), encoding="utf-8").read()
    exec_html = open(os.path.join(html_dir, "DET_executives.html"), encoding="utf-8").read()

    hof = parse_hof_div(hof_html)
    exec_rows = parse_executives_table(exec_html)

    # --- HOF gold ---
    with open(gold_json, encoding="utf-8") as fh:
        gold = json.load(fh)
    gold_count = gold.get("count")
    gold_se = {(s, p) for s, p in gold.get("season_entries", [])}

    assert len(hof) == len(gold_se), f"HOF entry count {len(hof)} != gold {len(gold_se)}"
    parsed_se = {(r.season, r.player_name) for r in hof}
    assert parsed_se == gold_se, "HOF season_entries mismatch vs gold"
    if gold_count is not None:
        distinct = {r.player_name for r in hof}
        assert len(distinct) == gold_count, f"HOF distinct {len(distinct)} != gold {gold_count}"

    # --- Executives gold ---
    gold_exec: list[list[str]] = []
    with open(gold_csv, encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header
        for cells in reader:
            if not cells or cells[0].strip() == "Rk":
                continue  # skip duplicate header row (e.g. CSV line 22)
            gold_exec.append(cells)

    assert len(exec_rows) == len(gold_exec), (
        f"Exec count {len(exec_rows)} != gold {len(gold_exec)}"
    )

    return {
        "hof_entries": len(hof),
        "hof_distinct": len({r.player_name for r in hof}),
        "exec_entries": len(exec_rows),
    }
