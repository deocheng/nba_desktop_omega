"""Unit tests for the clutch-replay mapper (pure Python, no real DB).

`build_eventnum_to_index_map` is exercised with a monkeypatched
``backend.core.db.batch_query`` so the tests stay deterministic and offline.
"""
from __future__ import annotations

import pytest

from backend.services.clutch_replay_engine import mapper


def test_clutch_replay_mapper_first_frame():
    frames = [{"event_index": 0}, {"event_index": 0}, {"event_index": 3}, {"event_index": 5}]
    assert mapper.first_frame_for_event_index(frames, 3) == 2
    assert mapper.first_frame_for_event_index(frames, 0) == 0
    assert mapper.first_frame_for_event_index(frames, 9) == -1


def test_clutch_replay_mapper_eventnum_map(monkeypatch):
    captured = {}

    def fake_batch_query(sql, params=None):
        captured["sql"] = sql
        # ordered by period ASC, clock_seconds DESC, id ASC (same as tactics)
        return [
            {"eventnum": 100},
            {"eventnum": 101},
            {"eventnum": 100},  # duplicate -> first occurrence wins
        ]

    monkeypatch.setattr("backend.core.db.batch_query", fake_batch_query)
    mapping = mapper.build_eventnum_to_index_map("G1", 2025)
    assert mapping == {100: 0, 101: 1}
    # must restrict to br_crawler and the same ordering
    assert "source = 'br_crawler'" in captured["sql"]
    assert "ORDER BY period ASC, clock_seconds DESC, id ASC" in " ".join(captured["sql"].split())


def test_clutch_replay_mapper_build_segments_merge():
    frames = [{"event_index": i} for i in range(10)]
    # ei=5 -> [3,7]; ei=7 -> [5,9]; merge (gap 5-7 <= 2) -> [3,9]
    segs = mapper.build_segments([5, 7], frames, pad=2)
    assert len(segs) == 1
    s = segs[0]
    assert s.start_event_index == 3 and s.end_event_index == 9
    assert s.start_frame == 3 and s.end_frame == 9


def test_clutch_replay_mapper_build_segments_disjoint():
    frames = [{"event_index": i} for i in range(20)]
    # ei=1 -> [0,3]; ei=12 -> [10,14]; gap 7 > pad(2) -> two segments
    segs = mapper.build_segments([1, 12], frames, pad=2)
    assert len(segs) == 2
    assert segs[0].start_event_index == 0 and segs[0].end_event_index == 3
    assert segs[1].start_event_index == 10 and segs[1].end_event_index == 14


def test_clutch_replay_mapper_build_segments_empty_frames():
    assert mapper.build_segments([1, 2], [], pad=2) == []
    assert mapper.build_segments([], [{"event_index": 0}], pad=2) == []


def test_clutch_replay_mapper_build_segments_clamps():
    frames = [{"event_index": i} for i in range(5)]  # indices 0..4
    segs = mapper.build_segments([0], frames, pad=2)  # [0,2] (no negative)
    assert segs[0].start_event_index == 0 and segs[0].end_event_index == 2
