"""API 层薄编排测试（任务⑨）：FastAPI TestClient 调关键端点，验证响应结构。

端点：
  GET  /trade/rules/{season}
  POST /trade/validate
  POST /trade/suggest
  GET  /trade/timeline/player/{id}
  GET  /trade/timeline/team/{abbr}
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.services.trade_engine.tests.conftest import skip_if_no_db


@pytest.fixture(scope="module")
def client():
    from backend.app import app

    return TestClient(app)


@skip_if_no_db
class TestTradeAPI:
    def test_get_rules(self, client):
        r = client.get("/trade/rules/2025-26")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["salary_cap"] == 154_647_000
        assert body["data"]["second_apron"] == 207_824_000
        assert body["data"]["first_apron"] == 195_945_000

    def test_validate_gsw_brk(self, client):
        payload = {
            "league": "NBA",
            "season": "2025-26",
            "as_of": "2026-01-15T00:00:00",
            "legs": [
                {"team_abbr": "GSW", "outgoing": ["curryst01"],
                 "incoming": ["portemi01", "claxtni01", "mannte01"]},
                {"team_abbr": "BRK", "outgoing": ["portemi01", "claxtni01", "mannte01"],
                 "incoming": ["curryst01"]},
            ],
        }
        r = client.post("/trade/validate", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["legal"] is False
        assert "results" in body["data"]
        assert "cap_impact" in body["data"]
        gsw = next(m for m in body["data"]["results"] if m["team_abbr"] == "GSW")
        codes = {i["rule_code"] for i in gsw["issues"]}
        assert "HARD_CAP" in codes and "SALARY_MATCH" in codes

    def test_suggest_structure(self, client):
        payload = {
            "league": "NBA",
            "season": "2025-26",
            "as_of": "2026-01-15T00:00:00",
            "legs": [
                {"team_abbr": "GSW", "outgoing": ["curryst01"],
                 "incoming": ["portemi01", "claxtni01", "mannte01"]},
                {"team_abbr": "BRK", "outgoing": ["portemi01", "claxtni01", "mannte01"],
                 "incoming": ["curryst01"]},
            ],
        }
        r = client.post("/trade/suggest", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert "suggestions" in body["data"]

    def test_player_timeline(self, client):
        r = client.get("/trade/timeline/player/curryst01?season=2025-26")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["season"] == "2025-26"
        assert "salaries" in body["data"]
        assert len(body["data"]["salaries"]) == 6

    def test_team_timeline(self, client):
        r = client.get("/trade/timeline/team/GSW?season=2025-26")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["team_abbr"] == "GSW"
        assert len(body["data"]["total_salary"]) == 6
