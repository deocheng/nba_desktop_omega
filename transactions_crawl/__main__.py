"""transactions_crawl/__main__ — CLI to crawl + load BR team transactions.

Examples
--------
Offline (sandbox / verified), single team:
    python -m transactions_crawl --offline-dir det2026_br --team DET --year 2026

Live, all 30 teams (run on the user's Mac — CF blocks the sandbox):
    python -m transactions_crawl --all-teams --year 2026
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


def _run(team_abbrs: list[str], year: int, offline_dir: str | None) -> int:
    total = 0
    for abbr in team_abbrs:
        try:
            html = fetch_transactions_page(abbr, year, offline_dir=offline_dir)
        except FileNotFoundError as exc:
            logger.warning("SKIP %s/%s: %s", abbr, year, exc)
            continue
        if looks_like_404(html):
            logger.warning("SKIP %s/%s: 404 page detected", abbr, year)
            continue
        rows = parse_transactions(html, team_abbr=abbr)
        n = upsert_transactions(rows)
        total += n
        logger.info("LOADED %s/%s: %d rows", abbr, year, n)
    logger.info("DONE totals: transactions=%d", total)
    return total


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Crawl + load BR team transactions.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--all-teams", action="store_true", help="run all 30 NBA teams")
    src.add_argument("--team", type=str, help="single team abbr, e.g. DET")
    p.add_argument("--year", type=int, default=2026, help="season-end year (default 2026)")
    p.add_argument(
        "--offline-dir",
        type=str,
        default=None,
        help="read <ABBR>_<year>_transactions(_raw).html from this dir instead of live",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    team_abbrs = TEAM_ABBRS if args.all_teams else [args.team.upper()]
    _run(team_abbrs, args.year, args.offline_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
