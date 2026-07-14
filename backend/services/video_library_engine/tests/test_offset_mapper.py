"""Unit tests for video_library_engine.offset_mapper (pure Python, no DB).

Validates the core offset mapping formulas and timeline construction
(architecture §8.1). These tests run without a database connection.
"""
from __future__ import annotations

import pytest

from backend.services.video_library_engine import offset_mapper
from backend.services.video_library_engine.schemas import EventTimeMark


# ── period_length ──

class TestPeriodLength:
    def test_q1_to_q4(self):
        assert offset_mapper.period_length(1) == 720
        assert offset_mapper.period_length(2) == 720
        assert offset_mapper.period_length(3) == 720
        assert offset_mapper.period_length(4) == 720

    def test_overtime(self):
        assert offset_mapper.period_length(5) == 300
        assert offset_mapper.period_length(6) == 300
        assert offset_mapper.period_length(7) == 300

    def test_invalid(self):
        assert offset_mapper.period_length(0) == 0
        assert offset_mapper.period_length(-1) == 0


# ── game_elapsed ──

class TestGameElapsed:
    def test_q1_start(self):
        """At Q1 12:00 (720s remaining), elapsed = 0."""
        assert offset_mapper.game_elapsed(1, 720.0) == 0.0

    def test_q1_end(self):
        """At Q1 0:00 (0s remaining), elapsed = 720."""
        assert offset_mapper.game_elapsed(1, 0.0) == 720.0

    def test_q2_start(self):
        """At Q2 12:00 (720s remaining), elapsed = 720 (one full quarter)."""
        assert offset_mapper.game_elapsed(2, 720.0) == 720.0

    def test_q2_end(self):
        """At Q2 0:00, elapsed = 720 + 720 = 1440."""
        assert offset_mapper.game_elapsed(2, 0.0) == 1440.0

    def test_q4_start(self):
        """At Q4 12:00, elapsed = 3 * 720 = 2160."""
        assert offset_mapper.game_elapsed(4, 720.0) == 2160.0

    def test_q4_5min(self):
        """At Q4 5:00 (300s remaining), elapsed = 2160 + (720-300) = 2580."""
        assert offset_mapper.game_elapsed(4, 300.0) == 2580.0

    def test_q4_end(self):
        """At Q4 0:00, elapsed = 4 * 720 = 2880."""
        assert offset_mapper.game_elapsed(4, 0.0) == 2880.0

    def test_ot_start(self):
        """At OT1 5:00 (300s remaining), elapsed = 2880."""
        assert offset_mapper.game_elapsed(5, 300.0) == 2880.0

    def test_ot_end(self):
        """At OT1 0:00, elapsed = 2880 + 300 = 3180."""
        assert offset_mapper.game_elapsed(5, 0.0) == 3180.0

    def test_invalid_period(self):
        assert offset_mapper.game_elapsed(0, 720.0) == 0.0
        assert offset_mapper.game_elapsed(-1, 720.0) == 0.0


# ── build_timeline ──

class TestBuildTimeline:
    def test_empty_events(self):
        """No events → empty timeline."""
        marks = offset_mapper.build_timeline([], [], 0.0)
        assert marks == []

    def test_basic_timeline(self):
        """Two events in Q1, offset=10 → video_time = 10 + game_elapsed."""
        events = [
            {"event_index": 0, "period": 1, "clock_seconds": 720.0},
            {"event_index": 1, "period": 1, "clock_seconds": 718.0},
        ]
        frames = [
            {"event_index": 0, "t": 0.0},
            {"event_index": 0, "t": 0.033},
            {"event_index": 1, "t": 0.066},
        ]
        marks = offset_mapper.build_timeline(events, frames, 10.0)
        assert len(marks) == 2

        # Event 0: Q1 12:00 → game_elapsed=0, video_time=10+0=10
        assert marks[0].event_index == 0
        assert marks[0].video_time == 10.0
        assert marks[0].frame_index == 0  # first frame with event_index==0

        # Event 1: Q1 11:58 → game_elapsed=2, video_time=10+2=12
        assert marks[1].event_index == 1
        assert marks[1].video_time == 12.0
        assert marks[1].frame_index == 2  # first frame with event_index==1

    def test_no_matching_frame(self):
        """Event with no matching frame → frame_index = -1."""
        events = [{"event_index": 5, "period": 1, "clock_seconds": 600.0}]
        frames = [{"event_index": 0, "t": 0.0}]
        marks = offset_mapper.build_timeline(events, frames, 0.0)
        assert len(marks) == 1
        assert marks[0].frame_index == -1

    def test_offset_applied(self):
        """Offset is added to game_elapsed for all events."""
        events = [
            {"event_index": 0, "period": 1, "clock_seconds": 720.0},
            {"event_index": 1, "period": 4, "clock_seconds": 300.0},
        ]
        frames = [
            {"event_index": 0},
            {"event_index": 1},
        ]
        marks = offset_mapper.build_timeline(events, frames, 12.5)
        # Event 0: offset + 0 = 12.5
        assert marks[0].video_time == 12.5
        # Event 1: offset + game_elapsed(4, 300) = 12.5 + 2580 = 2592.5
        assert marks[1].video_time == 2592.5

    def test_return_type(self):
        """Returns list of EventTimeMark."""
        events = [{"event_index": 0, "period": 1, "clock_seconds": 720.0}]
        frames = [{"event_index": 0}]
        marks = offset_mapper.build_timeline(events, frames, 0.0)
        assert len(marks) == 1
        assert isinstance(marks[0], EventTimeMark)


# ── attach_video_time ──

class TestAttachVideoTime:
    def test_empty_marks(self):
        """No marks → segments unchanged."""
        segs = [{"start_event_index": 0, "end_event_index": 5}]
        result = offset_mapper.attach_video_time(segs, [])
        assert result == segs

    def test_basic_attach(self):
        """Segments get video_time_start/end from marks lookup."""
        marks = [
            EventTimeMark(event_index=0, period=1, clock_seconds=720.0, frame_index=0, video_time=10.0),
            EventTimeMark(event_index=1, period=1, clock_seconds=718.0, frame_index=60, video_time=12.0),
            EventTimeMark(event_index=5, period=1, clock_seconds=710.0, frame_index=300, video_time=20.0),
        ]
        segs = [
            {"start_event_index": 0, "end_event_index": 5},
        ]
        result = offset_mapper.attach_video_time(segs, marks)
        assert result[0]["video_time_start"] == 10.0
        assert result[0]["video_time_end"] == 20.0

    def test_missing_event_index(self):
        """Missing end_event_index in marks → falls back to start's video_time."""
        marks = [
            EventTimeMark(event_index=0, period=1, clock_seconds=720.0, frame_index=0, video_time=10.0),
        ]
        segs = [
            {"start_event_index": 0, "end_event_index": 99},
        ]
        result = offset_mapper.attach_video_time(segs, marks)
        assert result[0]["video_time_start"] == 10.0
        # When end_event_index is missing, falls back to start's video_time (graceful degradation)
        assert result[0]["video_time_end"] == 10.0
