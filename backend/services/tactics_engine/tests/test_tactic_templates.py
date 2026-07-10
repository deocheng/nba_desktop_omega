"""Requirement 2 — Tactic templates (decision: >=8 built-in).

Verifies:
  - list_templates() returns >= 8 templates with unique ids
  - get_template(id) returns formation (5 players) + steps (paths)
  - build_frames_from_template produces frames with legal 5-man initial spotting
  - path interpolation produces displacement (animation actually moves players)
  - all generated coordinates stay inside the 500×470 court (no out-of-bounds)
  - no (0,0) placeholder leaks into template frames
"""
from __future__ import annotations

import pytest

from backend.services.tactics_engine import animation, tactic_templates


def test_list_templates_has_at_least_8():
    tpls = tactic_templates.list_templates()
    assert len(tpls) >= 8
    ids = [t["id"] for t in tpls]
    assert len(ids) == len(set(ids))  # unique ids


def test_get_template_formation_and_steps():
    for t in tactic_templates.all_templates():
        assert len(t.formation) == 5, f"{t.id} must have 5 players"
        assert len(t.steps) >= 1, f"{t.id} must have >=1 step"
        slots = {s.slot for s in t.formation}
        for st in t.steps:
            assert st.actor_slot in slots, (t.id, st.actor_slot)


def test_get_template_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        tactic_templates.get_template("does_not_exist")


def test_build_frames_from_template_structure():
    t = tactic_templates.get_template("pick_and_roll")
    frames = animation.build_frames_from_template(t, fps=30)
    assert len(frames) > 0
    f0 = frames[0]
    assert set(f0.keys()) >= {"t", "players", "ball", "annotations", "event_index"}
    assert len(f0["players"]) == 5  # 5-man initial spotting
    assert f0["ball"] is not None
    assert "x_px" in f0["ball"] and "y_px" in f0["ball"]


def test_template_frames_in_bounds():
    for t in tactic_templates.all_templates():
        frames = animation.build_frames_from_template(t, fps=30)
        for fr in frames:
            for p in fr["players"]:
                assert 0.0 <= p["x_px"] <= 500.0, (t.id, p)
                assert 0.0 <= p["y_px"] <= 470.0, (t.id, p)
            b = fr["ball"]
            assert 0.0 <= b["x_px"] <= 500.0, (t.id, b)
            assert 0.0 <= b["y_px"] <= 470.0, (t.id, b)


def test_template_frames_no_placeholder_zero():
    for t in tactic_templates.all_templates():
        frames = animation.build_frames_from_template(t, fps=20)
        for fr in frames:
            for p in fr["players"]:
                assert not (p["x_px"] == 0.0 and p["y_px"] == 0.0), (t.id, p)
            b = fr["ball"]
            assert not (b["x_px"] == 0.0 and b["y_px"] == 0.0), (t.id, b)


def test_template_frames_produce_displacement():
    for t in tactic_templates.all_templates():
        frames = animation.build_frames_from_template(t, fps=20)
        f0 = {p["player_id"]: (p["x_px"], p["y_px"]) for p in frames[0]["players"]}
        moved = False
        for fr in frames[1:]:
            for p in fr["players"]:
                if (p["x_px"], p["y_px"]) != f0.get(p["player_id"]):
                    moved = True
                    break
            if moved:
                break
        assert moved, f"template {t.id} produced no player movement"
