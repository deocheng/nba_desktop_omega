"""Tests for the games.game_id -> BR migration (T05).

Prerequisite: scripts/migrate_games_gameid_to_br.py has already been run
against the live PostgreSQL.  These tests verify:
  1. Migration shape — recent seasons use BR or numeric game_id, no duplicates.
  2. get_game_detail() resolves a migrated BR game_id and returns data.
  3. BR game_id joins back to player_gamelog / play_by_play via nba_api_id
     (radar / play-by-play / player-performance all return data).
  4. Legacy numeric game_id (older seasons) still works via the fallback path.

Run:
    env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
        .venv/Scripts/python.exe -m pytest tests/test_gameid_migration.py -v
"""
from __future__ import annotations

import re

import pytest

from backend.core.db import batch_query
from backend.data_layer.game_loader import (
    _resolve_join_key,
    get_game_detail,
    get_game_player_performance,
    get_game_radar,
    get_play_by_play,
)

BR_RE = re.compile(r"^\d{8,}[A-Z]{3}$")
NUMERIC_RE = re.compile(r"^\d+$")
RECENT: tuple[int, int] = (2025, 2026)


@pytest.fixture(scope="module")
def br_sample(db_available) -> str:
    """A migrated recent-season BR game_id that has gamelog + pbp rows."""
    if not db_available:
        pytest.skip("PostgreSQL not available")
    rows = batch_query(
        """
        SELECT g.game_id FROM games g
        WHERE g.season IN %s AND g.game_id ~ %s
          AND EXISTS (
              SELECT 1 FROM player_gamelog pg
              WHERE pg.gameid = g.nba_api_id::text)
          AND EXISTS (
              SELECT 1 FROM play_by_play p
              WHERE p.gameid = g.nba_api_id::text)
        LIMIT 1
        """,
        (RECENT, BR_RE.pattern),
    )
    if not rows:
        pytest.skip("No recent BR game with gamelog+pbp data found")
    return rows[0]["game_id"]


@pytest.fixture(scope="module")
def legacy_numeric(db_available) -> str:
    """A legacy (non-recent) numeric game_id for fallback testing."""
    if not db_available:
        pytest.skip("PostgreSQL not available")
    rows = batch_query(
        "SELECT game_id FROM games WHERE season NOT IN %s AND game_id ~ %s LIMIT 1",
        (RECENT, NUMERIC_RE.pattern),
    )
    if not rows:
        pytest.skip("No legacy numeric game_id found")
    return rows[0]["game_id"]


@pytest.mark.needs_db
def test1_migrated_shape(db_available) -> None:
    """Recent seasons: game_id is BR or numeric; no duplicate game_id."""
    if not db_available:
        pytest.skip("PostgreSQL not available")

    dup = batch_query(
        """
        SELECT count(*) AS c FROM (
            SELECT game_id FROM games WHERE season IN %s
            GROUP BY game_id HAVING count(*) > 1
        ) d
        """,
        (RECENT,),
    )[0]["c"]
    assert dup == 0, f"duplicate game_id in recent seasons: {dup}"

    rows = batch_query(
        "SELECT game_id FROM games WHERE season IN %s", (RECENT,)
    )
    bad = [
        r["game_id"]
        for r in rows
        if not (BR_RE.match(r["game_id"]) or NUMERIC_RE.match(r["game_id"]))
    ]
    assert not bad, f"non-standard game_id values: {bad[:5]}"


@pytest.mark.needs_db
def test2_br_detail(br_sample: str) -> None:
    """get_game_detail returns non-empty for a migrated BR game_id."""
    detail = get_game_detail(br_sample)
    assert detail, f"get_game_detail returned empty for BR id {br_sample}"
    assert detail.get("game_id") == br_sample


@pytest.mark.needs_db
def test3_br_joins(br_sample: str) -> None:
    """BR id resolves via nba_api_id to gamelog/pbp (radar/pbp/players)."""
    radar = get_game_radar(br_sample)
    assert radar, "get_game_radar returned empty"

    pbp = get_play_by_play(br_sample)
    assert isinstance(pbp, list) and len(pbp) > 0, "play_by_play empty"

    perf = get_game_player_performance(br_sample)
    assert isinstance(perf, list), "get_game_player_performance should return a list"

    # join key must be the numeric nba_api_id, not the BR id
    key = _resolve_join_key(br_sample)
    assert NUMERIC_RE.match(key), f"join key should be numeric, got {key!r}"


@pytest.mark.needs_db
def test4_legacy_fallback(legacy_numeric: str) -> None:
    """Legacy numeric game_id still resolves via the fallback path."""
    detail = get_game_detail(legacy_numeric)
    assert detail, f"get_game_detail returned empty for legacy id {legacy_numeric}"
    assert detail.get("game_id") == legacy_numeric

    key = _resolve_join_key(legacy_numeric)
    assert NUMERIC_RE.match(key), f"legacy join key should be numeric, got {key!r}"
