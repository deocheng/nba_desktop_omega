"""hof_exec/load.py — upsert parsed rows + load from gold fixtures.

Upsert semantics (idempotent re-runs):
  * ``team_hof``        unique (team_abbr, season, player_name)
  * ``team_executives`` unique (team_abbr, rk)
On conflict we refresh ``br_slug`` / ``notes`` and bump ``scraped_at``.
"""

from __future__ import annotations

import csv
import json
import logging
from typing import List, Tuple

from .config import get_conn
from .parse import ExecEntry, HofEntry

logger = logging.getLogger(__name__)


def upsert_hof(rows: List[HofEntry]) -> int:
    """Upsert a list of HofEntry into ``team_hof``. Returns rows written."""
    if not rows:
        return 0
    sql = """
        INSERT INTO team_hof (team_abbr, season, player_name, br_slug, scraped_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (team_abbr, season, player_name)
        DO UPDATE SET br_slug = EXCLUDED.br_slug, scraped_at = now()
    """
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.executemany(
                    sql,
                    [(r.team_abbr, r.season, r.player_name, r.br_slug) for r in rows],
                )
        return len(rows)
    finally:
        conn.close()


def upsert_executives(rows: List[ExecEntry]) -> int:
    """Upsert a list of ExecEntry into ``team_executives``. Returns rows written."""
    if not rows:
        return 0
    sql = """
        INSERT INTO team_executives (team_abbr, rk, executive, start, "end", notes, scraped_at)
        VALUES (%s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (team_abbr, rk)
        DO UPDATE SET executive = EXCLUDED.executive,
                      start    = EXCLUDED.start,
                      "end"    = EXCLUDED."end",
                      notes    = EXCLUDED.notes,
                      scraped_at = now()
    """
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.executemany(
                    sql,
                    [
                        (r.team_abbr, r.rk, r.executive, r.start, r.end, r.notes)
                        for r in rows
                    ],
                )
        return len(rows)
    finally:
        conn.close()


def load_from_gold(team_abbr: str, json_path: str, csv_path: str) -> Tuple[int, int]:
    """Load HOF (from gold json) + executives (from gold csv) for one team.

    Returns ``(hof_rows, exec_rows)`` counts upserted. ``br_slug`` is left
    ``None`` because the gold json only carries (season, player) pairs.
    """
    # --- HOF from gold json ---
    with open(json_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    hof_rows: List[HofEntry] = []
    for season, player in data.get("season_entries", []):
        hof_rows.append(
            HofEntry(team_abbr=team_abbr, season=season, player_name=player, br_slug=None)
        )
    n_hof = upsert_hof(hof_rows)

    # --- Executives from gold csv (quoted fields, may contain a duplicate header) ---
    exec_rows: List[ExecEntry] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # skip header
        for cells in reader:
            if not cells:
                continue
            if cells[0].strip() == "Rk":
                continue  # duplicate header row
            try:
                rk = int(cells[0])
            except (ValueError, IndexError):
                logger.warning("load_from_gold: skip non-numeric rk %r", cells)
                continue
            executive = cells[1] if len(cells) > 1 else ""
            start = cells[2] if len(cells) > 2 else ""
            end = cells[3] if len(cells) > 3 else ""
            notes = cells[4] if len(cells) > 4 else ""
            exec_rows.append(
                ExecEntry(
                    team_abbr=team_abbr,
                    rk=rk,
                    executive=executive,
                    start=start,
                    end=end,
                    notes=notes or None,
                )
            )
    n_exec = upsert_executives(exec_rows)
    return n_hof, n_exec
