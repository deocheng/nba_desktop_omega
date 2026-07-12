"""Regression tests for the two PBP replay bugs (Ball-follows-holder + zero-coord shots).

Bug 1 — Ball does not follow the carrier:
    In ``build_frames`` the ball used to be linearly interpolated between
    ``e0.ball`` and ``e1.ball``. When ``e1`` is a non-holder event (foul,
    turnover, next possession) the ball "flew" to ``e1``'s actor. The fix tracks
    the *segment-start holder*'s interpolated sprite instead.

    Asserted invariant: for every rendered frame whose ``ball.holder`` is set,
    the ball pixel position equals that holder's player-sprite position
    (the ball is glued to the carrier, never to a bystander).

Bug 2 — Missing shot animation for (0,0) attempts:
    ``resolve_positions`` used to require ``(x, y) != (0, 0)`` to treat a
    makes/misses event as a shot. Many BR-source PBP rows have (0,0) shot
    coordinates, so they were rendered as ordinary possession events (ball glued
    to the shooter's frozen last-known position, no MAKE/MISS-to-rim motion).

    Fix: every makes/misses is a shot (MAKE/MISS annotation + ball release).
    When coordinates are missing the ball falls back to the rim (coords.RIM_PX)
    — never (0,0) — so the user sees a shot at the basket.
"""
from __future__ import annotations

import json

import pytest

from backend.services.tactics_engine import (
    animation,
    coords,
    db,
    replay_engine,
    service,
)
from backend.services.tactics_engine.schemas import PbPEvent, ReplayRequest


def _ev(index, verb, player="", team="", x=0, y=0, player2="", period=1, clock=100.0):
    return PbPEvent(
        event_index=index, game_id="SYN", season="2025", period=period,
        clock_seconds=clock, action_verb=verb, player=player, player2=player2,
        team=team, x=x, y=y, dist=0,
    )


# ───────────────────────── Bug 1: ball follows segment-start holder ─────────────────────────
def test_ball_follows_holder_not_nonholder_actor():
    """Ball must track the carrier (A), never fly to the next event's actor (B).

    A is first anchored at a real coordinate via a shot (so its sprite is far
    from B's default slot), then A holds the ball (rebound) while B draws a
    foul. During the [rebound, foul] segment the ball must stay on A even though
    the next event (foul) belongs to B — under the old code it flew to B.
    """
    events = [
        _ev(0, "makes", "A", "UTA", x=200, y=800, clock=100.0),   # shot: anchor A at real spot
        _ev(1, "rebound", "A", "UTA", x=0, y=0, clock=98.0),      # A holds (last_known real)
        _ev(2, "foul", "B", "LAL", x=0, y=0, clock=96.0),         # B (non-holder)
    ]
    resolved = replay_engine.resolve_positions(events)
    frames = animation.build_frames(resolved, fps=10)

    # holder "A" only in the [rebound, foul] segment
    seg = [fr for fr in frames if fr["ball"]["holder"] == "A"]
    assert seg, "expected a possession segment held by A"
    a_real = coords.map_xy_to_svg(200, 800)   # A's anchored real spot
    max_ball_to_holder = 0.0
    min_ball_to_b = float("inf")
    for fr in seg:
        h = next((p for p in fr["players"] if p["player_id"] == "A"), None)
        assert h is not None, "carrier sprite must be present in frame"
        d_holder = ((fr["ball"]["x_px"] - h["x_px"]) ** 2 +
                    (fr["ball"]["y_px"] - h["y_px"]) ** 2) ** 0.5
        max_ball_to_holder = max(max_ball_to_holder, d_holder)
        b_sprite = next((p for p in fr["players"] if p["player_id"] == "B"), None)
        if b_sprite:
            d_b = ((fr["ball"]["x_px"] - b_sprite["x_px"]) ** 2 +
                   (fr["ball"]["y_px"] - b_sprite["y_px"]) ** 2) ** 0.5
            min_ball_to_b = min(min_ball_to_b, d_b)
    # ball coincides with carrier sprite (sub-pixel rounding) ...
    assert max_ball_to_holder < 1.5, f"ball drifted from holder by {max_ball_to_holder}"
    # ... and is far from the non-holder actor B (would be ~0 under the old bug)
    assert min_ball_to_b > 100.0, f"ball got too close to non-holder B ({min_ball_to_b})"


@pytest.mark.needs_db
def test_ball_never_flies_to_nonholder_on_real_game():
    """Real-game invariant: for every frame with a holder, ball == holder sprite."""
    events = db.load_pbp_events("22400740", "2025")
    frames = replay_engine.build_frames_from_events(events, fps=10)["frames"]
    offenders = 0
    for fr in frames:
        holder = fr["ball"].get("holder") if fr.get("ball") else None
        if not holder:
            continue
        sprite = next((p for p in fr["players"] if p["player_id"] == holder), None)
        if sprite is None:
            offenders += 1
            continue
        d = ((fr["ball"]["x_px"] - sprite["x_px"]) ** 2 +
             (fr["ball"]["y_px"] - sprite["y_px"]) ** 2) ** 0.5
        if d > 2.0:
            offenders += 1
    assert offenders == 0, f"{offenders} frames where ball != holder sprite"


# ───────────────────────── Bug 2: zero-coord shots still render ─────────────────────────
def test_zero_coord_make_produces_make_annotation_and_rim_ball():
    events = [_ev(0, "makes", "A", "UTA", x=0, y=0, clock=100.0)]
    resolved = replay_engine.resolve_positions(events)
    re = resolved[0]
    types = [a["type"] for a in re.annotation]
    assert "MAKE" in types
    make_ann = next(a for a in re.annotation if a["type"] == "MAKE")
    assert make_ann["text"] == "✅"
    # ball released to rim, never (0,0); holder cleared (shot)
    assert re.ball["holder"] is None
    assert (re.ball["x_px"], re.ball["y_px"]) == coords.RIM_PX
    assert not (re.ball["x_px"] == 0.0 and re.ball["y_px"] == 0.0)
    # pos_source must stay non-real (architecture pos_source contract)
    assert re.actor_pos_source in ("last_known", "default")


def test_zero_coord_miss_produces_miss_annotation_and_rim_ball():
    events = [_ev(0, "misses", "A", "UTA", x=0, y=0, clock=100.0)]
    resolved = replay_engine.resolve_positions(events)
    re = resolved[0]
    types = [a["type"] for a in re.annotation]
    assert "MISS" in types
    assert re.ball["holder"] is None
    assert (re.ball["x_px"], re.ball["y_px"]) == coords.RIM_PX
    assert not (re.ball["x_px"] == 0.0 and re.ball["y_px"] == 0.0)


def test_real_coord_make_still_real_with_make_annotation():
    """Regression guard: real-coordinate shots keep pos_source='real'."""
    events = [_ev(0, "makes", "A", "UTA", x=120, y=240, clock=100.0)]
    resolved = replay_engine.resolve_positions(events)
    re = resolved[0]
    assert re.actor_pos_source == "real"
    assert "MAKE" in [a["type"] for a in re.annotation]
    assert re.ball["holder"] is None
    assert (re.ball["x_px"], re.ball["y_px"]) == coords.map_xy_to_svg(120, 240)


def test_zero_coord_shot_segment_ball_lands_at_rim_no_zero():
    """Full frame build: a (0,0) shot puts the ball at the rim for its segment."""
    events = [
        _ev(0, "rebound", "A", "UTA", x=200, y=800, clock=100.0),
        _ev(1, "makes", "A", "UTA", x=0, y=0, clock=98.0),
        _ev(2, "turnover", "C", "LAL", x=0, y=0, clock=96.0),
    ]
    resolved = replay_engine.resolve_positions(events)
    frames = animation.build_frames(resolved, fps=10)

    saw_rim = False
    for fr in frames:
        # red line: never (0,0)
        assert not (fr["ball"]["x_px"] == 0.0 and fr["ball"]["y_px"] == 0.0)
        # during the [makes, turnover] segment the ball sits at the rim
        if fr["ball"]["holder"] is None:
            d = ((fr["ball"]["x_px"] - coords.RIM_PX[0]) ** 2 +
                 (fr["ball"]["y_px"] - coords.RIM_PX[1]) ** 2) ** 0.5
            if d < 1.5:
                saw_rim = True
    assert saw_rim, "no frame placed the ball at the rim for the (0,0) shot"
    # MAKE annotation must surface in the shot segment
    assert any(
        a["type"] == "MAKE"
        for fr in frames for a in fr["annotations"]
    )


@pytest.mark.needs_db
def test_zero_coord_shots_in_real_game_never_place_ball_at_zero():
    """Real-game red line: a game with (0,0) shot rows keeps the ball off (0,0)."""
    events = db.load_pbp_events("22500240", "2026")
    frames = replay_engine.build_frames_from_events(events, fps=10)["frames"]
    bad = sum(
        1 for fr in frames
        if fr.get("ball") and fr["ball"]["x_px"] == 0.0 and fr["ball"]["y_px"] == 0.0
    )
    assert bad == 0, f"{bad} frames with ball at (0,0) placeholder"


# ───────────────────────── Frame-budget regression (load-failure bug) ─────────────────────────
def test_large_synthetic_sequence_respects_frame_budget():
    """Offline, deterministic guard: a ~600-event synthetic sequence yields <= 5000 frames.

    Regression for the PBP replay load-failure bug. Before the per-segment cap the
    same sequence emitted ~36k frames (~89MB) because every 2s segment got
    round(2*30)=60 pre-computed frames. The cap keeps the payload small while the
    frame structure (t/players/ball/annotations/event_index) stays identical, so the
    frontend (rAF + SVG) consumes it with zero changes.
    """
    events = [
        _ev(
            i,
            "makes" if i % 7 == 0 else "rebound",
            f"P{i % 10}",
            "UTA" if i % 2 == 0 else "LAL",
            x=100 + (i % 5) * 10,
            y=300 + (i % 7) * 20,
            clock=100.0 - i * 2.0,
        )
        for i in range(600)
    ]
    resolved = replay_engine.resolve_positions(events)
    frames = animation.build_frames(resolved, fps=30)
    assert frames, "frames must be non-empty"
    assert len(frames) <= 5000, f"synthetic 600-event seq produced {len(frames)} frames"
    first = frames[0]
    for key in ("t", "players", "ball", "annotations", "event_index"):
        assert key in first, key
    assert first["players"], "first frame must carry player sprites"
    assert first["ball"] is not None, "first frame must carry a ball sprite"


@pytest.mark.needs_db
def test_replay_response_frame_budget_and_contract_real_game():
    """Hard requirement (online): game 22500001/2026 must return <= 5000 frames AND a
    serialized payload < 15MB, while preserving the first-frame structure, the
    ball-follows-holder invariant (Bug 1), and MAKE/MISS annotations (Bug 2, incl.
    zero-coord shots).

    This is the regression guard that proves the load-failure bug is fixed end-to-end
    through the real ``TacticsService.replay`` path (DB -> resolve -> build_frames).
    """
    events = db.load_pbp_events("22500001", "2026")
    assert len(events) >= 400, "expected a full ~600-event game for the budget test"

    svc = service.TacticsService()
    result = svc.replay(ReplayRequest(game_id="22500001", season="2026", frame_rate=30))
    frames = result["frames"]
    meta = result["meta"]

    # Frame budget (hard cap for <15MB payload)
    assert frames, "frames must be non-empty"
    assert len(frames) <= 5000, f"frames={len(frames)} exceeds 5000 budget"
    # Serialized payload estimate must be well under the 15MB hard limit
    payload_bytes = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    assert payload_bytes < 15_000_000, f"payload={payload_bytes} bytes >= 15MB"

    # First-frame structure preserved (frontend consumes these keys)
    first = frames[0]
    for key in ("t", "players", "ball", "annotations", "event_index"):
        assert key in first, key
    assert first["players"], "first frame must carry player sprites"
    assert first["ball"] is not None, "first frame must carry a ball sprite"
    # meta.fps must equal the actual generation fps (frontend tick() relies on it)
    assert meta["fps"] == service.REPLAY_FPS_CAP, (
        f"meta.fps={meta['fps']} must equal clamped REPLAY_FPS_CAP={service.REPLAY_FPS_CAP}"
    )

    # Bug 1 invariant: whenever ball has a holder, ball == holder sprite
    offenders = 0
    for fr in frames:
        holder = fr["ball"].get("holder") if fr.get("ball") else None
        if not holder:
            continue
        sprite = next((p for p in fr["players"] if p["player_id"] == holder), None)
        if sprite is None:
            offenders += 1
            continue
        d = ((fr["ball"]["x_px"] - sprite["x_px"]) ** 2 +
             (fr["ball"]["y_px"] - sprite["y_px"]) ** 2) ** 0.5
        if d > 2.0:
            offenders += 1
    assert offenders == 0, f"{offenders} frames where ball != holder sprite"

    # Bug 2 invariant: MAKE/MISS annotations still surface
    types = {a["type"] for fr in frames for a in fr["annotations"]}
    assert "MAKE" in types, "no MAKE annotation in replay frames"
    assert "MISS" in types, "no MISS annotation in replay frames"
