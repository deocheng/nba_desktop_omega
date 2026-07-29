"""Offline unit tests for common/team_names.py (no DB, no network).

Proves the single-source reference module is internally consistent and
correctly generalizes to all 30 teams:

  * exactly 30 full names, keyed by the canonical 30 abbrs;
  * all English names (no CJK) — dim_teams.team_name is Chinese and must NOT
    be used as the English source;
  * BR_TEAM_SLUGS diverges for BKN->BRK, CHA->CHO, PHX->PHO; identity otherwise;
  * get_full_name / get_br_slug resolve correctly for every abbr.

The English<->Chinese name comparison against ``dim_teams.team_name`` is
intentionally NOT done here (team_name is Chinese); the abbr/slug alignment
check lives in scripts/verify_team_names_db.py (needs a live DB).

Run from the repo root:
    python -m pytest tests/test_team_names.py -v
"""

from __future__ import annotations

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.bridge_constants import _CANON  # noqa: E402
from common.team_names import (  # noqa: E402
    BR_TEAM_SLUGS,
    TEAM_ABBRS,
    TEAM_FULL_NAME,
    check_against_db,
    get_br_slug,
    get_full_name,
)

# CJK Unified Ideographs — used to assert TEAM_FULL_NAME holds English only.
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def test_thirty_full_names():
    assert len(TEAM_FULL_NAME) == 30
    assert set(TEAM_FULL_NAME) == set(_CANON)
    assert all(name.strip() for name in TEAM_FULL_NAME.values())


def test_values_are_english_no_cjk():
    for abbr, name in TEAM_FULL_NAME.items():
        assert name, f"empty name for {abbr}"
        assert not _CJK_RE.search(name), (
            f"{abbr} value {name!r} contains CJK — English source only!"
        )


def test_abbrs_sorted_canon():
    assert TEAM_ABBRS == sorted(_CANON)
    assert len(TEAM_ABBRS) == 30


def test_slug_divergences():
    # the three known slug divergences (verified against dim_teams active team_abbr)
    assert BR_TEAM_SLUGS["BKN"] == "BRK"
    assert BR_TEAM_SLUGS["CHA"] == "CHO"
    assert BR_TEAM_SLUGS["PHX"] == "PHO"
    # everything else is identity
    for abbr in TEAM_ABBRS:
        if abbr in ("BKN", "CHA", "PHX"):
            continue
        assert BR_TEAM_SLUGS[abbr] == abbr, f"unexpected slug for {abbr}"


def test_get_full_name():
    assert get_full_name("DET") == "Detroit Pistons"
    assert get_full_name("BKN") == "Brooklyn Nets"
    assert get_full_name("CHA") == "Charlotte Hornets"
    assert get_full_name("PHX") == "Phoenix Suns"
    with pytest.raises(KeyError):
        get_full_name("ZZZ")


def test_get_br_slug():
    assert get_br_slug("BKN") == "BRK"
    assert get_br_slug("CHA") == "CHO"
    assert get_br_slug("PHX") == "PHO"
    assert get_br_slug("DET") == "DET"
    # defensive fallback for unknown abbr
    assert get_br_slug("ZZZ") == "ZZZ"


def test_det_available():
    # The DET prototype must remain covered by the unified source.
    assert TEAM_FULL_NAME["DET"] == "Detroit Pistons"
    assert "DET" in TEAM_ABBRS


def test_check_against_db_alignment():
    """Abbr/slug alignment with dim_teams (skipped if no live DB).

    Uses the same connection path the crawlers use. Never compares English
    names to Chinese team_name.
    """
    try:
        from hof_exec.config import get_conn

        conn = get_conn()
    except Exception:  # noqa: BLE001 - no DB in sandbox
        pytest.skip("no live PostgreSQL available")
    try:
        result = check_against_db(conn)
    finally:
        conn.close()
    assert result["missing_in_db"] == [], result["missing_in_db"]
    assert result["extra_in_db"] == [], result["extra_in_db"]
