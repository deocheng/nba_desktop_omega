"""NBACore v8 — Entity Detail API tests (Layer 3 routers).

GET /players/{id}/detail, /players/{id}/games,
    /teams/{abbr}/detail, /teams/{abbr}/games

v8 §6: no mocking of engine core; DB-dependent tests use a live connection
(skipped if PostgreSQL is unavailable).
"""
from __future__ import annotations

import pytest

_KNOWN_PLAYER = "greenac01"
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


class TestPlayerDetail:
    @pytest.mark.needs_data
    def test_404_for_unknown(self, app_client):
        resp = app_client.get("/players/unknown99zz/detail?season=2026")
        assert resp.status_code == 404

    @pytest.mark.needs_data
    @needs_db
    def test_ok_structure(self, app_client):
        resp = app_client.get(f"/players/{_KNOWN_PLAYER}/detail?season=2026")
        assert resp.status_code == 200
        d = resp.json()
        assert isinstance(d["bio"], dict)
        assert isinstance(d["seasons"], list)
        assert isinstance(d["metrics"], dict)
        assert d["season"] == 2026


class TestPlayerGames:
    def test_invalid_granularity_422(self, app_client):
        resp = app_client.get(f"/players/{_KNOWN_PLAYER}/games?season=2026&granularity=bogus")
        assert resp.status_code == 422

    @pytest.mark.needs_data
    @needs_db
    def test_month_ok(self, app_client, player_with_gamelog):
        # 样本球员动态选取：硬编码 slug 在 2025-26 季已无 gamelog（见 conftest 说明）
        pid = player_with_gamelog(2026)
        assert pid, "no player with gamelog rows in season 2026"
        resp = app_client.get(f"/players/{pid}/games?season=2026&granularity=month")
        assert resp.status_code == 200
        d = resp.json()
        assert d["entity_type"] == "player"
        assert d["granularity"] == "month"
        assert d["totals"]["gp"] > 0
        assert isinstance(d["groups"], list)

    @needs_db
    def test_game_granularity(self, app_client):
        resp = app_client.get(f"/players/{_KNOWN_PLAYER}/games?season=2026&granularity=game")
        d = resp.json()
        assert resp.status_code == 200
        assert len(d["groups"]) == d["totals"]["gp"]


@pytest.mark.needs_data
class TestTeamDetail:
    @needs_db
    def test_ok_structure(self, app_client):
        resp = app_client.get(f"/teams/{_KNOWN_TEAM}/detail?season=2026")
        assert resp.status_code == 200
        d = resp.json()
        assert d["team_abbr"] == _KNOWN_TEAM
        assert isinstance(d["seasons"], list)
        assert d["season"] == 2026


class TestTeamGames:
    def test_invalid_granularity_422(self, app_client):
        resp = app_client.get(f"/teams/{_KNOWN_TEAM}/games?season=2026&granularity=bogus")
        assert resp.status_code == 422

    @pytest.mark.needs_data
    @needs_db
    def test_month_ok(self, app_client):
        resp = app_client.get(f"/teams/{_KNOWN_TEAM}/games?season=2026&granularity=month")
        assert resp.status_code == 200
        d = resp.json()
        assert d["entity_type"] == "team"
        assert d["totals"]["gp"] > 0
        assert isinstance(d["groups"], list)

    @needs_db
    def test_divergent_abbr_games(self, app_client):
        resp = app_client.get("/teams/BKN/games?season=2026&granularity=month")
        assert resp.status_code == 200
        assert resp.json()["entity_type"] == "team"
