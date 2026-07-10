"""Requirements 7 (router) & 8 — API orchestration (thin layer, envelope shape).

Uses FastAPI TestClient against the real app:
  - GET  /tactics/templates                  -> 200, envelope, >=8 templates
  - POST /tactics/ai/generate (static)      -> 200
  - POST /tactics/ai/generate (llm)         -> 501  (P2 reserved slot)
  - GET  /tactics/games?season=2025         -> 200, envelope, non-empty list (DB)
  - POST /tactics/replay (real game)        -> 200, envelope {code,data,message}
  - POST /tactics/replay (missing game)     -> 404 (orchestration error path)
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.needs_db


@pytest.fixture(scope="module")
def client():
    from backend.app import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_templates_endpoint(client):
    r = client.get("/tactics/templates")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert isinstance(body["data"], list) and len(body["data"]) >= 8


def test_ai_generate_static_returns_200(client):
    r = client.post(
        "/tactics/ai/generate",
        json={"prompt": "pick and roll", "provider": "static"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["id"] == "pick_and_roll"


def test_ai_generate_llm_returns_501(client):
    r = client.post(
        "/tactics/ai/generate",
        json={"prompt": "any", "provider": "llm"},
    )
    assert r.status_code == 501


def test_games_endpoint(client):
    r = client.get("/tactics/games?season=2025")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert isinstance(body["data"], list) and len(body["data"]) > 0
    # real game 22400740 must be present in the 2025 replay list
    ids = {g["game_id"] for g in body["data"]}
    assert "22400740" in ids


def test_replay_endpoint_envelope(client):
    r = client.post(
        "/tactics/replay",
        json={"game_id": "22400740", "season": "2025", "frame_rate": 2},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    # envelope shape
    assert set(body.keys()) == {"code", "data", "message"}
    data = body["data"]
    assert isinstance(data["frames"], list) and len(data["frames"]) > 0
    assert "meta" in data


def test_replay_missing_game_returns_404(client):
    r = client.post(
        "/tactics/replay",
        json={"game_id": "00000000", "season": "2025", "frame_rate": 2},
    )
    assert r.status_code == 404
