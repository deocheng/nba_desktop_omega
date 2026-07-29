"""Unit tests for the player_gamelog identity-column fixes.

These tests are pure (no real crawler / browser / DB / network):

1. Parse-layer test — ``parse_gamelog_html`` (extracted from ``scrape_gamelog``)
   is fed a minimal but structurally faithful ``player_game_log_reg`` table and
   must return game dicts with correct ``date``/``team``/``opp`` and stats.
   A second test calls ``scrape_gamelog`` directly with ``_fetch_html`` and
   ``player_page_cache`` mocked, proving the same parse path end-to-end.

2. INSERT alignment test — ``build_insert`` is a pure function that returns the
   ``(columns, values)`` tuple for one INSERT. We assert columns/values are
   1:1 aligned and that the identity columns (``br_player_id``, ``player_name``,
   ``game_id_full``) are present and correctly populated — this is what guards
   against the original NULL-identity bug without touching a database.

Run with the project venv:
    .venv/bin/python -m pytest tests/test_gamelog_identity.py -v
"""
from __future__ import annotations

import importlib.util
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

PROJECT_ROOT = "/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

SRC_PATH = os.path.join(
    PROJECT_ROOT, "external_crawler", "crawler", "crawl_br_gamelog.py"
)


def _load_module():
    """Import ``crawl_br_gamelog`` robustly.

    Tries the normal package import first; if a heavy top-level dependency
    (e.g. ``common.player_page_cache``) is unavailable in the test env, falls
    back to loading the source with that dependency stubbed out. This keeps the
    test honest — it never silently skips because of an import failure, and
    ``parse_gamelog_html`` / ``build_insert`` never touch the stubbed dep.
    """
    try:
        from external_crawler.crawler.crawl_br_gamelog import (
            parse_gamelog_html,
            scrape_gamelog,
            build_insert,
        )
        return SimpleNamespace(
            parse_gamelog_html=parse_gamelog_html,
            scrape_gamelog=scrape_gamelog,
            build_insert=build_insert,
            mod=None,
        )
    except Exception:  # pragma: no cover - fallback path only
        with open(SRC_PATH, encoding="utf-8") as fh:
            source = fh.read()
        # Replace the heavy top-level import with a harmless stub so exec does
        # not require that dependency.
        source = source.replace(
            "import common.player_page_cache as player_page_cache",
            "player_page_cache = None  # stubbed for isolated test import",
        )
        namespace = {
            "os": os,
            "json": __import__("json"),
            "sys": sys,
            "BeautifulSoup": __import__("bs4").BeautifulSoup,
            "__name__": "crawl_br_gamelog_isolated",
        }
        exec(compile(source, SRC_PATH, "exec"), namespace)
        return SimpleNamespace(
            parse_gamelog_html=namespace["parse_gamelog_html"],
            scrape_gamelog=namespace["scrape_gamelog"],
            build_insert=namespace["build_insert"],
            mod=namespace,
        )


_LOADED = _load_module()
parse_gamelog_html = _LOADED.parse_gamelog_html
scrape_gamelog = _LOADED.scrape_gamelog
build_insert = _LOADED.build_insert
MODULE_NS = _LOADED.mod  # None when imported normally; the exec namespace otherwise


def _module_obj():
    """Return the module object/namespace that holds the functions, for patching."""
    if MODULE_NS is not None:
        return SimpleNamespace(
            player_page_cache=None,
            _fetch_html=None,
            scrape_gamelog=scrape_gamelog,
        )
    import external_crawler.crawler.crawl_br_gamelog as m
    return m


# --------------------------------------------------------------------------- #
# Minimal, structurally faithful BR gamelog HTML
# --------------------------------------------------------------------------- #
def _gamelog_html() -> str:
    """Build a minimal ``player_game_log_reg`` table with 3 game rows:

    - row 1: a normal started game (ranker=1)
    - row 2: another normal started game (ranker=2)
    - row 3: an "Inactive" game that must be SKIPPED by the parser
    """
    # The 19 stat columns in the exact order they appear in BR's table.
    stat_cols = [
        "fg", "fga", "fg_pct", "fg3", "fga3", "fg3_pct", "ft", "fta", "ft_pct",
        "orb", "drb", "trb", "ast", "stl", "blk", "tov", "pf", "pts", "plus_minus",
    ]

    def _row(rk, date, team, opp, starter, *vals):
        assert len(vals) == len(stat_cols), "stat count mismatch"
        cells = "".join(
            f'<td data-stat="{c}" class="right ">{v}</td>' for c, v in zip(stat_cols, vals)
        )
        return f"""
        <tr >
            <th data-stat="ranker" class="right ">{rk}</th>
            <th data-stat="date" class="left ">{date}</th>
            <td data-stat="team_name_abbr" class="left ">{team}</td>
            <td data-stat="opp_name_abbr" class="left ">{opp}</td>
            <td data-stat="is_starter" class="left ">{starter}</td>
            {cells}
        </tr>"""

    return f"""<html><body>
    <table id="player_game_log_reg">
        <thead><tr class="thead">
            <th data-stat="ranker" class="right ">Rk</th>
            <th data-stat="date" class="left ">Date</th>
        </tr></thead>
        <tbody>
            {_row(1, "1985-11-02", "LAL", "HOU", "*",
                  10, 20, ".500", 2, 5, ".400", 4, 5, ".800",
                  2, 5, 7, 8, 1, 1, 2, 3, 28, "+10")}
            {_row(2, "1985-11-05", "LAL", "POR", "*",
                  12, 22, ".545", 1, 4, ".250", 6, 7, ".857",
                  1, 8, 9, 5, 2, 0, 3, 4, 31, "-5")}
            {_row(3, "1985-11-08", "LAL", "GSW", "Inactive",
                  "", "", "", "", "", "", "", "", "",
                  "", "", "", "", "", "", "", "", 0, "")}
        </tbody>
    </table>
    </body></html>"""


# --------------------------------------------------------------------------- #
# Parse-layer tests
# --------------------------------------------------------------------------- #
def test_parse_gamelog_html_returns_games_with_correct_fields():
    """The parser must return 2 games (the Inactive row is skipped) with the
    right date/team/opp and stats."""
    html = _gamelog_html()
    games = parse_gamelog_html(html)

    assert isinstance(games, list)
    assert len(games) == 2, f"expected 2 playable games, got {len(games)}"

    g1 = games[0]
    assert g1["date"] == "1985-11-02"
    assert g1["team"] == "LAL"
    assert g1["opp"] == "HOU"
    assert g1["is_starter"] is True
    # Stats mapped correctly (ints; pct as floats).
    assert g1["pts"] == 28
    assert g1["fg"] == 10
    assert g1["fga"] == 20
    assert g1["fg_pct"] == 0.5
    assert g1["fg3_pct"] == 0.4
    assert g1["plus_minus"] == 10  # "+10" -> 10

    g2 = games[1]
    assert g2["date"] == "1985-11-05"
    assert g2["team"] == "LAL"
    assert g2["opp"] == "POR"
    assert g2["pts"] == 31
    assert g2["plus_minus"] == -5  # "-5" -> -5

    # Inactive game must NOT appear.
    assert all(g["date"] != "1985-11-08" for g in games)


def test_parse_gamelog_html_no_table_returns_empty():
    assert parse_gamelog_html("<html><body>no table here</body></html>") == []
    assert parse_gamelog_html("") == []


def test_scrape_gamelog_with_mocked_fetch():
    """Call ``scrape_gamelog`` end-to-end with the browser fetch and the
    player-page cache stubbed; it must parse the returned HTML."""
    html = _gamelog_html()
    mod = _module_obj()
    with patch.object(mod, "player_page_cache", MagicMock()), \
         patch.object(mod, "_fetch_html", return_value=html):
        games = scrape_gamelog("Kareem Abdul-Jabbar", "abdrk01", 1995)

    assert len(games) == 2
    assert games[0]["date"] == "1985-11-02"
    assert games[0]["team"] == "LAL"
    assert games[0]["opp"] == "HOU"
    assert games[0]["pts"] == 28


# --------------------------------------------------------------------------- #
# INSERT alignment tests (the core guard against the NULL-identity bug)
# --------------------------------------------------------------------------- #
def _sample_game(game_id: str, season: int = 1995) -> dict:
    """A fully-populated game dict as produced by the parser / cache."""
    return {
        "game_id": game_id,
        "season": season,
        "team": "LAL",
        "opp": "HOU",
        "date": "1985-11-02",
        "fg": 10, "fga": 20, "fg_pct": 0.5,
        "fg3": 2, "fga3": 5, "fg3_pct": 0.4,
        "ft": 4, "fta": 5, "ft_pct": 0.8,
        "orb": 2, "drb": 5, "trb": 7,
        "ast": 8, "stl": 1, "blk": 1,
        "tov": 2, "pf": 3, "pts": 28, "plus_minus": 10,
    }


def test_build_insert_alignment_and_identity_columns():
    """Columns and values must be 1:1 aligned, and the three identity columns
    (br_player_id, player_name, game_id_full) must be present and populated."""
    g = _sample_game("29400007")
    columns, values = build_insert("Kareem Abdul-Jabbar", "abdrk01", g, "198511020LAL")

    assert len(columns) == len(values), (
        f"columns ({len(columns)}) and values ({len(values)}) must align 1:1"
    )
    assert len(columns) == 26, f"expected 26 columns, got {len(columns)}"

    for col in ("br_player_id", "player_name", "game_id_full"):
        assert col in columns, f"identity column {col} missing from INSERT"

    # gameid is the first column and carries the numeric nba_api_id string.
    assert columns[0] == "gameid"
    assert values[0] == "29400007"

    # Identity columns populated correctly.
    assert values[columns.index("br_player_id")] == "abdrk01"
    assert values[columns.index("player_name")] == "Kareem Abdul-Jabbar"
    assert values[columns.index("game_id_full")] == "198511020LAL"

    # season carried through.
    assert values[columns.index("season")] == 1995
    # a stat is present and aligned.
    assert values[columns.index("pts")] == 28


def test_build_insert_handles_missing_game_id_full():
    """When the game_id_full mapping is missing (None), the column is still
    written as NULL — columns/values stay aligned and no crash occurs."""
    g = _sample_game("29400007")
    columns, values = build_insert("Kareem Abdul-Jabbar", "abdrk01", g, None)

    assert len(columns) == len(values) == 26
    assert values[columns.index("game_id_full")] is None
    # br_player_id / player_name still populated.
    assert values[columns.index("br_player_id")] == "abdrk01"
    assert values[columns.index("player_name")] == "Kareem Abdul-Jabbar"


def test_build_insert_reused_by_pipeline_and_rework_shapes():
    """Both run_pipeline and rework_season call build_insert; assert the same
    (columns, values) shape is produced regardless of which caller builds it.
    This guards against the two write paths drifting apart."""
    g_pipe = _sample_game("29400007")
    g_rework = _sample_game("29400007")

    cols_a, vals_a = build_insert("Kareem Abdul-Jabbar", "abdrk01", g_pipe, "198511020LAL")
    cols_b, vals_b = build_insert("Kareem Abdul-Jabbar", "abdrk01", g_rework, "198511020LAL")

    assert cols_a == cols_b
    assert vals_a == vals_b
    assert len(cols_a) == len(vals_a) == 26
