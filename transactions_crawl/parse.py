"""transactions_crawl/parse.py — pure HTML parser (offline & online share one path).

Public function (takes an HTML *string*, no I/O, no DB):
  * ``parse_transactions(html, team_abbr=None) -> list[TxnEntry]``

Because it only consumes an HTML string, the exact same code parses an
offline captured page (``det2026_br/DET_*_transactions_raw.html``) and a
live UC-Chrome page.

IMPORTANT — how a ``<li>`` becomes one or more ``TxnEntry`` rows
-----------------------------------------------------------------
A BR transactions ``<li>`` looks like::

    July 7, 2025 Signed Paul Reed to a multi-year contract. \
    Signed Caris LeVert to a multi-year contract. Traded Simone ...

i.e. a leading ``Month D, YYYY`` date, then one or more action sentences
each beginning with an action verb (Signed / Traded / Waived / ...). This is
the **root of the historical concat bug**: the old crawler joined the inner
fragments with an empty separator, producing glued text such as
``'TheDetroit PistonssignedMichael Curryas a free agent.'``.

This parser therefore:
  1. calls ``li.get_text(" ", strip=True)`` — the SPACE separator is the
     fix that produces correct inter-word spaces;
  2. strips the leading date and converts it to ``YYYY-MM-DD``;
  3. splits the remaining body into per-action segments (each segment begins
     at an action verb), because one ``<li>`` may contain several moves;
  4. prepends ``"The {Team Full Name} "`` (derived from ``team_abbr``) and
     lower-cases the action verb's first letter, exactly matching the
     hand-verified gold verbatim;
  5. dedups byte-identical ``<li>`` texts via a ``seen`` set.

The resulting ``description`` strings are the canonical, space-correct form
that the gold file ``det2026_br/DET_2026_transactions_verbatim.txt``
captures verbatim.
"""

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# 30-team abbreviation -> full franchise name (used to build the
# "The <Team> " description prefix). Static NBA reference data.
TEAM_FULL_NAME: dict[str, str] = {
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

# Leading ``Month D, YYYY`` (the optional ":" is tolerated for pages that
# include it; the captured DET page omits it).
_DATE_RE = re.compile(r"^([A-Z][a-z]+\.?\s*\d{1,2},?\s*\d{4})\b\s*:?\s*")

# Action verbs that mark the start of a transaction sentence. Order matters:
# "Re-Signed" must precede "Signed" so the alternation does not split on the
# embedded "Signed".
_ACTION_RE = re.compile(
    r"(?:Re-Signed|Re-signed|Re\s*-\s*signed|Signed|Waived|Traded|"
    r"Claimed|Converted|Released|Assigned|Appointed)"
)

# Keyword -> canonical transaction_type. Checked against the lower-cased
# segment text.
_TYPE_RULES: List[tuple[str, str]] = [
    ("re-signed", "Re-Signed"),
    ("signed", "Signed"),
    ("waived", "Waived"),
    ("traded", "Traded"),
    ("claimed", "Claimed"),
    ("converted", "Contract Converted"),
    ("released", "Released"),
    ("assigned", "Assigned"),
    ("appointed", "Appointed"),
]


@dataclass
class TxnEntry:
    """One parsed team transaction row."""

    team_abbr: Optional[str]
    transaction_date: str  # YYYY-MM-DD
    transaction_type: Optional[str]
    description: str


def _to_iso(date_token: str) -> str:
    """'July 7, 2025' -> '2025-07-07' (strips optional trailing dot)."""
    cleaned = date_token.replace(".", "").strip()
    return datetime.datetime.strptime(cleaned, "%B %d, %Y").strftime("%Y-%m-%d")


def _infer_type(text: str) -> Optional[str]:
    """Infer the canonical transaction_type from a description segment."""
    low = text.lower()
    for keyword, label in _TYPE_RULES:
        if keyword in low:
            return label
    return None


def parse_transactions(html: str, team_abbr: Optional[str] = None) -> List[TxnEntry]:
    """Parse a BR team transactions HTML page into a list of ``TxnEntry``.

    Parameters
    ----------
    html:
        Raw HTML string of the ``<year>_transactions`` page.
    team_abbr:
        Optional 3-letter abbreviation (e.g. ``"DET"``). When supplied, the
        parsed ``description`` is prefixed with ``"The <Team> "`` so it matches
        the BR verbatim gold form. When ``None``, no prefix is added.

    Returns
    -------
    list[TxnEntry]
        Transaction rows. Order follows document order; identical ``<li>``
        texts are de-duplicated via a ``seen`` set.
    """
    soup = BeautifulSoup(html, "html.parser")
    prefix = f"The {TEAM_FULL_NAME[team_abbr]} " if team_abbr in TEAM_FULL_NAME else ""

    entries: List[TxnEntry] = []
    seen: set[str] = set()

    for li in soup.find_all("li"):
        text = li.get_text(" ", strip=True)  # SPACE separator — the concat-bug fix
        if not text or text in seen:
            continue

        date_match = _DATE_RE.match(text)
        if not date_match:
            continue

        body = text[date_match.end():].strip()
        # A transaction ``<li>`` must contain at least one action verb after
        # the date; this excludes nav/footer list items that merely carry a
        # leading date (e.g. "June 13, 2026 ( Daily Leaders ) ...").
        action_starts = [m.start() for m in _ACTION_RE.finditer(body)]
        if not action_starts:
            continue

        seen.add(text)
        transaction_date = _to_iso(date_match.group(1))

        for idx, start in enumerate(action_starts):
            end = action_starts[idx + 1] if idx + 1 < len(action_starts) else len(body)
            segment = body[start:end].strip()
            if not segment:
                continue
            # Lower-case the action verb's first letter to match the gold
            # verbatim (e.g. "Signed ..." -> "signed ...").
            segment = segment[0].lower() + segment[1:]
            description = (prefix + segment).strip()
            entries.append(
                TxnEntry(
                    team_abbr=team_abbr,
                    transaction_date=transaction_date,
                    transaction_type=_infer_type(segment),
                    description=description,
                )
            )

    return entries
