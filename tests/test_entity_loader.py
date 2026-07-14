"""NBACore v8 — Entity aggregation loader tests (Layer 1).

Covers season_label + season discovery + game grouping aggregation.
v8 §6: no mocking of engine core; DB-dependent tests use a live connection
(skipped if PostgreSQL is unavailable).
"""
from __future__ import annotations

import pytest

from backend.data_layer import entity_loader
from backend.data_layer.entity_loader import (
    load_player_games_aggregated,
    load_player_seasons,
    load_team_games_aggregated,
    load_team_seasons,
    season_label,
)

_KNOWN_PLAYER = "greenac01"  # verified to have 2026 gamelog
_KNOWN_TEAM = "HOU"

try:
    from backend.core.db import ping as _db_ping
    _DB_AVAILABLE = _db_ping()
except Exception:
    _DB_AVAILABLE = False

needs_db = pytest.mark.skipif(
    not _DB_AVAILABLE,
    reason="needs live PostgreSQL (set DB_PORT and start service)",
)


class TestSeasonLabel:
    def test_matches_frontend_convention(self):
        assert season_label(2026) == "2025-26"
        assert season_label(2025) == "2024-25"
        assert season_label(2019) == "2018-19"

    def test_pads_two_digit_end(self):
        assert season_label(2001) == "2000-01"


class TestPlayerSeasons:
    @needs_db
    def test_returns_descending_ints(self):
        seasons = load_player_seasons(_KNOWN_PLAYER)
        assert seasons, "expected non-empty season list"
        assert all(isinstance(s, int) for s in seasons)
        assert seasons == sorted(seasons, reverse=True)

    @needs_db
    def test_filters_null_seasons(self):
        seasons = load_player_seasons(_KNOWN_PLAYER)
        assert None not in seasons

    def test_empty_for_blank_id(self):
        assert load_player_seasons("") == []


class TestTeamSeasons:
    @needs_db
    def test_returns_ints(self):
        seasons = load_team_seasons(_KNOWN_TEAM)
        assert seasons
        assert all(isinstance(s, int) for s in seasons)

    @needs_db
    def test_divergent_abbr_matches_both_forms(self):
        # BKN (NBA) and BRK (BR) refer to the same franchise in dim_games
        a = load_team_seasons("BKN")
        b = load_team_seasons("BRK")
        assert a == b
        assert a


class TestPlayerGamesAggregated:
    @needs_db
    def test_month_grouping_structure(self):
        agg = load_player_games_aggregated(_KNOWN_PLAYER, 2026, "month")
        assert "groups" in agg and "totals" in agg
        assert agg["totals"]["gp"] > 0
        for g in agg["groups"]:
            assert set(g.keys()) >= {"key", "label", "games", "aggregate"}
            assert g["aggregate"]["gp"] == len(g["games"])
            for gm in g["games"]:
                assert set(gm.keys()) == {"game_id", "game_date", "opponent", "is_home", "result", "pts"}

    @needs_db
    def test_week_grouping_non_empty(self):
        agg = load_player_games_aggregated(_KNOWN_PLAYER, 2026, "week")
        assert len(agg["groups"]) > 0

    @needs_db
    def test_game_granularity_group_count_equals_gp(self):
        agg = load_player_games_aggregated(_KNOWN_PLAYER, 2026, "game")
        assert len(agg["groups"]) == agg["totals"]["gp"]

    def test_invalid_granularity_raises(self):
        with pytest.raises(ValueError):
            load_player_games_aggregated(_KNOWN_PLAYER, 2026, "quarter")


class TestTeamGamesAggregated:
    @needs_db
    def test_month_grouping_structure(self):
        agg = load_team_games_aggregated(_KNOWN_TEAM, 2026, "month")
        assert agg["totals"]["gp"] > 0
        for g in agg["groups"]:
            assert g["aggregate"]["gp"] == len(g["games"])
            for gm in g["games"]:
                assert gm["opponent"] is not None
                assert gm["result"] in ("W", "L", "T")

    @needs_db
    def test_divergent_abbr_team_games(self):
        agg = load_team_games_aggregated("BKN", 2026, "month")
        assert agg["totals"]["gp"] >= 0  # may be 0 if no 2026 games, must not error

    def test_invalid_granularity_raises(self):
        with pytest.raises(ValueError):
            load_team_games_aggregated(_KNOWN_TEAM, 2026, "quarter")
