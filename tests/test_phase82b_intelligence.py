"""NBACore v8.2-B — Player Understanding unit + API tests.

Covers v8.2 §8 Role Classification, §9 Player DNA, §10 Scoring Profile, and
the GET /players/{id}/intelligence endpoint (§19).

Pure helpers tested deterministically; DB-backed + API tested against the
live PostgreSQL `nba` instance. Run:
    pytest tests/test_phase82b_intelligence.py -q
"""
from __future__ import annotations

import pytest

from backend.services.intelligence_engine import (
    ROLE_TYPES,
    DNA_DIMENSIONS,
    classify_role,
    compute_dna,
    compute_availability,
    load_player_intel,
    scoring_profile,
)


def _m(**kw):
    base = dict(pts=1500, g=70, ast=300, trb=400, mp=2000, ts_percent=0.55,
                usg_percent=20.0, ast_percent=15.0, orb_percent=5.0,
                drb_percent=15.0, stl_percent=1.0, blk_percent=1.0,
                x3pa=200, fga=1000)
    base.update(kw)
    return base


# ── §8 Role Classification (pure) ──

class TestRoleClassification:
    @pytest.mark.parametrize("name,kwargs", [
        ("Primary Creator", dict(usg_percent=30, ast_percent=30)),
        ("Two Way Star", dict(usg_percent=22, ast_percent=15, ts_percent=0.60,
                              stl_percent=2.0, blk_percent=1.5)),
        ("Scoring Guard", dict(usg_percent=28, ast_percent=10, x3pa=400, fga=1000)),
        ("Shot Creator", dict(usg_percent=28, ast_percent=10, x3pa=100, fga=1000)),
        ("3&D Wing", dict(usg_percent=18, ast_percent=10, x3pa=400, g=1000,
                          ts_percent=0.56, stl_percent=1.0, blk_percent=1.0)),
        ("Secondary Creator", dict(usg_percent=20, ast_percent=30)),
        ("Rim Protector", dict(usg_percent=15, ast_percent=5, blk_percent=5.0)),
        ("Stretch Big", dict(usg_percent=18, orb_percent=8.0, drb_percent=10.0,
                             x3pa=300, fga=1000)),
        ("Role Player", dict(usg_percent=15, ast_percent=8, x3pa=100, fga=1000,
                             blk_percent=1.0)),
    ])
    def test_role_assignment(self, name, kwargs):
        assert classify_role(_m(**kwargs)) == name

    def test_all_nine_roles_covered(self):
        seen = {
            classify_role(_m(**kw)) for _, kw in [
                ("Primary Creator", dict(usg_percent=30, ast_percent=30)),
                ("Two Way Star", dict(usg_percent=22, ast_percent=15, ts_percent=0.60,
                                      stl_percent=2.0, blk_percent=1.5)),
                ("Scoring Guard", dict(usg_percent=28, ast_percent=10, x3pa=400, fga=1000)),
                ("Shot Creator", dict(usg_percent=28, ast_percent=10, x3pa=100, fga=1000)),
                ("3&D Wing", dict(usg_percent=18, ast_percent=10, x3pa=400, g=1000,
                                  ts_percent=0.56, stl_percent=1.0, blk_percent=1.0)),
                ("Secondary Creator", dict(usg_percent=20, ast_percent=30)),
                ("Rim Protector", dict(usg_percent=15, ast_percent=5, blk_percent=5.0)),
                ("Stretch Big", dict(usg_percent=18, orb_percent=8.0, drb_percent=10.0,
                                     x3pa=300, fga=1000)),
                ("Role Player", dict(usg_percent=15, ast_percent=8, x3pa=100, fga=1000,
                                     blk_percent=1.0)),
            ]
        }
        assert seen == set(ROLE_TYPES)

    def test_role_lebron_db(self, db_available):
        skip_without_db(db_available)
        rows = load_player_intel(2025, "Regular", ["jamesle01"])
        assert classify_role(rows[0]) == "Primary Creator"


# ── §9 Player DNA (pure + DB) ──

class TestPlayerDNA:
    def test_dna_range_and_keys(self):
        dna = compute_dna(_m(), availability_score=0.9)
        assert set(dna.keys()) == set(DNA_DIMENSIONS)
        assert all(0.0 <= v <= 100.0 for v in dna.values())

    def test_dna_zero_games_no_crash(self):
        dna = compute_dna(_m(g=0, pts=0, ast=0), availability_score=0.0)
        assert all(0.0 <= v <= 100.0 for v in dna.values())

    def test_dna_lebron_db(self, db_available):
        skip_without_db(db_available)
        rows = load_player_intel(2025, "Regular", ["jamesle01"])
        av = compute_availability(2025, ["jamesle01"], "Regular").get("jamesle01", {})
        dna = compute_dna(rows[0], av.get("availability", 1.0))
        assert set(dna.keys()) == set(DNA_DIMENSIONS)
        assert all(0.0 <= v <= 100.0 for v in dna.values())
        # LeBron is an elite playmaker + leader
        assert dna["playmaking"] >= 90.0
        assert dna["leadership"] >= 90.0


# ── §10 Scoring Profile (DB) ──

class TestScoringProfile:
    def test_scoring_profile_lebron(self, db_available):
        skip_without_db(db_available)
        prof = scoring_profile("jamesle01", 2025, "Regular")
        assert prof, "expected non-empty shooting zones"
        assert set(prof.keys()) <= {"At Rim", "Paint", "Mid-Range", "Three Point"}
        total = sum(v["frequency"] for v in prof.values())
        assert 0.95 <= total <= 1.05  # frequencies sum to ~1.0
        for v in prof.values():
            assert 0.0 <= v["efficiency"] <= 1.0


# ── §19 Intelligence API ──

class TestIntelligenceAPI:
    def test_endpoint_200_structure(self, app_client, db_available):
        skip_without_db(db_available)
        r = app_client.get("/players/jamesle01/intelligence", params={"season": 2025})
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "Primary Creator"
        assert set(body["dna"].keys()) == set(DNA_DIMENSIONS)
        assert body["availability"]["availability"] is not None
        assert 0.8 < body["availability"]["availability"] < 0.9  # LeBron ~0.85
        assert body["scoring_profile"]  # at least one zone

    def test_endpoint_404_unknown_player(self, app_client, db_available):
        skip_without_db(db_available)
        r = app_client.get("/players/nonexistent01/intelligence", params={"season": 2025})
        assert r.status_code == 404

    def test_endpoint_defaults_to_latest_season(self, app_client, db_available):
        skip_without_db(db_available)
        r = app_client.get("/players/jamesle01/intelligence")
        assert r.status_code == 200
        assert r.json()["season"] >= 2024


def skip_without_db(db_available):
    if not db_available:
        pytest.skip("PostgreSQL not available — set DB_PORT and start service")
