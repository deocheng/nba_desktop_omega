"""hof_exec/parse.py — pure HTML parsers (offline & online share one code path).

Public functions (all take an HTML *string*, no I/O, no DB):
  * ``normalize_season(token) -> str | None``
  * ``parse_hof_div(html, team_abbr=None) -> list[HofEntry]``
  * ``parse_executives_table(html, team_abbr=None) -> list[ExecEntry]``

Because they only consume an HTML string, the exact same code parses an
offline captured page (``det2026_br/DET_*.html``) and a live UC-Chrome page.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from bs4 import BeautifulSoup, Comment

logger = logging.getLogger(__name__)

_SEASON_RE = re.compile(r"^\d{4}-\d{2}$")
_YEAR_RE = re.compile(r"\d{4}")

# Normalize typographic (curly) quotes to ASCII so names parsed from HTML
# match the straight-quote form used in the gold JSON (e.g. “Chuck” -> "Chuck").
_QUOTE_TABLE = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"})


def _norm_text(text: str) -> str:
    """Strip and ASCII-normalize a player/executive name."""
    return text.strip().translate(_QUOTE_TABLE)


@dataclass
class HofEntry:
    """One (team, season, player) Hall-of-Fame mapping."""

    team_abbr: Optional[str]
    season: str
    player_name: str
    br_slug: Optional[str]


@dataclass
class ExecEntry:
    """One (team, rk) executive tenure."""

    team_abbr: Optional[str]
    rk: int
    executive: str
    start: str
    end: str
    notes: Optional[str]


def normalize_season(token: str) -> Optional[str]:
    """Normalize a raw season token to the canonical ``YYYY-YY`` form.

    * Already ``YYYY-YY`` (e.g. ``2010-11``) -> returned unchanged.
    * Otherwise take the leading 4-digit year ``Y`` and return
      ``f"{Y}-{str(Y + 1)[2:]}"`` (with a warning).
    * If no 4-digit year can be found, log an error and return ``None`` so the
      caller can skip the row.
    """
    if token is None:
        return None
    raw = token.strip()
    if _SEASON_RE.match(raw):
        return raw
    m = _YEAR_RE.search(raw)
    if m:
        y = int(m.group(0))
        norm = f"{y}-{str(y + 1)[2:]}"
        logger.warning("normalize_season: '%s' -> '%s' (heuristic)", raw, norm)
        return norm
    logger.error("normalize_season: cannot parse '%s'; skipping", raw)
    return None


def _slug_from_href(href: Optional[str]) -> Optional[str]:
    """Extract a BR player slug from an href like '/players/m/mcgratr01.html'."""
    if not href:
        return None
    base = href.rstrip("/").split("?")[0]
    name = base.rsplit("/", 1)[-1]
    if not name:
        return None
    return name.rsplit(".", 1)[0] or None


def parse_hof_div(html: str, team_abbr: Optional[str] = None) -> List[HofEntry]:
    """Parse the HoF leaderboard ``<div>`` blocks into HofEntry rows.

    Container: ``div#div_leaderboard`` (fallback ``div.leaderboard_grid``).
    Each block id matches ``leaderboard_number-<season>``; its ``<h4>`` holds
    the season label and its ``<span><a>`` links are the inducted players.
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("div", id="div_leaderboard")
    if container is None:
        container = soup.find("div", class_="leaderboard_grid")
    if container is None:
        logger.error("parse_hof_div: no leaderboard container found")
        return []

    rows: List[HofEntry] = []
    blocks = container.find_all("div", id=re.compile(r"^leaderboard_number-(.+)$"))
    for block in blocks:
        h4 = block.find("h4")
        if h4 is None:
            continue
        season = normalize_season(h4.get_text(strip=True))
        if not season:
            continue
        for a in block.find_all("a"):
            player_name = _norm_text(a.get_text(strip=True))
            if not player_name:
                continue
            rows.append(
                HofEntry(
                    team_abbr=team_abbr,
                    season=season,
                    player_name=player_name,
                    br_slug=_slug_from_href(a.get("href")),
                )
            )
    return rows


def parse_executives_table(html: str, team_abbr: Optional[str] = None) -> List[ExecEntry]:
    """Parse the executives ``<table>`` into ExecEntry rows.

    The table is searched across BOTH the main document and any HTML comment
    blocks (BR occasionally hides stat tables inside comments). We pick the
    table whose header contains both ``Executive`` and ``Start``.

    Per-row rules:
      * skip empty rows;
      * skip the header row / a repeated header row (first cell == ``"Rk"``);
      * skip rows whose ``rk`` is not numeric (warning);
      * ``start`` / ``end`` are kept as raw TEXT (e.g. ``1948``,
        ``1954-03-27``, ``present``) — never coerced to a date.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Gather candidate tables from both the main doc and HTML comment blocks.
    candidates = list(soup.find_all("table"))
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        sub = BeautifulSoup(str(c), "html.parser")
        candidates.extend(sub.find_all("table"))

    target = None
    for tbl in candidates:
        head = tbl.find("thead")
        headers = [th.get_text(" ", strip=True) for th in head.find_all("th")] if head else []
        if "Executive" in headers and "Start" in headers:
            target = tbl
            break
    if target is None:
        logger.error("parse_executives_table: no executives table found")
        return []

    rows: List[ExecEntry] = []
    tbody = target.find("tbody")
    if tbody is None:
        return rows
    for tr in tbody.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
        if not cells:
            continue  # empty row
        if cells[0] == "Rk" or (
            len(cells) >= 5 and cells[:5] == ["Rk", "Executive", "Start", "End", "Notes"]
        ):
            continue  # header row / repeated (duplicate) header row
        try:
            rk = int(cells[0])
        except (ValueError, IndexError):
            logger.warning("parse_executives_table: skipping non-numeric rk row %r", cells)
            continue
        executive = _norm_text(cells[1]) if len(cells) > 1 else ""
        start = cells[2] if len(cells) > 2 else ""
        end = cells[3] if len(cells) > 3 else ""
        notes = cells[4] if len(cells) > 4 else ""
        rows.append(
            ExecEntry(
                team_abbr=team_abbr,
                rk=rk,
                executive=executive,
                start=start,
                end=end,
                notes=notes or None,
            )
        )
    return rows
