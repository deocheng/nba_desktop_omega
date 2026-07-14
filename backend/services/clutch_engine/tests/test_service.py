"""Clutch service tests: post-processing units + live DB integration + router contract.

Live tests skip automatically when PostgreSQL is unreachable (v8 §6 forbids
mocking engine core logic, so we hit the real DB instead of faking it).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.routers.clutch_schemas import ClutchQuery
from backend.services.clutch_engine import clutch_service


# ── Fast, DB-free post-processing units ──
def test_post_process_nulls_catch_dribble_when_unidentifiable():
    row = {"fga": 10, "fgm": 4, "fga2": 6, "fgm2": 3, "fga3": 4, "fgm3": 1,
           "fta": 2, "ftm": 2, "catch_shots": 0, "dribble_shots": 0,
           "oreb": 1, "dreb": 2, "ast": 1, "stl": 0, "tov": 1, "pf": 2,
           "pts": 9, "player_name": "X", "team": "DEN", "poss": 12, "player_id": "P1"}
    out = clutch_service._post_process(row)
    assert out["catch_shots"] is None
    assert out["dribble_shots"] is None
    assert out["dribble_coverage"] is None
    assert out["fg_pct"] == 40.0
    assert out["fg2_pct"] == 50.0
    assert out["fg3_pct"] == 25.0
    assert out["ft_pct"] == 100.0


def test_post_process_keeps_catch_dribble_when_identified():
    row = {"fga": 10, "fgm": 5, "fga2": 6, "fgm2": 3, "fga3": 4, "fgm3": 2,
           "fta": 0, "ftm": 0, "catch_shots": 6, "dribble_shots": 4,
           "oreb": 0, "dreb": 0, "ast": 0, "stl": 0, "tov": 0, "pf": 0,
           "pts": 12, "player_name": "Y", "team": "LAL", "poss": 20, "player_id": "P2"}
    out = clutch_service._post_process(row)
    assert out["catch_shots"] == 6
    assert out["dribble_shots"] == 4
    assert out["dribble_coverage"] == 100.0
    assert out["fg_pct"] == 50.0


# ── Router input contract (no DB) ──
def test_clutch_query_rejects_bad_metric():
    with pytest.raises(Exception):
        ClutchQuery(metric="bogus")


def test_clutch_query_accepts_valid_metric():
    q = ClutchQuery(metric="points", season=2026)
    assert q.metric == "points" and q.season == 2026


# ── Live integration (skipped if no DB) ──
def test_get_clutch_players_live(db_available):
    if not db_available:
        pytest.skip("PostgreSQL not available")
    rows = clutch_service.get_clutch_players(
        period=4, clock_max=300, margin_max=5, season=2026,
        metric="possessions", min_poss=20, limit=30)
    assert isinstance(rows, list) and len(rows) > 0
    assert len(rows) <= 30
    poss = [r["poss"] for r in rows]
    assert poss == sorted(poss, reverse=True)
    for r in rows:
        assert "player_name" in r and "team" in r and "fg_pct" in r
        if r["catch_shots"] is None:
            assert r["dribble_shots"] is None
        else:
            assert r["dribble_shots"] is not None


def test_get_seasons_live(db_available):
    if not db_available:
        pytest.skip("PostgreSQL not available")
    seasons = clutch_service.get_seasons()
    assert isinstance(seasons, list) and len(seasons) > 0
    assert all(isinstance(s, int) for s in seasons)
    # games table spans NBA history (first season 1946-47 -> stored as 1947);
    # play_by_play only reaches back to 2001, but get_seasons reads games.
    assert min(seasons) >= 1946 and max(seasons) <= 2026


def test_router_clutch_players_live(db_available):
    if not db_available:
        pytest.skip("PostgreSQL not available")
    from backend.app import create_app
    with TestClient(create_app()) as client:
        resp = client.get(
            "/api/clutch/players?metric=possessions&min_poss=20&limit=30&season=2026")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert isinstance(body["data"], list)
        assert len(body["data"]) <= 30


def test_router_clutch_seasons_live(db_available):
    if not db_available:
        pytest.skip("PostgreSQL not available")
    from backend.app import create_app
    with TestClient(create_app()) as client:
        resp = client.get("/api/clutch/seasons")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert all(isinstance(s, int) for s in body["data"])
