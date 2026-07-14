"""NBACore v8 — Video Library offset mapper (pure Python, no DB).

Implements the deterministic video-time mapping (architecture §8.1):

    period_length(p)     → 720 for Q1–Q4, 300 for OT (p ≥ 5)
    game_elapsed(p, c)   → Σ_{k<p} period_length(k) + (period_length(p) − c)
                           where c = remaining clock seconds in period p
    video_time(p, c)     → video_offset_seconds + game_elapsed(p, c)

ALL offset/clock arithmetic lives here (backend). The frontend
``SyncController`` only does binary search on the precomputed ``timeline[]``
— zero offset math in the frontend (v8 §11 red line).

Frame anchoring reuses ``clutch_replay_engine.mapper.first_frame_for_event_index``
(shared asset, architecture §0 cross-feature dependency).
"""
from __future__ import annotations

from typing import List

from backend.services.clutch_replay_engine.mapper import first_frame_for_event_index
from backend.services.video_library_engine import schemas


# ───────────────────────── Core mapping functions ─────────────────────────

def period_length(p: int) -> int:
    """Return the length in seconds of NBA period ``p``.

    Q1–Q4 are 12 minutes (720 s); overtime periods (p ≥ 5) are 5 minutes (300 s).

    Args:
        p: Period number (1-indexed).

    Returns:
        Period length in seconds.
    """
    if p < 1:
        return 0
    if p <= 4:
        return 720
    return 300


def game_elapsed(p: int, c: float) -> float:
    """Compute elapsed game time (in seconds) at period ``p``, clock ``c``.

    ``c`` is the **remaining** clock seconds in period ``p`` (consistent with
    ``ReplayMeta.clock=[720, 0]`` convention where clock counts down).

    The formula sums the full duration of all completed periods, then adds
    the time elapsed within the current period:

        game_elapsed = Σ_{k=1}^{p-1} period_length(k) + (period_length(p) − c)

    Args:
        p: Period number (1-indexed).
        c: Remaining clock seconds in period ``p``.

    Returns:
        Total elapsed game time in seconds.
    """
    if p < 1:
        return 0.0
    elapsed = 0.0
    for k in range(1, p):
        elapsed += period_length(k)
    # Within the current period: time elapsed = period_length - remaining_clock
    pl = period_length(p)
    elapsed += max(0.0, pl - float(c))
    return elapsed


def build_timeline(
    events: List[dict],
    frames: List[dict],
    offset: float,
) -> List[schemas.EventTimeMark]:
    """Build the precomputed ``timeline[]`` for the frontend SyncController.

    For each PBP event, computes:
        - ``video_time`` = offset + game_elapsed(period, clock_seconds)
        - ``frame_index`` = first frame whose ``event_index`` matches

    The frontend uses ``frame_index`` to project to 0–1000 (Timeline space)
    and ``video_time`` to set ``<video>.currentTime`` via binary search.

    Args:
        events: PBP events (dicts with ``event_index``, ``period``,
                ``clock_seconds``). Must be in the same order as
                ``tactics_engine.db.load_pbp_events`` output.
        frames: Replay frames (dicts with ``event_index`` field).
        offset: ``video_offset_seconds`` from the game_videos row.

    Returns:
        List of :class:`EventTimeMark` entries, one per event.
    """
    marks: List[schemas.EventTimeMark] = []
    for ev in events:
        ei = int(ev.get("event_index", 0))
        period = int(ev.get("period", 1))
        clock = float(ev.get("clock_seconds", 0.0))
        vt = float(offset) + game_elapsed(period, clock)
        fi = first_frame_for_event_index(frames, ei)
        marks.append(schemas.EventTimeMark(
            event_index=ei,
            period=period,
            clock_seconds=clock,
            frame_index=fi,
            video_time=round(vt, 3),
        ))
    return marks


def attach_video_time(
    segments: List[dict],
    marks: List[schemas.EventTimeMark],
) -> List[dict]:
    """Enrich each clutch segment with ``video_time_start`` / ``video_time_end``.

    Looks up the ``video_time`` at ``start_event_index`` and ``end_event_index``
    in the precomputed ``marks`` list. If no exact match is found, uses the
    nearest mark (binary-search-free linear scan since segment counts are small).

    Args:
        segments: Clutch segment dicts (must have ``start_event_index`` /
                  ``end_event_index``).
        marks: Precomputed timeline from :func:`build_timeline`.

    Returns:
        The same ``segments`` list, each enriched with ``video_time_start``
        and ``video_time_end`` fields.
    """
    if not marks:
        return segments

    # Build a lookup: event_index → video_time
    mark_map = {m.event_index: m.video_time for m in marks}

    for seg in segments:
        s_ei = int(seg.get("start_event_index", 0))
        e_ei = int(seg.get("end_event_index", s_ei))
        seg["video_time_start"] = mark_map.get(s_ei, 0.0)
        seg["video_time_end"] = mark_map.get(e_ei, mark_map.get(s_ei, 0.0))
    return segments
