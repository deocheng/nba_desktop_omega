"""Integration test: /clutch-replay router wiring (engine layers mocked, offline).

Validates the Layer-3 envelope contract (``{code, data, message}``) and that
the router is registered and delegates to ``ClutchReplayService``. No database
is touched; the service method is monkeypatched with a canned result.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import app
from backend.services.clutch_replay_engine import schemas
from backend.services.clutch_replay_engine.service import ClutchReplayService


def _canned(req: schemas.ClutchReplayRequest) -> schemas.ClutchReplayResult:
    return schemas.ClutchReplayResult(
        game_id=req.game_id,
        season=req.season,
        frames=[{"t": 0.0, "event_index": 0}, {"t": 1.0, "event_index": 1}],
        meta={"frame_count": 2, "fps": 30},
        clutch_segments=[schemas.ClutchSegment(
            start_event_index=0, end_event_index=1, start_frame=0, end_frame=1,
            period=4, clock_start=120.0, clock_end=110.0,
            players=[schemas.ClutchSegmentPlayer(player="A", team="DEN")], margin=3,
        )],
        clutch_players=[schemas.ClutchPlayerStat(player_name="A", team="DEN", poss=5, pts=8)],
    )


def test_clutch_replay_integration_replay_endpoint(monkeypatch):
    monkeypatch.setattr(ClutchReplayService, "clutch_replay", lambda self, req: _canned(req))
    client = TestClient(app)
    resp = client.post("/clutch-replay/replay", json={"game_id": "G1", "season": "2025"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["game_id"] == "G1"
    assert "frames" in body["data"]
    assert "clutch_segments" in body["data"]
    assert "clutch_players" in body["data"]
    assert body["data"]["clutch_segments"][0]["players"][0]["player"] == "A"
    assert body["data"]["meta"]["frame_count"] == 2


def test_clutch_replay_integration_games_endpoint(monkeypatch):
    monkeypatch.setattr(
        "backend.services.tactics_engine.service.TacticsService.list_games",
        lambda self, season: [{"game_id": "G1", "teams": ["A", "B"],
                               "event_count": 10, "xy_count": 5}],
    )
    client = TestClient(app)
    resp = client.get("/clutch-replay/games?season=2025")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"][0]["game_id"] == "G1"
