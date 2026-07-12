"""NBACore v8.2-A — Intelligence Engine (Core) unit tests.

Covers the four v8.2-A capabilities:
    §5  Pace Adjustment
    §7  Availability Intelligence
    §12 Season Type Separation
    §16 Historical Percentile Ranking

Pure helpers are tested deterministically; DB-backed wrappers are tested
against the live PostgreSQL `nba` database (same instance used by the app).
Run with:  pytest tests/test_phase82_intelligence.py -q
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.services.intelligence_engine import (
    availability_score,
    compute_availability,
    compute_league_pace,
    compute_team_paces,
    historical_percentile,
    league_pace,
    load_player_intel,
    minutes_share,
    normalize_season_type,
    pace_adjust,
    pace_adjust_player_stats,
    percentile_rank,
    team_pace,
    team_possessions,
)


# ── §12 Season Type Separation ──

class TestSeasonType:
    def test_normalize_canonical(self):
        assert normalize_season_type("Regular") == "Regular"
        assert normalize_season_type("Playoffs") == "Playoffs"

    @pytest.mark.parametrize("raw,expected", [
        ("regular", "Regular"),
        ("REG", "Regular"),
        ("playoffs", "Playoffs"),
        ("PLAY_IN", "PlayIn"),
        ("play-in", "PlayIn"),
        (None, "Regular"),
    ])
    def test_normalize_aliases(self, raw, expected):
        assert normalize_season_type(raw) == expected

    def test_normalize_invalid_raises(self):
        with pytest.raises(ValueError):
            normalize_season_type("finals")


# ── §5 Pace Adjustment (pure) ──

class TestPacePure:
    def _team(self, fga, orb, tov, fta, mp):
        return {"fga": fga, "orb": orb, "tov": tov, "fta": fta, "mp": mp}

    def test_team_possessions(self):
        # 100 - 10 + 15 + 0.44*30 = 105 + 13.2 = 118.2
        assert team_possessions(self._team(100, 10, 15, 30, 240)) == pytest.approx(118.2)

    def test_team_pace(self):
        # poss=118.2, mp=240 -> 240*118.2/240 = 118.2
        t = self._team(100, 10, 15, 30, 240)
        assert team_pace(t) == pytest.approx(118.2)

    def test_team_pace_zero_minutes(self):
        t = self._team(100, 10, 15, 30, 0)
        assert team_pace(t) == 0.0

    def test_league_pace_minutes_weighted(self):
        rows = [self._team(100, 10, 15, 30, 240), self._team(200, 20, 30, 60, 480)]
        # tot_poss = 118.2 + 236.4 = 354.6 ; tot_mp = 720
        # pace = 240 * 354.6 / 720 = 118.2
        assert league_pace(rows) == pytest.approx(118.2)

    def test_pace_adjust(self):
        # value 20, lg/team = 110/100 -> 22
        assert pace_adjust(20.0, 110.0, 100.0) == pytest.approx(22.0)

    def test_pace_adjust_zero_team_pace_returns_original(self):
        assert pace_adjust(20.0, 110.0, 0.0) == pytest.approx(20.0)


# ── §5 Pace Adjustment (DB) ──

class TestPaceDB:
    def test_league_pace_realistic(self):
        lg = compute_league_pace(2025)
        # NBA league pace is ~95-110 possessions/48min
        assert 90.0 < lg < 115.0

    def test_team_paces_nonempty(self):
        paces = compute_team_paces(2025)
        assert len(paces) >= 28  # ~30 teams
        assert all(80.0 < p < 120.0 for p in paces.values())

    def test_pace_adjust_player_stats_keys(self):
        out = pace_adjust_player_stats(2025, ["jamesle01"], "Regular")
        assert "jamesle01" in out
        rec = out["jamesle01"]
        for k in ("team", "league_pace", "team_pace",
                  "adjusted_points", "adjusted_assists",
                  "adjusted_rebounds", "adjusted_usage"):
            assert k in rec
        # LAL plays slightly slower than league -> adjusted points >= raw-ish
        assert rec["adjusted_points"] is not None and rec["adjusted_points"] > 0
        # ratio sanity: adjusted_points should be close to raw PPG (24.4)
        assert 20.0 < rec["adjusted_points"] < 30.0

    def test_season_type_filter_real(self):
        reg = load_player_intel(2025, "Regular")
        po = load_player_intel(2025, "Playoffs")
        assert len(reg) > 0
        assert len(po) > 0  # playoff rows exist for 2025 season


# ── §7 Availability (pure + DB) ──

class TestAvailability:
    def test_availability_score(self):
        assert availability_score(70, 82) == pytest.approx(70 / 82)
        # clip upper bound
        assert availability_score(90, 82) == pytest.approx(1.0)
        # zero team games -> 0
        assert availability_score(70, 0) == 0.0

    def test_minutes_share(self):
        assert minutes_share(2000, 19830) == pytest.approx(2000 / 19830)
        # below 1.0 is NOT clipped
        assert minutes_share(5000, 19830) == pytest.approx(5000 / 19830)
        # above 1.0 IS clipped
        assert minutes_share(25000, 19830) == pytest.approx(1.0)
        assert minutes_share(100, 0) == 0.0

    def test_compute_availability_lebron(self):
        out = compute_availability(2025, ["jamesle01"], "Regular")
        assert "jamesle01" in out
        rec = out["jamesle01"]
        # LeBron 2025: 70 of 82 games, 2444 minutes
        assert rec["g"] == 70
        assert rec["mp"] == pytest.approx(2444.0)
        assert rec["team_games"] == pytest.approx(82.0)
        assert rec["availability"] == pytest.approx(70 / 82, abs=1e-3)
        assert 0.10 < rec["minutes_share"] < 0.20  # ~12%


# ── §16 Historical Percentile (pure + DB) ──

class TestHistoricalPercentile:
    def test_percentile_rank_mean_convention(self):
        dist = np.array([10, 20, 20, 30, 40])
        # value 20 ties at positions 2-3 -> mean rank (1+0.5*2)/5 = 40%
        assert percentile_rank(20, dist) == pytest.approx(40.0)
        # value 5 -> 0%
        assert percentile_rank(5, dist) == pytest.approx(0.0)
        # value 40 (max) -> mean rank (4+0.5)/5 = 90%
        assert percentile_rank(40, dist) == pytest.approx(90.0)

    def test_percentile_rank_empty(self):
        assert percentile_rank(10, np.array([])) == 0.0

    def test_historical_percentile_lebron(self):
        hp = historical_percentile(2025, "ppg", ["jamesle01"], "Regular")
        assert "jamesle01" in hp
        rec = hp["jamesle01"]
        assert 90.0 < rec["percentile"] < 100.0  # LeBron top-tier scorer
        assert 20.0 < rec["value"] < 30.0

    @pytest.mark.parametrize("metric", ["ts_percent", "ast", "reb", "bpm", "vorp"])
    def test_historical_percentile_all_metrics(self, metric):
        hp = historical_percentile(2025, metric, ["jamesle01"], "Regular")
        rec = hp["jamesle01"]
        assert 0.0 <= rec["percentile"] <= 100.0

    def test_historical_percentile_unsupported_raises(self):
        with pytest.raises(ValueError):
            historical_percentile(2025, "not_a_metric", ["jamesle01"])

    def test_historical_percentile_playoffs_no_crash(self):
        # Player may have no playoff row; must return {} not crash
        out = historical_percentile(2025, "ppg", ["jamesle01"], "Playoffs")
        assert isinstance(out, dict)
