"""Unit tests for career_utils (pure functions, no DB)."""
from __future__ import annotations

from datetime import date

import pytest

from backend.services.career_engine import career_utils as u
from backend.services.career_engine.career_constants import AGE_GRID


def test_round_rate_basic():
    assert u.round_rate(50, 100) == 50.0
    assert u.round_rate(1, 3) == pytest.approx(33.33, abs=0.01)


def test_round_rate_zero_denom_is_none():
    assert u.round_rate(5, 0) is None
    assert u.round_rate(None, 10) is None
    assert u.round_rate(10, None) is None


def test_age_in_season_known():
    # Born 1984-12-30; season 2003 starts Oct 1 2003 -> age 18 (birthday after Oct 1)
    assert u.age_in_season(date(1984, 12, 30), 2003) == 18.0
    # Born 1984-1-1; season 2003 -> age 19 (birthday before Oct 1)
    assert u.age_in_season(date(1984, 1, 1), 2003) == 19.0


def test_age_in_season_missing():
    assert u.age_in_season(None, 2003) is None
    assert u.age_in_season(date(1984, 1, 1), None) is None


def test_age_in_season_string():
    assert u.age_in_season("1984-12-30", 2003) == 18.0


def test_resample_linear_interp():
    pts = [(20, 10.0), (22, 20.0)]
    grid = [20, 21, 22]
    out = u.resample_curve_to_grid(pts, grid)
    assert out[0] == 10.0
    assert out[1] == pytest.approx(15.0)
    assert out[2] == 20.0


def test_resample_clamps_endpoints():
    pts = [(20, 10.0), (22, 20.0)]
    # ages outside range are clamped to nearest endpoint value
    out = u.resample_curve_to_grid(pts, [18, 19, 20, 22, 24, 25])
    assert out[0] == 10.0
    assert out[1] == 10.0
    assert out[4] == 20.0
    assert out[5] == 20.0


def test_resample_empty_returns_none_grid():
    out = u.resample_curve_to_grid([], AGE_GRID)
    assert out == [None for _ in AGE_GRID]


def test_resample_dict_points():
    pts = [{"age": 20, "value": 10.0}, {"age": 22, "value": 20.0}]
    out = u.resample_curve_to_grid(pts, [20, 21, 22], age_key="age", value_key="value")
    assert out[1] == pytest.approx(15.0)


def test_pearson_perfect_positive():
    a = [1.0, 2.0, 3.0, 4.0]
    b = [2.0, 4.0, 6.0, 8.0]
    assert u.similarity_score(a, b, "pearson") == pytest.approx(1.0)


def test_pearson_perfect_negative():
    a = [1.0, 2.0, 3.0, 4.0]
    b = [8.0, 6.0, 4.0, 2.0]
    assert u.similarity_score(a, b, "pearson") == pytest.approx(0.0)


def test_pearson_zero_variance_is_zero():
    a = [1.0, 1.0, 1.0, 1.0]
    b = [2.0, 4.0, 6.0, 8.0]
    assert u.similarity_score(a, b, "pearson") == 0.0


def test_pearson_moderate():
    # r ~ 0.5 -> score ~ 0.75
    a = [1.0, 2.0, 3.0, 4.0, 5.0]
    b = [1.0, 2.0, 2.0, 4.0, 5.0]
    s = u.similarity_score(a, b, "pearson")
    assert 0.6 < s <= 1.0


def test_cosine_identical():
    a = [1.0, 2.0, 3.0]
    assert u.similarity_score(a, a, "cosine") == pytest.approx(1.0)


def test_euclidean_identical():
    a = [1.0, 2.0, 3.0]
    assert u.similarity_score(a, a, "euclidean") == pytest.approx(1.0)


def test_similarity_no_overlap_is_zero():
    a = [1.0, None, 3.0]
    b = [None, 2.0, None]
    assert u.similarity_score(a, b, "pearson") == 0.0


def test_parse_era():
    assert u._parse_era("2010s") == (2010, 2019)
    assert u._parse_era(None) is None
    assert u._parse_era("garbage") is None


def test_pos_group():
    assert u._pos_group("PG") == "G"
    assert u._pos_group("SF") == "F"
    assert u._pos_group("C") == "C"
    assert u._pos_group(None) is None
