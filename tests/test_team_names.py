"""Unit tests for common/team_names.py (single source of 30-team names/slugs).

Pure, no DB, no network. Proves:
  * TEAM_FULL_NAME keys == TEAM_ABBRS (30 teams, full coverage)
  * all TEAM_FULL_NAME values are ENGLISH (no CJK chars; dim_teams.team_name
    is Chinese and must NOT be used as the English-name source)
  * get_full_name / get_slug round-trip through BR_TEAM_SLUGS

Run from repo root:
    pytest tests/test_team_names.py -v
"""

from __future__ import annotations

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.team_names import (  # noqa: E402
    BR_TEAM_SLUGS,
    TEAM_ABBRS,
    TEAM_FULL_NAME,
    get_full_name,
    get_slug,
)

# Matches CJK Unified Ideographs (equivalent to the literal class [一-鿿]).
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def test_keys_equal_canonical_abbrs():
    assert set(TEAM_FULL_NAME.keys()) == set(TEAM_ABBRS), (
        f"TEAM_FULL_NAME keys {sorted(TEAM_FULL_NAME)} != "
        f"TEAM_ABBRS {sorted(TEAM_ABBRS)}"
    )
    assert len(TEAM_FULL_NAME) == 30


def test_values_are_english_no_cjk():
    for abbr, name in TEAM_FULL_NAME.items():
        assert name, f"empty name for {abbr}"
        assert not _CJK_RE.search(name), (
            f"{abbr} value {name!r} contains CJK chars — English source only!"
        )


def test_get_full_name():
    assert get_full_name("DET") == "Detroit Pistons"
    assert get_full_name("BKN") == "Brooklyn Nets"
    with pytest.raises(KeyError):
        get_full_name("ZZZ")


def test_get_slug_uses_br_team_slugs():
    # divergence cases
    assert get_slug("BKN") == "BRK"
    assert get_slug("CHA") == "CHO"
    # identity otherwise
    assert get_slug("DET") == "DET"
    assert get_slug("LAL") == "LAL"
    # slug map is a superset of the full-name keys
    for abbr in TEAM_FULL_NAME:
        assert abbr in BR_TEAM_SLUGS
