"""Unit tests for career_service orchestration (mock db.batch_query, no live DB)."""
from __future__ import annotations

import pytest

from backend.services.career_engine import career_service as svc


@pytest.fixture
def patch_db(monkeypatch):
    calls = {"results": [], "queue": []}

    def fake_batch_query(sql, params=None):
        calls["results"].append((sql, params))
        if calls["queue"]:
            return calls["queue"].pop(0)
        return []

    monkeypatch.setattr(svc.db, "batch_query", fake_batch_query)
    calls["fake"] = fake_batch_query
    return calls


def test_get_peak_players_age_fallback(patch_db):
    rows = [
        {
            "player_id": "p1", "player_name": "Player One",
            "peak_value": 30.5, "peak_season": 2010, "peak_age": None,
            "peak_team": "LAL", "second_value": 28.0, "seasons_played": 12,
            "birth_date": "1984-12-30",
        }
    ]
    patch_db["queue"] = [rows]
    out = svc.get_peak_players("pts_per_game", limit=5)
    assert len(out) == 1
    assert out[0]["rank"] == 1
    assert out[0]["peak_value"] == 30.5
    assert out[0]["second_value"] == 28.0
    # age fallback: 1984-12-30 in season 2010 -> 25
    assert out[0]["peak_age"] == 25.0


def test_get_peak_players_skips_null_peak(patch_db):
    rows = [
        {"player_id": "p1", "player_name": "X", "peak_value": None,
         "peak_season": None, "peak_age": None, "peak_team": None,
         "second_value": None, "seasons_played": 0, "birth_date": None},
    ]
    patch_db["queue"] = [rows]
    assert svc.get_peak_players("per") == []


def test_get_age_curves_groups_and_sorts(patch_db):
    rows = [
        {"player_id": "p1", "player_name": "P1", "season": 2004, "age": 21,
         "team": "T1", "metric_value": 20.0, "birth_date": None},
        {"player_id": "p1", "player_name": "P1", "season": 2003, "age": 20,
         "team": "T1", "metric_value": 10.0, "birth_date": None},
        {"player_id": "p2", "player_name": "P2", "season": 2005, "age": 22,
         "team": "T2", "metric_value": 15.0, "birth_date": None},
    ]
    patch_db["queue"] = [rows]
    out = svc.get_age_curves(["p1", "p2"], "pts_per_game")
    assert len(out) == 2
    assert [c["age"] for c in out[0]["curve"]] == [20, 21]
    assert out[0]["peak_age"] == 21
    assert out[0]["team_last"] == "T1"
    assert out[1]["curve"][0]["value"] == 15.0


def test_get_age_curves_missing_player_empty(patch_db):
    rows = [
        {"player_id": "p1", "player_name": "P1", "season": 2003, "age": 20,
         "team": "T1", "metric_value": 10.0, "birth_date": None},
    ]
    patch_db["queue"] = [rows]
    out = svc.get_age_curves(["p1", "missing"], "pts_per_game")
    assert out[0]["player_name"] == "P1"
    assert out[1]["player_id"] == "missing"
    assert out[1]["curve"] == []


def test_get_similar_evolution_scores_and_excludes_target(patch_db):
    target_rows = [
        {"player_id": "t1", "player_name": "Target", "season": 2003, "age": 20,
         "team": "T", "pos": "PG", "metric_value": 10.0, "birth_date": None},
        {"player_id": "t1", "player_name": "Target", "season": 2004, "age": 21,
         "team": "T", "pos": "PG", "metric_value": 20.0, "birth_date": None},
        {"player_id": "t1", "player_name": "Target", "season": 2005, "age": 22,
         "team": "T", "pos": "PG", "metric_value": 30.0, "birth_date": None},
    ]
    cand_rows = [
        # c1: identical shape -> sim 1.0
        {"player_id": "c1", "player_name": "Cand1", "season": 2003, "age": 20,
         "team": "T", "pos": "PG", "metric_value": 12.0, "birth_date": None},
        {"player_id": "c1", "player_name": "Cand1", "season": 2004, "age": 21,
         "team": "T", "pos": "PG", "metric_value": 22.0, "birth_date": None},
        {"player_id": "c1", "player_name": "Cand1", "season": 2005, "age": 22,
         "team": "T", "pos": "PG", "metric_value": 32.0, "birth_date": None},
        # c2: inverted shape -> sim 0.0
        {"player_id": "c2", "player_name": "Cand2", "season": 2003, "age": 20,
         "team": "T", "pos": "PG", "metric_value": 30.0, "birth_date": None},
        {"player_id": "c2", "player_name": "Cand2", "season": 2004, "age": 21,
         "team": "T", "pos": "PG", "metric_value": 20.0, "birth_date": None},
        {"player_id": "c2", "player_name": "Cand2", "season": 2005, "age": 22,
         "team": "T", "pos": "PG", "metric_value": 10.0, "birth_date": None},
    ]
    patch_db["queue"] = [target_rows, cand_rows]
    out = svc.get_similar_evolution(
        "t1", "pts_per_game", top_k=5, min_games=1,
        same_position=True, algorithm="pearson", min_seasons=2,
    )
    assert out["target"]["player_id"] == "t1"
    assert len(out["target"]["curve"]) == 3
    sim_ids = [c["player_id"] for c in out["similar"]]
    assert "t1" not in sim_ids
    by_id = {c["player_id"]: c["similarity"] for c in out["similar"]}
    assert by_id["c1"] == pytest.approx(1.0)
    assert by_id["c2"] == pytest.approx(0.0)


def test_get_similar_evolution_empty_target(patch_db):
    patch_db["queue"] = [[], []]
    out = svc.get_similar_evolution("ghost", "per")
    assert out["target"]["player_id"] == "ghost"
    assert out["similar"] == []


def test_get_age_curves_multi_groups_two_metrics(patch_db):
    rows = [
        {"player_id": "p1", "player_name": "P1", "season": 2003, "age": 20,
         "team": "T1", "metric_value": 10.0, "birth_date": None},
        {"player_id": "p1", "player_name": "P1", "season": 2004, "age": 21,
         "team": "T1", "metric_value": 25.0, "birth_date": None},
    ]
    # one query result consumed per metric (pts_per_game, then per)
    patch_db["queue"] = [rows, rows]
    out = svc.get_age_curves_multi(["p1"], ["pts_per_game", "per"])
    assert len(out) == 1
    p = out[0]
    # two metrics keyed in curves
    assert set(p["curves"].keys()) == {"pts_per_game", "per"}
    assert p["curves"]["pts_per_game"][0]["value"] == 10.0
    assert p["curves"]["per"][0]["value"] == 10.0
    # peak_ages present for both metrics
    assert p["peak_ages"]["pts_per_game"] == 21
    assert p["peak_ages"]["per"] == 21
    assert isinstance(p["peak_ages"]["pts_per_game"], (int, float))
    # back-compat: curve / peak_age mirror first metric
    assert p["curve"] == p["curves"]["pts_per_game"]
    assert p["peak_age"] == p["peak_ages"]["pts_per_game"]
    assert p["player_name"] == "P1"
    assert p["team_last"] == "T1"
    # values identical to a fresh single-metric call
    patch_db["queue"] = [rows]
    single = svc.get_age_curves(["p1"], "pts_per_game")
    single_vals = [c["value"] for c in single[0]["curve"]]
    multi_vals = [c["value"] for c in p["curves"]["pts_per_game"]]
    assert single_vals == multi_vals


def test_get_age_curves_multi_live():
    """Optional integration check (skips if no live DB is reachable)."""
    try:
        pid_rows = svc.db.batch_query(
            "SELECT player_id FROM fact_player_season_stats WHERE season_type='Regular' LIMIT 1"
        )
    except Exception:
        pytest.skip("live DB not available")
    if not pid_rows:
        pytest.skip("no data in DB")
    pid = pid_rows[0]["player_id"]
    out = svc.get_age_curves_multi([pid], ["pts_per_game", "per"])
    assert len(out) == 1
    p = out[0]
    assert p["player_id"] == pid
    if "pts_per_game" in p["curves"] and p["curves"]["pts_per_game"]:
        single = svc.get_age_curves([pid], "pts_per_game")
        assert [c["value"] for c in p["curves"]["pts_per_game"]] == [c["value"] for c in single[0]["curve"]]
        assert p["curve"] == p["curves"]["pts_per_game"]

