"""Requirement 1 — Coordinate mapping (coords.map_xy_to_svg).

Verifies:
  - deterministic boundary mapping (x=-250→0, x=250→500, y=0→bottom 470)
  - full-court folding keeps py within [0, 470]
  - full sweep stays inside the 500×470 SVG court (no out-of-bounds)
  - half-court fold symmetry + clamping of negative / overflow y
  - pure function with no side effects (deterministic, no global mutation)
"""
from __future__ import annotations

import pytest

from backend.services.tactics_engine import coords


def test_boundary_x_neg250_maps_to_left_edge():
    px, py = coords.map_xy_to_svg(-250, 0)
    assert px == 0.0
    assert py == 470.0  # y=0 baseline -> bottom of half court


def test_boundary_x_pos250_maps_to_right_edge():
    px, py = coords.map_xy_to_svg(250, 0)
    assert px == 500.0
    assert py == 470.0


def test_y_zero_is_bottom_baseline():
    px, py = coords.map_xy_to_svg(0, 0)
    assert py == 470.0
    assert px == 250.0  # x=0 -> horizontal centre


def test_full_court_y94_folds_within_range():
    # Source is a full-court frame; y=94 folds to py in [0,470].
    px, py = coords.map_xy_to_svg(0, 94)
    assert 0.0 <= py <= 470.0
    # concrete: _fold_half(94) = min(94, 940-94) = 94 -> py = 470 - 94 = 376
    assert py == 376.0


def test_full_sweep_stays_in_bounds():
    # Cover the full observed + theoretical source range.
    for x in range(-250, 251, 25):
        for y in range(-60, 901, 60):
            px, py = coords.map_xy_to_svg(x, y)
            assert 0.0 <= px <= 500.0, (x, y, px)
            assert 0.0 <= py <= 470.0, (x, y, py)


def test_fold_half_symmetry_and_anchors():
    # Full-court folding is symmetric about the half-court line (y=470).
    assert coords._fold_half(200) == coords._fold_half(740)  # 940 - 740 = 200
    assert coords._fold_half(123) == coords._fold_half(817)  # 940 - 817 = 123
    assert coords._fold_half(0) == 0.0
    assert coords._fold_half(470) == 470.0
    assert coords._fold_half(940) == 0.0


def test_fold_half_clamps_negative_and_overflow():
    # Negative / overflow y must be clamped before folding (architecture §8.1).
    assert coords._fold_half(-100) == 0.0
    assert coords._fold_half(2000) == 0.0  # clamped to 940 -> fold -> 0


def test_deterministic_and_no_side_effects():
    before = (coords.SVG_W, coords.SVG_H, coords.PX_PER_UNIT, coords.FULL_COURT_Y)
    r1 = coords.map_xy_to_svg(123, 456)
    r2 = coords.map_xy_to_svg(123, 456)
    assert r1 == r2
    assert r1 == (coords.SVG_W / 2.0 + 123, coords.SVG_H - coords._fold_half(456))
    after = (coords.SVG_W, coords.SVG_H, coords.PX_PER_UNIT, coords.FULL_COURT_Y)
    assert before == after  # no global mutation
    # distinct inputs -> distinct outputs
    assert coords.map_xy_to_svg(10, 10) != coords.map_xy_to_svg(-10, 10)
