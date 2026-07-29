"""common/team_names.py — single source of truth for 30-team reference data.

This module is the ONE place that hard-codes the two BR-team reference maps
used across every team-page crawler:

  * ``TEAM_FULL_NAME`` : abbr -> English franchise name (e.g. ``"Detroit Pistons"``)
  * ``BR_TEAM_SLUGS``  : abbr -> Basketball-Reference *URL slug*
                         (``BKN`` -> ``BRK``, ``CHA`` -> ``CHO``, ``PHX`` -> ``PHO``; else identity)

Why code-hardened (NOT read from the DB at runtime)?
----------------------------------------------------
* The English franchise names exist **only here**. ``dim_teams.team_name`` is
  CHINESE (e.g. ``底特律活塞`` / ``布鲁克林篮网`` / ``新奥尔良鹈鹕``) and must
  NEVER be used as the English ``"Detroit Pistons"`` prefix source — see
  docs/team_crawl_design.md §3.2 / hard facts.
* The BR URL slug is also code-only. ``dim_teams.current_code`` is a *different*
  concept (historic-franchise -> current abbr continuity, e.g. ``NJN`` -> ``BKN``);
  it is NOT the BR slug, and there is no slug column in the DB.

Dependency direction (IMPORTANT — keep acyclic):
  ``common.team_names`` depends ONLY on ``common.bridge_constants`` (for the
  canonical 30 abbrs). It must NOT import ``hof_exec.config``. The crawlers'
  ``config`` modules import FROM this module (re-export) — see T02 in the
  design doc. Inverting this would create an import cycle at module load.

The ``TEAM_FULL_NAME`` 30-team dictionary was moved **verbatim** from
``transactions_crawl/parse.py`` (it already covered all 30 teams). Do NOT
re-derive it from the DB — the parser's "built for DET only" problem was
already solved at the code level; the remaining task was merely to give the
local copy a single home.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from .bridge_constants import _CANON

logger = logging.getLogger(__name__)

# 30 canonical NBA abbreviations (single source of truth from common).
TEAM_ABBRS: List[str] = sorted(_CANON)

# 30-team abbreviation -> full English franchise name. Used to build the
# "The <Team> " description prefix in transactions_crawl/parse.py.
# Moved verbatim from transactions_crawl/parse.py (already 30-team complete).
TEAM_FULL_NAME: Dict[str, str] = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}

# abbr -> BR url slug. Known divergences from the 3-letter canon abbr:
#   BKN -> BRK ,  CHA -> CHO ,  PHX -> PHO ; everything else is identity.
# Verified against dim_teams (active team_abbr == BR slug, current_code ==
# canonical abbr): Brooklyn/Charlotte/Phoenix all follow the same pattern, so
# all three divergences are required — without PHX -> PHO the live Phoenix URL
# (/teams/PHX/) 404s. ``check_against_db()`` surfaces any further divergence.
BR_TEAM_SLUGS: Dict[str, str] = {abbr: abbr for abbr in TEAM_ABBRS}
BR_TEAM_SLUGS["BKN"] = "BRK"
BR_TEAM_SLUGS["CHA"] = "CHO"
BR_TEAM_SLUGS["PHX"] = "PHO"


def get_full_name(abbr: str) -> str:
    """Return the English franchise name for an abbreviation.

    Raises ``KeyError`` on an unknown abbr (callers pass a validated abbr).
    """
    return TEAM_FULL_NAME[abbr]


def get_br_slug(abbr: str) -> str:
    """Return the BR URL slug for an abbreviation (BKN->BRK, CHA->CHO, PHX->PHO).

    Unknown abbrs fall back to themselves (defensive; callers pass a
    validated abbr).
    """
    return BR_TEAM_SLUGS.get(abbr, abbr)


def check_against_db(conn) -> Dict[str, List[str]]:
    """Cross-validate the code-hardened maps against ``dim_teams``.

    IMPORTANT — abbr/slug alignment ONLY. ``dim_teams.team_name`` is Chinese,
    so English ``TEAM_FULL_NAME`` values are deliberately NOT compared to it
    (that comparison would always fail). We instead verify:

      * every canonical ``abbr``'s slug (``BR_TEAM_SLUGS[abbr]``) resolves to
        an existing ``dim_teams.team_abbr`` row (no phantom / missing team);
      * every *active* ``dim_teams.team_abbr`` reverse-maps to a canonical
        abbr we crawl (no orphan active team).

    Returns a dict of mismatch lists (``{"missing_in_db": [...], "extra_in_db": [...]}``);
    both empty means the maps are consistent with the DB.
    """
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT team_abbr, current_code, is_active FROM dim_teams")
            rows = cur.fetchall()

    db_abbrs = {r[0] for r in rows}
    active_abbrs = {r[0] for r in rows if r[2]}
    slug_values = set(BR_TEAM_SLUGS.values())

    # Each canonical abbr must map (via slug) to a real dim_teams row.
    missing_in_db = [a for a in TEAM_ABBRS if BR_TEAM_SLUGS[a] not in db_abbrs]
    # Each active dim_teams abbr must reverse-map to a crawled canonical abbr.
    extra_in_db = [a for a in active_abbrs if a not in slug_values]

    return {"missing_in_db": missing_in_db, "extra_in_db": extra_in_db}
