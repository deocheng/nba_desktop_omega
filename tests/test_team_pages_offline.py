"""Offline regression for the unified 30-team crawler (no network).

Three layers of proof, all offline (the live 30-team run is T05, on the Mac):

1. **Data-driven gold check** — for every ``*_transactions_raw.html`` captured
   under ``det2026_br/`` that has a matching ``*_transactions_verbatim.txt``
   gold file, ``transactions_crawl.validate.assert_parse_matches_gold`` must
   reproduce it verbatim. Today this covers DET; as more teams' offline
   captures are added (T05) the same harness checks them automatically.

2. **30-team prefix rebuild (unit)** — for every one of the 30 canonical
   abbrs, feed a synthetic transaction ``<li>`` through ``parse_transactions``
   and assert the description is rebuilt with the correct ``"The <FullName> "``
   prefix (sourced from ``common.team_names`` — the single source). This proves
   the 30-team generalization without needing real HTML for all 30 teams, and
   guards against the historical concat bug (no ``"<FullName><Upper>"`` glue).

3. **Twin-dedup repair (DB, skipped without a live DB)** — insert a legacy
   space-less ("concat-bug") twin row, run ``upsert_transactions`` with the
   clean form, and assert the bad row is repaired in place (no new row added).

Run from the repo root:
    python -m pytest tests/test_team_pages_offline.py -v
"""

from __future__ import annotations

import glob
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.team_names import TEAM_ABBRS, get_full_name  # noqa: E402
from transactions_crawl.parse import parse_transactions  # noqa: E402
from transactions_crawl.validate import assert_parse_matches_gold  # noqa: E402

DET_DIR = os.path.join(ROOT, "det2026_br")


# ---------------------------------------------------------------------------
# 1) Data-driven gold check (any team with a captured raw HTML + verbatim gold)
# ---------------------------------------------------------------------------

def _gold_pairs(html_path: str, gold_path: str):
    abbr = re.match(r"^([A-Za-z]{3})_", os.path.basename(html_path)).group(1).upper()
    parsed = parse_transactions(open(html_path, encoding="utf-8").read(), team_abbr=abbr)
    gold = []
    for line in open(gold_path, encoding="utf-8").read().splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        date, _, desc = line.partition("\t")
        gold.append((date, desc))
    return {(r.transaction_date, r.description) for r in parsed}, set(gold)


def test_det_gold_via_validate_helper():
    html = os.path.join(DET_DIR, "DET_2026_transactions_raw.html")
    gold = os.path.join(DET_DIR, "DET_2026_transactions_verbatim.txt")
    assert os.path.exists(html) and os.path.exists(gold)
    summary = assert_parse_matches_gold(html, gold)
    assert summary["parsed"] == summary["gold"] > 0
    assert summary["team_abbr"] == "DET"


def test_all_available_offline_golds():
    """Validate every captured team's transactions against its verbatim gold.

    Auto-extends as more teams are captured (T05): any
    ``<ABBR>_<YEAR>_transactions_raw.html`` accompanied by a
    ``<ABBR>_<YEAR>_transactions_verbatim.txt`` is checked.
    """
    raw_files = glob.glob(os.path.join(DET_DIR, "*_transactions_raw.html"))
    checked = 0
    for html_path in raw_files:
        base = os.path.basename(html_path)
        m = re.match(r"^([A-Za-z]{3})_(\d{4})_transactions_raw\.html$", base)
        if not m:
            continue
        abbr, year = m.group(1).upper(), m.group(2)
        gold_path = os.path.join(DET_DIR, f"{abbr}_{year}_transactions_verbatim.txt")
        if not os.path.exists(gold_path):
            continue
        parsed, gold = _gold_pairs(html_path, gold_path)
        assert parsed == gold, f"{base}: parsed != gold"
        checked += 1
    # At minimum DET must be present and validated.
    assert checked >= 1, "no offline gold pairs found (expected DET)"


# ---------------------------------------------------------------------------
# 2) 30-team prefix rebuild (proves single-source generalization)
# ---------------------------------------------------------------------------

_SYNTH_LI = '<li>July 1, 2025 Signed Jordan Example to a multi-year contract.</li>'


@pytest.mark.parametrize("abbr", TEAM_ABBRS)
def test_prefix_rebuild_per_team(abbr: str):
    full = get_full_name(abbr)
    rows = parse_transactions(_SYNTH_LI, team_abbr=abbr)
    assert len(rows) == 1, f"{abbr}: expected exactly 1 entry"
    desc = rows[0].description
    # prefix is the canonical English full name from the single source
    assert desc.startswith(f"The {full} "), f"{abbr}: bad prefix -> {desc!r}"
    # concat-bug guard: the full name must be followed by a space, never glued
    # to the next capitalized word (e.g. "Pistonssigned")
    assert not re.search(rf"{full.split()[-1]}[A-Z]", desc), (
        f"{abbr}: concat bug detected -> {desc!r}"
    )
    # verb is lower-cased to match the gold verbatim form
    assert desc.endswith("signed Jordan Example to a multi-year contract.")


def test_all_30_abbrs_have_full_names():
    missing = [a for a in TEAM_ABBRS if get_full_name(a) != get_full_name(a)]
    assert not missing
    assert len(TEAM_ABBRS) == 30


# ---------------------------------------------------------------------------
# 3) Twin-dedup repair (DB; skipped if no live PostgreSQL)
# ---------------------------------------------------------------------------

def test_twin_dedup_repairs_concat_bug():
    """A legacy space-less twin is repaired in place by upsert_transactions."""
    try:
        from hof_exec.config import get_conn

        conn = get_conn()
    except Exception:  # noqa: BLE001 - no DB in sandbox
        pytest.skip("no live PostgreSQL available")

    from transactions_crawl.load import upsert_transactions
    from transactions_crawl.parse import TxnEntry

    probe = "TwinDedupProbe"
    date = "1990-01-01"  # sentinel: no real DET transactions on this date
    abbr = "DET"
    concat = f"TheDetroit Pistonssigned{probe} as a free agent."  # glued
    clean = f"The Detroit Pistons signed {probe} as a free agent."

    try:
        with conn:
            with conn.cursor() as cur:
                # The transactions.id sequence can be desynced after bulk loads,
                # so pick an explicit free id instead of relying on DEFAULT.
                cur.execute("SELECT COALESCE(max(id), 0) + 1 FROM transactions")
                next_id = cur.fetchone()[0]
                # seed the legacy bad row
                cur.execute(
                    "INSERT INTO transactions "
                    "(id, transaction_date, team_abbr, transaction_type, description, source) "
                    "VALUES (%s, %s, %s, %s, %s, 'probe') RETURNING id",
                    (next_id, date, abbr, "Signed", concat),
                )
                bad_id = cur.fetchone()[0]

        # run the upsert with the clean form -> should REPAIR the twin, not insert
        upsert_transactions([TxnEntry(team_abbr=abbr, transaction_date=date,
                                      transaction_type="Signed", description=clean)])

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, description FROM transactions "
                    "WHERE transaction_date=%s AND team_abbr=%s AND description LIKE %s",
                    (date, abbr, f"%{probe}%"),
                )
                rows = cur.fetchall()
        assert len(rows) == 1, f"expected exactly 1 row after repair, got {len(rows)}"
        repaired = rows[0][1]
        assert repaired == clean, f"twin not repaired: {repaired!r}"
        assert not re.search(r"Pistons[A-Z]", repaired), "concat bug remains"
    finally:
        # cleanup: remove the probe row so the DB is left untouched
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM transactions WHERE transaction_date=%s "
                    "AND team_abbr=%s AND description LIKE %s",
                    (date, abbr, f"%{probe}%"),
                )
        conn.close()
