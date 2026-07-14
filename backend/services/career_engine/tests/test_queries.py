"""Unit tests for career_queries (SQL builders are SELECT-only, parameterized)."""
from __future__ import annotations

import pytest

from backend.services.career_engine import career_queries as q
from backend.services.career_engine.career_constants import (
    EXCLUDED_TEAMS,
    METRIC_PATTERN,
    METRIC_WHITELIST,
)


def _forbidden_check(sql: str):
    """Assert no DML/DDL substring appears (mirrors db.validate_batch_sql)."""
    import re

    forbidden = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|MERGE|VACUUM)\b",
        re.IGNORECASE,
    )
    assert not forbidden.search(sql), f"forbidden SQL token in: {sql[:120]}"


def test_peak_sql_is_select_only_and_parameterized():
    sql, params = q.build_peak_sql("pts_per_game", min_games=20, limit=10)
    assert sql.strip().upper().startswith("WITH")
    _forbidden_check(sql)
    # excluded teams + season_type + min_games + limit present in params
    assert params.count(20) >= 1
    assert 10 in params
    for t in EXCLUDED_TEAMS:
        assert t in params
    # placeholder count matches params length (no %s left dangling)
    assert sql.count("%s") == len(params)


def test_peak_sql_metric_mapping_pts_per_game():
    sql, _ = q.build_peak_sql("pts_per_game")
    # derived expression, not a bare column
    assert "pts::numeric / NULLIF(g, 0)" in sql


def test_peak_sql_metric_real_columns():
    for m in ("per", "ws", "vorp", "ts_percent", "bpm"):
        sql, _ = q.build_peak_sql(m)
        assert METRIC_WHITELIST[m]["expr"] in sql


def test_peak_sql_position_filter():
    sql, params = q.build_peak_sql("per", position="PG")
    assert "pos_group_sql('f.pos')" not in sql  # fragment is inlined
    assert "ILIKE '%G%'" in sql
    assert "G" in params


def test_peak_sql_era_filter():
    sql, params = q.build_peak_sql("per", era="2010s")
    assert "f.season >= %s AND f.season <= %s" in sql
    assert 2010 in params and 2019 in params


def test_age_curve_sql_requires_ids():
    with pytest.raises(ValueError):
        q.build_age_curve_sql([], "pts_per_game")


def test_age_curve_sql_select_only():
    sql, params = q.build_age_curve_sql(["jamesle01", "curryan01"], "bpm")
    _forbidden_check(sql)
    assert "jamesle01" in params and "curryan01" in params
    assert sql.count("%s") == len(params)
    assert "ORDER BY player_id, age ASC" in sql


def test_similar_candidates_sql_select_only():
    sql, params = q.build_similar_candidates_sql("ws", target_pos="SF", same_position=True)
    _forbidden_check(sql)
    # pos_group_sql always emits the C/G CASE; the category param is 'F' for SF
    assert "ILIKE '%C%'" in sql
    assert "ILIKE '%G%'" in sql
    assert "F" in params
    assert sql.count("%s") == len(params)


def test_similar_candidates_no_position_when_disabled():
    sql, params = q.build_similar_candidates_sql("ws", same_position=False)
    assert "ILIKE '%C%'" not in sql


def test_metric_pattern_matches_whitelist():
    import re

    pat = re.compile(METRIC_PATTERN)
    for m in METRIC_WHITELIST:
        assert pat.match(m)
    assert not pat.match("fake_metric")
