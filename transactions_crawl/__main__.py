"""transactions_crawl/__main__ — CLI to crawl + load BR team transactions.

Supports both single-season and full-volume reverse (multi-year) crawls:

  * Single season (default): ``--year`` (default 2026).
  * Full-volume reverse: ``--all-years`` builds a year list
    ``list(range(year_end, year_start - 1, -1))`` — newest first — and loops
    every (year, team) pair, so the entire transaction history is fetched
    from the most recent season back to the earliest.

The inner (year, team) processing reuses the same fetch -> 404-skip ->
parse -> upsert pipeline, so the parser/config layers are untouched.

Examples
--------
Offline (sandbox / verified), single team:
    python -m transactions_crawl --offline-dir det2026_br --team DET --year 2026

Offline multi-year replay (only the years present in <dir> will resolve,
others are gracefully SKIP-ped on FileNotFoundError):
    python -m transactions_crawl --all-teams --all-years \\
        --year-start 2026 --year-end 2026 --offline-dir det2026_br

Live, all 30 teams, full reverse history (run on the user's Mac —
Cloudflare blocks the sandbox):
    python -m transactions_crawl --all-teams --all-years

Live, all 30 teams, most-recent N years (e.g. 2000..2026):
    python -m transactions_crawl --all-teams --all-years \\
        --year-start 2000 --year-end 2026
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import TEAM_ABBRS
from .fetch import fetch_transactions_page, looks_like_404
from .load import upsert_transactions
from .parse import parse_transactions

logger = logging.getLogger("transactions_crawl")


def _run_pair(abbr: str, year: int, offline_dir: str | None) -> int:
    """Process a single (team, year) pair.

    Returns the number of rows written/updated for that pair.

    A missing offline file (``FileNotFoundError``) or a BR 404 page is treated
    as a graceful skip — logged and ``0`` returned — so a full reverse crawl
    over teams/years that have no page does not abort the run.
    """
    try:
        html = fetch_transactions_page(abbr, year, offline_dir=offline_dir)
    except FileNotFoundError as exc:
        logger.warning("SKIP %s/%s: %s", abbr, year, exc)
        return 0
    if looks_like_404(html):
        logger.warning("SKIP %s/%s: 404 page detected", abbr, year)
        return 0
    rows = parse_transactions(html, team_abbr=abbr)
    n = upsert_transactions(rows)
    logger.info("LOADED %s/%s: %d rows", abbr, year, n)
    return n


def _run(team_abbrs: list[str], years: list[int], offline_dir: str | None) -> int:
    """Run the crawl for an explicit list of years (outer) and teams (inner).

    Parameters
    ----------
    team_abbrs:
        Team abbreviations to process (e.g. all 30, or a single team).
    years:
        Season-end years to process, in the order the caller wants them
        visited. For a full reverse crawl this is the descending list
        ``list(range(year_end, year_start - 1, -1))`` (newest first).
    offline_dir:
        Optional offline HTML directory; ``None`` triggers live fetches.

    Returns
    -------
    int
        Total rows written/updated across all (year, team) pairs.
    """
    total = 0
    for year in years:
        logger.info("YEAR %s: start (%d teams)", year, len(team_abbrs))
        for abbr in team_abbrs:
            total += _run_pair(abbr, year, offline_dir)
        logger.info("YEAR %s: done", year)
    logger.info("DONE totals: transactions=%d", total)
    return total


def _build_years(args: argparse.Namespace, raw_argv: list[str]) -> list[int]:
    """Resolve the list of years to crawl from parsed args.

    Single-season mode returns ``[args.year]``. Multi-year mode (``--all-years``)
    returns ``list(range(year_end, year_start - 1, -1))`` — i.e. newest first.
    If ``--year`` is explicitly given together with ``--all-years`` it is ignored
    with a warning (the range takes precedence).
    """
    if args.all_years:
        explicit_year = "--year" in raw_argv
        if explicit_year:
            logger.warning(
                "Ignoring --year=%s because --all-years is set; "
                "using range [%s..%s] (newest first).",
                args.year,
                args.year_end,
                args.year_start,
            )
        years = list(range(args.year_end, args.year_start - 1, -1))
        logger.info(
            "Multi-year reverse mode: %d years, %s .. %s (newest first)",
            len(years),
            years[0] if years else "n/a",
            years[-1] if years else "n/a",
        )
        return years
    return [args.year]


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(description="Crawl + load BR team transactions.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--all-teams", action="store_true", help="run all 30 NBA teams")
    src.add_argument("--team", type=str, help="single team abbr, e.g. DET")

    # Season selection: either a single --year, or a full reverse range.
    p.add_argument(
        "--year",
        type=int,
        default=2026,
        help="season-end year for single-season mode (default 2026)",
    )
    p.add_argument(
        "--all-years",
        action="store_true",
        help="enable full-volume reverse crawl over the [year-start, year-end] range",
    )
    p.add_argument(
        "--year-start",
        type=int,
        default=1947,
        help="earliest season-end year for --all-years range (default 1947)",
    )
    p.add_argument(
        "--year-end",
        type=int,
        default=2026,
        help="latest season-end year for --all-years range, visited first (default 2026)",
    )

    p.add_argument(
        "--offline-dir",
        type=str,
        default=None,
        help="read <ABBR>_<year>_transactions(_raw).html from this dir instead of live",
    )
    args = p.parse_args(raw_argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    team_abbrs = TEAM_ABBRS if args.all_teams else [args.team.upper()]
    years = _build_years(args, raw_argv)
    _run(team_abbrs, years, args.offline_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
