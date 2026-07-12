"""Requirements 3, 4, 5 — PBP replay sequence, NULL/(0,0) red line, AST bubble.

Requirement 3 (real PBP event sequence):
  - service.replay(game 22400740, 2025) -> frames with t/players/ball/annotations/event_index
  - every coordinate inside [0,500]x[0,470] (out-of-bounds count = 0)
  - event annotations contain MAKE/MISS; spot-check a make shows the ✅ text

Requirement 4 (NULL/(0,0) red line, architecture §8.4):
  - frame JSON never contains (0,0) as a court coordinate
  - non-shot events pos_source in {last_known, default}; shot events pos_source='real'
  - players never teleport to (0,0)

Requirement 5 (AST assist bubble, synthetic event):
  - a make event with player2 produces BOTH MAKE + AST bubbles
  - real 2025 data has no player2 (data gap, NOT a code defect -> not asserted here)
"""
from __future__ import annotations

import pytest

from backend.services.tactics_engine import db, replay_engine
from backend.services.tactics_engine.schemas import PbPEvent

pytestmark = pytest.mark.needs_db


# ───────────────────────── Requirement 3 ─────────────────────────
def test_real_replay_frame_structure(real_frames):
    data = real_frames
    assert data["game_id"] == "22400740"
    frames = data["frames"]
    assert len(frames) > 0
    for key in ("t", "players", "ball", "annotations", "event_index"):
        assert key in frames[0], key
    # every frame must carry a ball sprite
    assert all(f["ball"] is not None for f in frames)


def test_real_replay_coords_in_bounds(real_frames):
    # 回放现恒走全场（full_court=True）：坐标须落在 [0, 940] x [0, 500]
    oob = 0
    for fr in real_frames["frames"]:
        for p in fr["players"]:
            if not (0.0 <= p["x_px"] <= 940.0 and 0.0 <= p["y_px"] <= 500.0):
                oob += 1
        b = fr["ball"]
        if not (0.0 <= b["x_px"] <= 940.0 and 0.0 <= b["y_px"] <= 500.0):
            oob += 1
    assert oob == 0, f"{oob} out-of-bounds coordinates found"


def test_real_replay_has_make_and_miss(real_frames):
    types = set()
    for fr in real_frames["frames"]:
        for a in fr["annotations"]:
            types.add(a["type"])
    assert "MAKE" in types, "no MAKE annotation in replay frames"
    assert "MISS" in types, "no MISS annotation in replay frames"
    has_check = any(
        a["type"] == "MAKE" and a["text"] == "✅"
        for fr in real_frames["frames"]
        for a in fr["annotations"]
    )
    assert has_check, "no MAKE annotation carrying the ✅ text"


# ───────────────────────── Requirement 4 ─────────────────────────
def test_frame_json_never_contains_zero_placeholder(real_frames):
    bad = 0
    for fr in real_frames["frames"]:
        for p in fr["players"]:
            if p["x_px"] == 0.0 and p["y_px"] == 0.0:
                bad += 1
        b = fr["ball"]
        if b["x_px"] == 0.0 and b["y_px"] == 0.0:
            bad += 1
    assert bad == 0, f"{bad} sprites sitting at the (0,0) placeholder"


def test_pos_source_membership_at_frame_level(real_frames):
    # Architecture §8.4/§8.5: frame-level pos_source must be one of the three
    # allowed strategies; it is a debug/transparency hint the frontend ignores.
    allowed = {"real", "last_known", "default"}
    seen = set()
    for fr in real_frames["frames"]:
        for p in fr["players"]:
            seen.add(p.get("pos_source"))
            assert p.get("pos_source") in allowed, p
    # Every frame-level pos_source is within the allowed set.
    assert seen <= allowed
    # Real-shot positions do reach the rendered frames (verifies no (0,0) leak
    # and that real coordinates are surfaced, not collapsed to placeholders).
    assert "real" in seen


def test_resolve_positions_pos_source_rule():
    events = db.load_pbp_events("22400740", "2025")
    resolved = replay_engine.resolve_positions(events)
    for re in resolved:
        is_real_shot = re.action_verb in ("makes", "misses") and (re.x != 0 or re.y != 0)
        if is_real_shot:
            assert re.actor_pos_source == "real", (
                re.event_index, re.action_verb, re.x, re.y,
            )
        elif re.player:
            # non-shot actor -> last-known / default placeholder strategy
            assert re.actor_pos_source in ("last_known", "default"), (
                re.event_index, re.player, re.actor_pos_source,
            )


# ───────────────────────── Requirement 5 ─────────────────────────
def test_synthetic_make_with_assist_double_bubble():
    events = [
        PbPEvent(event_index=0, game_id="SYN", season="2025", period=1,
                 clock_seconds=100.0, action_verb="rebound", player="B",
                 team="UTA", x=0, y=0, dist=0),
        PbPEvent(event_index=1, game_id="SYN", season="2025", period=1,
                 clock_seconds=98.0, action_verb="makes", player="A",
                 player2="B", team="UTA", x=100, y=200, dist=20),
    ]
    resolved = replay_engine.resolve_positions(events)
    anns = resolved[1].annotation
    types = [a["type"] for a in anns]
    assert "MAKE" in types
    assert "AST" in types
    make_ann = next(a for a in anns if a["type"] == "MAKE")
    ast_ann = next(a for a in anns if a["type"] == "AST")
    assert make_ann["text"] == "✅"
    # AST must be placed at player B's known position, never at (0,0)
    assert not (ast_ann["x_px"] == 0.0 and ast_ann["y_px"] == 0.0)
    # MAKE at the real shot location, never at (0,0)
    assert not (make_ann["x_px"] == 0.0 and make_ann["y_px"] == 0.0)
    # AST and MAKE should be at different spots (B != shooter A)
    assert (ast_ann["x_px"], ast_ann["y_px"]) != (make_ann["x_px"], make_ann["y_px"])


def test_synthetic_make_assist_unknown_player2_no_zero():
    # player2 never appeared -> AST still emitted (falls back to shooter position)
    events = [
        PbPEvent(event_index=0, game_id="SYN", season="2025", period=1,
                 clock_seconds=98.0, action_verb="makes", player="A",
                 player2="B", team="UTA", x=100, y=200, dist=20),
    ]
    resolved = replay_engine.resolve_positions(events)
    anns = resolved[0].annotation
    types = [a["type"] for a in anns]
    assert "MAKE" in types and "AST" in types
    for a in anns:
        assert not (a["x_px"] == 0.0 and a["y_px"] == 0.0)
