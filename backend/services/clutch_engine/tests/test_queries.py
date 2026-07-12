"""Unit tests for clutch_queries SQL builders (no execution; §6 compliance)."""
from __future__ import annotations

from backend.core import db
from backend.services.clutch_engine import clutch_queries as q


def test_build_clutch_players_sql_all_seasons_shape():
    sql, params = q.build_clutch_players_sql(
        period=4, clock_max=300, margin_max=5, season=None, min_poss=10)
    assert sql.strip().upper().startswith("WITH")
    assert "SELECT" in sql
    # params: [period, clock_max, season, season, gameid, gameid, margin_max, min_poss]
    assert len(params) == 8
    assert params[0] == 4 and params[1] == 300
    assert params[2] is None and params[3] is None
    assert params[4] is None and params[5] is None
    assert params[6] == 5 and params[7] == 10
    db.validate_batch_sql(sql)  # §6: SELECT-only must pass


def test_build_clutch_players_sql_with_season_and_game():
    sql, params = q.build_clutch_players_sql(
        period=4, clock_max=300, margin_max=5, season=2026, min_poss=10, gameid="G1")
    assert params[2] == 2026 and params[3] == 2026
    assert params[4] == "G1" and params[5] == "G1"
    db.validate_batch_sql(sql)


def test_build_clutch_events_sql_shape():
    sql, params = q.build_clutch_events_sql("G1", 2026, period=4, clock_max=300, margin_max=5)
    assert "source = 'br_crawler'" in sql
    assert len(params) == 5
    assert params[0] == 4 and params[1] == 300 and params[2] == "G1" and params[3] == 2026 and params[4] == 5
    db.validate_batch_sql(sql)


def test_build_seasons_sql():
    sql = q.build_seasons_sql()
    assert "DISTINCT season" in sql and "games" in sql
    db.validate_batch_sql(sql)
