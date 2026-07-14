"""Requirement B1 — Full-court coordinate mapping (coords.map_xy_to_svg_full).

Verifies:
  - boundary mapping matches the design table, all within [0, 940] x [0, 500]
  - nearest_rim picks the correct left/right basket and never returns (0, 0)
  - existing half-court map_xy_to_svg (templates) is untouched
"""
from __future__ import annotations

import pytest

from backend.services.tactics_engine import coords


def test_fullcourt_boundary_table():
    cases = [
        ((-250, 0), (0.0, 0.0)),
        ((250, 0), (0.0, 500.0)),
        ((-250, 940), (940.0, 0.0)),
        ((250, 940), (940.0, 500.0)),
        ((0, 0), (0.0, 250.0)),
        ((0, 940), (940.0, 250.0)),
        ((0, 470), (470.0, 250.0)),
    ]
    for src, expected in cases:
        got = coords.map_xy_to_svg_full(*src)
        assert got == expected, (src, got, expected)


def test_fullcourt_sweep_stays_in_bounds():
    for x in range(-250, 251, 25):
        for y in range(0, 941, 60):
            sx, sy = coords.map_xy_to_svg_full(x, y)
            assert 0.0 <= sx <= 940.0, (x, y, sx)
            assert 0.0 <= sy <= 500.0, (x, y, sy)


def test_nearest_rim_left_for_left_half():
    assert coords.nearest_rim(0, 0) == coords.RIM_PX_LEFT
    assert coords.nearest_rim(100, 469) == coords.RIM_PX_LEFT
    # 兜底绝不为 (0, 0)
    assert coords.nearest_rim(0, 0) != (0.0, 0.0)


def test_nearest_rim_right_for_right_half():
    assert coords.nearest_rim(0, 470) == coords.RIM_PX_RIGHT
    assert coords.nearest_rim(-100, 800) == coords.RIM_PX_RIGHT
    assert coords.RIM_PX_LEFT == (0.0, 250.0)
    assert coords.RIM_PX_RIGHT == (940.0, 250.0)


def test_fullcourt_constants():
    assert coords.FULL_SVG_W == 940
    assert coords.FULL_SVG_H == 500


def test_halfcourt_map_untouched():
    # 回归守卫：半场映射器（战术板模板）保持不变
    px, py = coords.map_xy_to_svg(0, 0)
    assert px == 250.0 and py == 470.0
