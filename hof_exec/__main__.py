"""hof_exec/__main__ — CLI to crawl + load BR team HOF / executives.

Examples
--------
Offline (sandbox / verified), single team:
    python -m hof_exec --offline-dir det2026_br --team DET --kind both

Live, all 30 teams (run on the user's Mac — CF blocks the sandbox):
    python -m hof_exec --all-teams --kind both
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import TEAM_ABBRS
from .fetch import fetch_team_page, looks_like_404
from .load import upsert_executives, upsert_hof
from .parse import parse_executives_table, parse_hof_div

logger = logging.getLogger("hof_exec")


def _run(team_abbrs: list[str], kind: str, offline_dir: str | None) -> dict:
    kinds = ["hof", "executives"] if kind == "both" else [kind]
    total = {"hof": 0, "executives": 0}
    for abbr in team_abbrs:
        for k in kinds:
            try:
                html = fetch_team_page(abbr, k, offline_dir=offline_dir)
            except FileNotFoundError as exc:
                logger.warning("SKIP %s/%s: %s", abbr, k, exc)
                continue
            if looks_like_404(html):
                logger.warning("SKIP %s/%s: 404 page detected", abbr, k)
                continue
            if k == "hof":
                rows = parse_hof_div(html, team_abbr=abbr)
                n = upsert_hof(rows)
            else:
                rows = parse_executives_table(html, team_abbr=abbr)
                n = upsert_executives(rows)
            total[k] += n
            logger.info("LOADED %s/%s: %d rows", abbr, k, n)
    logger.info("DONE totals: hof=%d executives=%d", total["hof"], total["executives"])
    return total


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Crawl + load BR team HOF / executives.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--all-teams", action="store_true", help="run all 30 NBA teams")
    src.add_argument("--team", type=str, help="single team abbr, e.g. DET")
    p.add_argument(
        "--offline-dir",
        type=str,
        default=None,
        help="read <ABBR>_<kind>.html from this dir instead of live fetching",
    )
    p.add_argument("--kind", choices=["hof", "executives", "both"], default="both")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    team_abbrs = TEAM_ABBRS if args.all_teams else [args.team.upper()]
    _run(team_abbrs, args.kind, args.offline_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
