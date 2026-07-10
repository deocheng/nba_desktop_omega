"""NBACore v8 — Fusion Clutch Replay mapper (pure Python, no DB math).

Implements the deterministic 3-key bridge (architecture §8.1):

    eventnum  ──(br_crawler same-order query)──▶  event_index
    event_index ──(first matching frame)─────────▶  frame_index

All queries go through ``backend.core.db.batch_query`` (SELECT-only). No
coordinate math, no interpolation, no clutch-window evaluation — those stay in
``tactics_engine`` / ``clutch_engine`` respectively (v8 §6 isolation).

Design note on :func:`build_segments`
-------------------------------------
The documented contract keeps ``build_segments(clutch_event_indices, frames, pad)``
taking only integer event indices (architecture §3.1) so the signature stays
stable and unit-testable without a database. It therefore returns segments with
the ``event_index`` / ``frame_index`` ranges resolved; the richer per-segment
fields (``period`` / ``clock_start`` / ``clock_end`` / ``players`` / ``margin``)
are populated by the service, which owns the original clutch-event details and
simply tags each resolved range. This split honours the exact function signature
while still producing a fully-populated :class:`ClutchSegment`.
"""
from __future__ import annotations

from typing import Dict, List

from backend.core import db as core_db
from backend.services.clutch_replay_engine import schemas


def build_eventnum_to_index_map(gameid: str, season) -> Dict[int, int]:
    """Build ``{eventnum: event_index}`` for one game's br_crawler PBP events.

    Uses the *exact* ordering of ``tactics_engine.db.load_pbp_events``
    (``period ASC, clock_seconds DESC, id ASC``) so the resulting row index
    matches the ``event_index`` written into replay frames. Duplicate
    ``eventnum`` values keep their *first* occurrence (architecture §9 ①).
    """
    sql = """
        SELECT eventnum
        FROM play_by_play
        WHERE gameid = %s
          AND season = %s::integer
          AND source = 'br_crawler'
        ORDER BY period ASC, clock_seconds DESC, id ASC
    """
    rows = core_db.batch_query(sql, (str(gameid), int(season)))
    mapping: Dict[int, int] = {}
    for i, r in enumerate(rows):
        en = int(r["eventnum"])
        if en not in mapping:  # keep first occurrence
            mapping[en] = i
    return mapping


def first_frame_for_event_index(frames: List[dict], event_index: int) -> int:
    """Return the index of the first frame whose ``event_index == event_index``.

    Deterministic (first match). Returns ``-1`` when no frame carries the index.
    """
    for i, f in enumerate(frames):
        if f.get("event_index") == event_index:
            return i
    return -1


def build_segments(
    clutch_event_indices: List[int],
    frames: List[dict],
    pad: int = 2,
) -> List[schemas.ClutchSegment]:
    """Resolve clutch event indices into frame-anchored highlight segments.

    1. For each clutch ``event_index`` anchor, build a window
       ``[ei - pad, ei + pad]`` (clamped to the frame sequence bounds).
    2. Merge overlapping / near windows where the gap between consecutive
       windows is ``<= pad`` (architecture §9 ④).
    3. Map each merged window's start/end ``event_index`` to its first frame.

    The returned :class:`ClutchSegment` objects carry only the resolved
    ``event_index`` / ``frame_index`` ranges and default detail fields; the
    service enriches them with period / clock / players / margin afterwards.
    """
    if not frames:
        return []
    max_ei = max((f.get("event_index", -1) for f in frames), default=-1)
    if max_ei < 0:
        return []

    raw: List[List[int]] = []
    for ei in clutch_event_indices:
        start_ei = max(0, ei - pad)
        end_ei = min(max_ei, ei + pad)
        if start_ei <= end_ei:
            raw.append([start_ei, end_ei])
    if not raw:
        return []

    raw.sort(key=lambda w: w[0])
    merged: List[List[int]] = [list(raw[0])]
    for s, e in raw[1:]:
        if s - merged[-1][1] <= pad:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    segments: List[schemas.ClutchSegment] = []
    for s_ei, e_ei in merged:
        start_frame = first_frame_for_event_index(frames, s_ei)
        end_frame = first_frame_for_event_index(frames, e_ei)
        if start_frame < 0 or end_frame < 0 or start_frame > end_frame:
            continue
        segments.append(schemas.ClutchSegment(
            start_event_index=s_ei,
            end_event_index=e_ei,
            start_frame=start_frame,
            end_frame=end_frame,
            period=0,
            clock_start=0.0,
            clock_end=0.0,
            players=[],
            margin=0,
        ))
    return segments
