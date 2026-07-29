"""Regression tests for ``merge_gamelog_cache`` in crawl_br_gamelog.py.

Background
----------
A bug was fixed in ``external_crawler/crawler/crawl_br_gamelog.py``: under
``--resume`` mode the local season cache ``gamelog_<season>.json`` was written
with OVERWRITE semantics, which shrank a re-scanned season to "only this round's
newly scraped players" (e.g. gamelog_1995.json dropped from ~390 players to 1).

The fix introduced ``merge_gamelog_cache(season, new_players, cache_dir)`` with
MERGE semantics: it reads any existing cache first and merges by ``player_id``
(same id -> new overrides old; different id -> appended) before writing back.

These tests are pure unit tests (no real crawler / DB / network). They use a
temporary cache dir per test and verify both the *count* of players after a
merge and the *content* of overridden players, so the fix is independently
proven rather than merely not crashing.

Run with the project venv:
    .venv/bin/python -m pytest tests/test_gamelog_cache_merge.py -v
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

PROJECT_ROOT = "/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _load_merge_gamelog_cache():
    """Import ``merge_gamelog_cache``.

    Tries the normal package import first. If that fails because of a
    top-level heavy dependency (e.g. ``common.player_page_cache``) that is not
    needed by ``merge_gamelog_cache``, falls back to loading the function from
    the source file directly with that dependency stubbed out. This keeps the
    test honest: it never silently skips because of an import failure.
    """
    try:
        from external_crawler.crawler.crawl_br_gamelog import merge_gamelog_cache
        return merge_gamelog_cache
    except Exception:  # pragma: no cover - fallback path only
        src_path = os.path.join(
            PROJECT_ROOT, "external_crawler", "crawler", "crawl_br_gamelog.py"
        )
        with open(src_path, encoding="utf-8") as fh:
            source = fh.read()
        # Replace the heavy top-level import with a harmless stub so exec does
        # not require that dependency (the merge function never uses it).
        source = source.replace(
            "import common.player_page_cache as player_page_cache",
            "player_page_cache = None  # stubbed for isolated test import",
        )
        namespace = {
            "os": os,
            "json": json,
            "sys": sys,
            "__name__": "crawl_br_gamelog_isolated",
        }
        exec(compile(source, src_path, "exec"), namespace)
        return namespace["merge_gamelog_cache"]


merge_gamelog_cache = _load_merge_gamelog_cache()


# --------------------------------------------------------------------------- #
# Test helpers
# --------------------------------------------------------------------------- #
def _player(pid, name, games):
    """Build a player entry shaped like the ones the crawler produces."""
    return {"player": name, "player_id": pid, "games": games}


def _cache_path(cache_dir: str, season: int) -> str:
    return os.path.join(cache_dir, f"gamelog_{season}.json")


def _write_cache(cache_dir: str, season: int, players, season_field=None):
    os.makedirs(cache_dir, exist_ok=True)
    payload = {"season": season if season_field is None else season_field,
               "players": players}
    with open(_cache_path(cache_dir, season), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def _read_cache(cache_dir: str, season: int) -> dict:
    with open(_cache_path(cache_dir, season), encoding="utf-8") as fh:
        return json.load(fh)


def _by_pid(players):
    return {p["player_id"]: p for p in players}


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #
def test_merge_preserves_existing_players(tmp_path):
    """Scenario 1 (core regression): MERGE must NOT shrink the cache.

    Old cache has [p1, p2(old games), p3]; new scrape is [p2(new games), p4].
    After merge there must be 4 players and p2 must carry the NEW games.
    """
    cache_dir = str(tmp_path)
    season = 1995

    old = [
        _player("p1", "Alice", [{"date": "1995-01-01", "pts": 10}]),
        _player("p2", "Bob", [{"date": "1995-01-02", "pts": 20}]),  # OLD games
        _player("p3", "Carol", [{"date": "1995-01-03", "pts": 30}]),
    ]
    _write_cache(cache_dir, season, old)

    new_games_p2 = [{"date": "1995-01-02", "pts": 99}]  # NEW (overriding) games
    new = [
        _player("p2", "Bob", new_games_p2),
        _player("p4", "Dave", [{"date": "1995-01-04", "pts": 40}]),
    ]

    merge_gamelog_cache(season, new, cache_dir)

    data = _read_cache(cache_dir, season)
    players = data["players"]
    assert data["season"] == season
    assert len(players) == 4, f"expected 4 players after merge, got {len(players)}"

    pids = {p["player_id"] for p in players}
    assert pids == {"p1", "p2", "p3", "p4"}, f"unexpected pids: {pids}"

    by = _by_pid(players)
    # p2 must reflect the NEW games (override, not a stale reference to old).
    assert by["p2"]["games"] == new_games_p2, "p2 games should be the new value"
    assert by["p2"]["games"] != old[1]["games"], "p2 should NOT keep old games"


def test_missing_old_cache_writes_new_only(tmp_path):
    """Scenario 2: no pre-existing cache -> simply write the new players."""
    cache_dir = str(tmp_path)
    season = 2000

    new = [
        _player("a", "A", [{"date": "2000-01-01"}]),
        _player("b", "B", [{"date": "2000-01-02"}]),
    ]
    out = merge_gamelog_cache(season, new, cache_dir)

    assert os.path.exists(out)
    data = _read_cache(cache_dir, season)
    assert len(data["players"]) == 2
    assert {p["player_id"] for p in data["players"]} == {"a", "b"}


def test_truncated_old_cache_treated_as_empty(tmp_path):
    """Scenario 3: a half-written (truncated) JSON cache must not crash and
    must be treated as empty -> result equals the new scrape count."""
    cache_dir = str(tmp_path)
    season = 1995
    # Write an incomplete JSON object (array never closed).
    with open(_cache_path(cache_dir, season), "w", encoding="utf-8") as fh:
        fh.write('{"season":1995,"players":[')

    new = [
        _player("x", "X", [{"date": "1995-01-01"}]),
        _player("y", "Y", [{"date": "1995-01-02"}]),
    ]
    # Must not raise despite corrupt on-disk cache.
    merge_gamelog_cache(season, new, cache_dir)

    data = _read_cache(cache_dir, season)
    assert len(data["players"]) == 2
    assert {p["player_id"] for p in data["players"]} == {"x", "y"}


def test_empty_valid_old_cache(tmp_path):
    """Scenario 4: a valid cache with an empty players list -> only new."""
    cache_dir = str(tmp_path)
    season = 1995
    _write_cache(cache_dir, season, [])  # {"season":1995,"players":[]}

    new = [_player("z", "Z", [{"date": "1995-01-01"}])]
    merge_gamelog_cache(season, new, cache_dir)

    data = _read_cache(cache_dir, season)
    assert len(data["players"]) == 1
    assert data["players"][0]["player_id"] == "z"


def test_duplicate_in_new_players_deduped(tmp_path):
    """Scenario 5: new batch contains a duplicate player_id -> dedupe by id,
    last value wins, never two entries with the same id."""
    cache_dir = str(tmp_path)
    season = 2010

    g_first = [{"date": "2010-01-01", "pts": 1}]
    g_last = [{"date": "2010-01-01", "pts": 2}]  # last value should win

    new = [
        _player("d", "Dup", g_first),
        _player("d", "Dup", g_last),  # same id, different games
        _player("e", "E", [{"date": "2010-01-02"}]),
    ]
    merge_gamelog_cache(season, new, cache_dir)

    data = _read_cache(cache_dir, season)
    players = data["players"]
    assert len(players) == 2, f"duplicate id should be deduped; got {len(players)}"

    pids = [p["player_id"] for p in players]
    assert len(pids) == len(set(pids)), "duplicate player_id must not appear"

    by = _by_pid(players)
    assert by["d"]["games"] == g_last, "last value should win for duplicate id"


def test_multi_round_accumulation(tmp_path):
    """Scenario 6: repeated merges must accumulate across rounds and must
    never be shrunk to 'only this round's players'."""
    cache_dir = str(tmp_path)
    season = 1996

    # Round 1: old empty + 3 new.
    r1 = [
        _player("r1a", "A", [{"date": "1996-01-01"}]),
        _player("r1b", "B", [{"date": "1996-01-02", "pts": 1}]),
        _player("r1c", "C", [{"date": "1996-01-03"}]),
    ]
    merge_gamelog_cache(season, r1, cache_dir)
    after_r1 = _read_cache(cache_dir, season)
    assert len(after_r1["players"]) == 3

    # Round 2: old 3 + 2 new (one overlaps r1b and is overridden).
    r1b_new_games = [{"date": "1996-01-02", "pts": 999}]
    r2 = [
        _player("r1b", "B", r1b_new_games),  # overlap -> override
        _player("r2d", "D", [{"date": "1996-01-04"}]),
    ]
    merge_gamelog_cache(season, r2, cache_dir)
    after_r2 = _read_cache(cache_dir, season)

    players = after_r2["players"]
    assert len(players) == 4, (
        f"multi-round merge should accumulate to 4, got {len(players)}"
    )
    pids = {p["player_id"] for p in players}
    assert pids == {"r1a", "r1b", "r1c", "r2d"}, f"unexpected pids: {pids}"

    by = _by_pid(players)
    assert by["r1b"]["games"] == r1b_new_games, "r1b should reflect round-2 override"


def test_structurally_broken_cache_missing_players_key(tmp_path):
    """Scenario 7a: cache is valid JSON but missing the 'players' key."""
    cache_dir = str(tmp_path)
    season = 1995
    # Valid dict, but no "players" key at all.
    with open(_cache_path(cache_dir, season), "w", encoding="utf-8") as fh:
        json.dump({"season": season}, fh)

    new = [_player("m", "M", [{"date": "1995-01-01"}])]
    merge_gamelog_cache(season, new, cache_dir)

    data = _read_cache(cache_dir, season)
    assert len(data["players"]) == 1
    assert data["players"][0]["player_id"] == "m"


def test_structurally_broken_cache_players_not_list(tmp_path):
    """Scenario 7b: cache has 'players' but it is not a list."""
    cache_dir = str(tmp_path)
    season = 1995
    with open(_cache_path(cache_dir, season), "w", encoding="utf-8") as fh:
        json.dump({"season": season, "players": "not-a-list"}, fh)

    new = [
        _player("n", "N", [{"date": "1995-01-01"}]),
        _player("o", "O", [{"date": "1995-01-02"}]),
    ]
    merge_gamelog_cache(season, new, cache_dir)

    data = _read_cache(cache_dir, season)
    assert len(data["players"]) == 2
    assert {p["player_id"] for p in data["players"]} == {"n", "o"}


def test_creates_cache_dir_if_missing(tmp_path):
    """Bonus: a non-existent (nested) cache dir should be created."""
    cache_dir = str(tmp_path / "nested" / "sub")
    season = 2022
    assert not os.path.isdir(cache_dir)

    new = [_player("c", "C", [{"date": "2022-01-01"}])]
    out = merge_gamelog_cache(season, new, cache_dir)

    assert os.path.isdir(cache_dir)
    assert os.path.exists(out)
    data = _read_cache(cache_dir, season)
    assert len(data["players"]) == 1
