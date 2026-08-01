"""Unit tests for video_library_engine.service (mocked DB + engines).

Tests the service orchestration logic without a live database. Validates
that get_playback correctly assembles PlaybackResponse, error handling for
missing video sources, and the analyzer contract.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.services.video_library_engine import schemas, service
from backend.services.video_library_engine.analyzer import (
    GameAnalyzer,
    LLMAnalyzer,
    REGISTRY,
    StaticAnalyzer,
)


# ── Analyzer contract ──

class TestStaticAnalyzer:
    def test_returns_game_analysis(self):
        analyzer = StaticAnalyzer()
        result = analyzer.analyze("GAME001", "2025", "/video-library/media/1")
        assert isinstance(result, schemas.GameAnalysis)
        assert result.game_id == "GAME001"
        assert result.season == "2025"
        assert len(result.summary) > 0
        assert len(result.segments) > 0

    def test_segments_have_required_fields(self):
        analyzer = StaticAnalyzer()
        result = analyzer.analyze("GAME001", "2025", "")
        for seg in result.segments:
            assert hasattr(seg, "event_index")
            assert hasattr(seg, "period_clock")
            assert hasattr(seg, "commentary")


class TestLLMAnalyzer:
    def test_raises_not_implemented(self):
        analyzer = LLMAnalyzer()
        with pytest.raises(NotImplementedError):
            analyzer.analyze("GAME001", "2025", "")


class TestRegistry:
    def test_registry_has_static(self):
        assert "static" in REGISTRY
        assert REGISTRY["static"] is StaticAnalyzer

    def test_registry_has_llm(self):
        assert "llm" in REGISTRY
        assert REGISTRY["llm"] is LLMAnalyzer

    def test_registry_classes_subclass_game_analyzer(self):
        for name, cls in REGISTRY.items():
            assert issubclass(cls, GameAnalyzer), f"{name} is not a GameAnalyzer subclass"


# ── Service: list_games (mocked DB) ──

class TestListGames:
    def test_empty_result(self):
        svc = service.VideoLibraryService()
        with patch.object(service.db, "list_games_with_flag", return_value=[]):
            req = schemas.VideoLibraryListRequest(season="2025")
            result = svc.list_games(req)
            assert result.total == 0
            assert result.games == []

    def test_games_with_video_flag(self):
        svc = service.VideoLibraryService()
        mock_rows = [
            {
                "game_id": "20250101_LAL_BOS",
                "season": 2025,
                "game_date": "2025-01-01",
                "home_team_abbr": "LAL",
                "away_team_abbr": "BOS",
                "home_pts": 110,
                "away_pts": 105,
                "video_id": 1,
                "video_source": "local_file",
            },
            {
                "game_id": "20250102_GSW_DEN",
                "season": 2025,
                "game_date": "2025-01-02",
                "home_team_abbr": "GSW",
                "away_team_abbr": "DEN",
                "home_pts": 108,
                "away_pts": 112,
                "video_id": None,
                "video_source": None,
            },
        ]
        with patch.object(service.db, "list_games_with_flag", return_value=mock_rows):
            req = schemas.VideoLibraryListRequest(season="2025")
            result = svc.list_games(req)
            assert result.total == 2
            assert result.games[0].has_video is True
            assert result.games[0].source == "local_file"
            assert result.games[0].score == "110-105"
            assert result.games[1].has_video is False
            assert result.games[1].source is None
            assert result.games[1].score == "108-112"


# ── Service: get_playback (mocked DB + clutch_replay) ──

class TestGetPlayback:
    def test_no_video_source_degrades_without_raise(self):
        """无录像源时不应整体 abort（原 40002 行为已改为降级）。

        修复后：video_ref 置空、video_ref_type='none'，仍继续用
        ClutchReplayService 构建 frames/timeline/clutch_segments（这些派生自 PBP，
        不依赖录像源）。前端在 video_ref 为空时显示占位，战术板 + 时间轴照常渲染。
        """
        svc = service.VideoLibraryService()
        mock_cr_result = MagicMock()
        mock_cr_result.frames = [
            {"event_index": 0, "t": 0.0},
            {"event_index": 1, "t": 0.033},
        ]
        mock_cr_result.meta = {"frame_count": 2, "fps": 30}
        mock_cr_result.clutch_segments = []
        mock_cr_result.clutch_players = []
        with patch.object(service.db, "get_video_source", return_value=None):
            with patch.object(svc._clutch_replay, "clutch_replay", return_value=mock_cr_result):
                with patch.object(service.VideoLibraryService, "_load_pbp_events_as_dicts",
                                  return_value=[{"event_index": 0, "period": 1, "clock_seconds": 720.0},
                                                {"event_index": 1, "period": 1, "clock_seconds": 718.0}]):
                    result = svc.get_playback("GAME001", "2025")
        # 关键契约：不抛 40002，返回空 video_ref + 非空 frames。
        assert result.video_ref == ""
        assert result.video_ref_type == "none"
        assert result.video_offset_seconds == 0.0
        assert len(result.frames) == 2

    def test_playback_with_frames(self):
        """Full playback path with mocked clutch_replay + events."""
        svc = service.VideoLibraryService()

        mock_source = {
            "id": 42,
            "gameid": "GAME001",
            "season": 2025,
            "source": "local_file",
            "video_url": None,
            "local_path": "2025/GAME001.mp4",
            "video_offset_seconds": 12.5,
            "created_at": "2025-01-01T00:00:00Z",
        }

        # Mock clutch_replay result
        mock_cr_result = MagicMock()
        mock_cr_result.frames = [
            {"event_index": 0, "t": 0.0},
            {"event_index": 0, "t": 0.033},
            {"event_index": 1, "t": 0.066},
        ]
        mock_cr_result.meta = {"frame_count": 3, "fps": 30}
        mock_cr_result.clutch_segments = []
        mock_cr_result.clutch_players = []

        # Mock PBP events
        mock_events = [
            MagicMock(event_index=0, period=1, clock_seconds=720.0),
            MagicMock(event_index=1, period=1, clock_seconds=718.0),
        ]

        with patch.object(service.db, "get_video_source", return_value=mock_source):
            with patch.object(svc._clutch_replay, "clutch_replay", return_value=mock_cr_result):
                with patch.object(service.VideoLibraryService, "_load_pbp_events_as_dicts",
                                  return_value=[{"event_index": 0, "period": 1, "clock_seconds": 720.0},
                                                {"event_index": 1, "period": 1, "clock_seconds": 718.0}]):
                    result = svc.get_playback("GAME001", "2025")

        assert result.game_id == "GAME001"
        assert result.season == "2025"
        assert result.video_ref == "/video-library/media/42"
        assert result.video_ref_type == "local"
        assert result.video_offset_seconds == 12.5
        assert len(result.frames) == 3
        assert len(result.timeline) == 2
        assert result.timeline[0].video_time == 12.5  # offset + game_elapsed(1, 720) = 12.5 + 0
        assert result.timeline[1].video_time == 14.5  # offset + game_elapsed(1, 718) = 12.5 + 2
        assert result.perspective == "viewer"


# ── Service: upsert_video_source (mocked) ──

class TestUpsertVideoSource:
    def test_game_not_found_raises_40001(self):
        svc = service.VideoLibraryService()
        req = schemas.UpsertVideoSourceRequest(
            gameid="NONEXISTENT", season="2025", source="other", video_url="http://test"
        )
        with patch.object(service.VideoLibraryService, "_game_exists", return_value=False):
            with pytest.raises(schemas.VideoLibraryError) as exc_info:
                svc.upsert_video_source(req)
            assert exc_info.value.code == 40001


# ── Service: analyze (mocked) ──

class TestAnalyze:
    def test_static_analyzer(self):
        svc = service.VideoLibraryService()
        with patch.object(service.db, "get_video_source", return_value=None):
            result = svc.analyze("GAME001", "2025", "static")
            assert result.game_id == "GAME001"
            assert len(result.summary) > 0

    def test_llm_analyzer_raises(self):
        svc = service.VideoLibraryService()
        with patch.object(service.db, "get_video_source", return_value=None):
            with pytest.raises(NotImplementedError):
                svc.analyze("GAME001", "2025", "llm")

    def test_unknown_provider_raises(self):
        svc = service.VideoLibraryService()
        with patch.object(service.db, "get_video_source", return_value=None):
            with pytest.raises(schemas.VideoLibraryError) as exc_info:
                svc.analyze("GAME001", "2025", "nonexistent")
            assert exc_info.value.code == 40001
