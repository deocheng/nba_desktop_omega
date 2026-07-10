"""Unit tests for the clutch-replay service (engine layers mocked, offline)."""
from __future__ import annotations

import pytest

from backend.services.clutch_replay_engine import schemas
from backend.services.clutch_replay_engine import service as svc_mod
from backend.services.clutch_engine import clutch_service
from backend.services.tactics_engine import service as tactics_service


def _fake_replay(self, req):
    frames = [{"t": float(i), "event_index": i} for i in range(12)]
    return {
        "game_id": req.game_id,
        "season": str(req.season),
        "frames": frames,
        "meta": {"frame_count": 12, "fps": 30},
    }


def _clutch_events():
    return [
        {"eventnum": 5, "period": 4, "clock_seconds": 120.0,
         "playerid": "P1", "player": "A", "team": "DEN", "margin": 3},
        {"eventnum": 7, "period": 4, "clock_seconds": 100.0,
         "playerid": "P2", "player": "B", "team": "LAL", "margin": 2},
    ]


def _player_rows():
    return [{
        "player_id": "P1", "player_name": "A", "team": "DEN", "poss": 5, "pts": 8,
        "fg_pct": 50.0, "fg2_pct": 55.0, "fg3_pct": 40.0,
        "oreb": 1, "dreb": 2, "ast": 1, "stl": 0, "tov": 1, "pf": 2,
        "catch_shots": 3, "dribble_shots": 1, "dribble_coverage": 80.0,
    }]


def test_clutch_replay_service_fusion(monkeypatch):
    monkeypatch.setattr(tactics_service.TacticsService, "replay", _fake_replay)
    monkeypatch.setattr(clutch_service, "fetch_clutch_events", lambda *a, **k: _clutch_events())
    monkeypatch.setattr(clutch_service, "get_clutch_players_for_game", lambda *a, **k: _player_rows())
    # build_segments runs for real (pure); only the DB-backed map is mocked
    monkeypatch.setattr(svc_mod, "build_eventnum_to_index_map", lambda *a, **k: {5: 5, 7: 7})

    svc = svc_mod.ClutchReplayService()
    req = schemas.ClutchReplayRequest(game_id="G1", season="2025")
    res = svc.clutch_replay(req)

    assert res.game_id == "G1"
    assert len(res.frames) == 12
    assert res.meta["clutch_segment_count"] == 1

    seg = res.clutch_segments[0]
    assert seg.start_frame == 3 and seg.end_frame == 9  # merged [3,9]
    assert seg.period == 4
    assert seg.clock_start == 120.0 and seg.clock_end == 100.0
    assert {p.player for p in seg.players} == {"A", "B"}
    assert seg.margin == 3

    assert len(res.clutch_players) == 1
    assert res.clutch_players[0].player_name == "A"
    assert res.clutch_players[0].pts == 8
    assert res.clutch_players[0].fg_pct == 50.0
    assert res.clutch_players[0].dribble_coverage == 80.0


def test_clutch_replay_service_no_frames(monkeypatch):
    def fake_replay(self, req):
        raise LookupError("no br_crawler data")

    monkeypatch.setattr(tactics_service.TacticsService, "replay", fake_replay)
    svc = svc_mod.ClutchReplayService()
    req = schemas.ClutchReplayRequest(game_id="GX", season="2025")
    with pytest.raises(schemas.ClutchReplayError) as exc:
        svc.clutch_replay(req)
    assert exc.value.code == 40002


def test_clutch_replay_service_empty_clutch(monkeypatch):
    monkeypatch.setattr(tactics_service.TacticsService, "replay", _fake_replay)
    monkeypatch.setattr(clutch_service, "fetch_clutch_events", lambda *a, **k: [])  # no clutch rows
    monkeypatch.setattr(clutch_service, "get_clutch_players_for_game", lambda *a, **k: [])
    monkeypatch.setattr(svc_mod, "build_eventnum_to_index_map", lambda *a, **k: {})

    svc = svc_mod.ClutchReplayService()
    req = schemas.ClutchReplayRequest(game_id="G1", season="2025")
    res = svc.clutch_replay(req)  # degraded rendering: empty segments, still code 0
    assert res.clutch_segments == []
    assert res.meta["clutch_segment_count"] == 0
    assert len(res.frames) == 12
