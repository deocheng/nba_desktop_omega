"""Unit tests for clutch_utils — pure SQL-fragment + rate helpers (no DB)."""
from __future__ import annotations

from backend.services.clutch_engine import clutch_utils as u


def test_round_rate_basic():
    assert u.round_rate(5, 10) == 50.0
    assert u.round_rate(1, 3) == 33.33
    assert u.round_rate(0, 0) is None
    assert u.round_rate(None, 10) is None
    assert u.round_rate(5, None) is None
    assert u.round_rate(5, 0) is None


def test_source_priority_sql():
    s = u.source_priority_sql("source")
    assert s.startswith("CASE")
    assert "br_crawler" in s and "nba_api" in s and "BBRef" in s
    assert "ELSE 9 END" in s


def test_parse_score_margin_sql():
    s = u.parse_score_margin_sql("scoremargin")
    assert "TIE" in s and "0" in s
    assert "REGEXP_REPLACE" in s


def test_derive_margin_sql():
    s = u.derive_margin_sql("base_margin", "h_fill", "a_fill")
    assert "COALESCE" in s and "ABS" in s


def test_shot_value_sql_br_crawler_branch():
    s = u.shot_value_sql(
        source_col="source", subtype_col="subtype", desc_col="description",
        is_fg_col="is_fg", shot_delta_col="shot_delta",
    )
    assert "br_crawler" in s and "BBRef" in s
    assert "IN (2, 3)" in s
    assert "3-pt|three" in s


def test_shot_value_sql_falls_through_to_null():
    s = u.shot_value_sql()
    assert "ELSE NULL END" in s


def test_shot_type_sql():
    s = u.shot_type_sql()
    assert "Free Throw" in s and "Jump Shot" in s and "Layup" in s and "Dunk" in s


def test_finish_type_sql():
    s = u.finish_type_sql()
    assert "br_crawler" in s
    assert "pullup" in s and "dribble" in s and "catch" in s
