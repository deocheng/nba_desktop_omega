"""NBACore v8 — Video Library AI analyzer (P2 pluggable contract).

Defines the ``GameAnalyzer`` ABC and a registry (same pattern as
``tactics_engine.ai_generator.TacticGenerator``). v1 ships:

    - ``StaticAnalyzer``: returns a placeholder ``GameAnalysis`` (runnable,
      testable, no LLM call).
    - ``LLMAnalyzer``: raises ``NotImplementedError`` on call → mapped to
      code 50100 by the router (P2 seam for future Ollama / LLM integration).

No actual AI/LLM calls are made in v1. The contract is designed so that a
future provider can be plugged in with zero refactoring.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Type

from backend.services.video_library_engine import schemas


class GameAnalyzer(ABC):
    """Abstract base class for game video analysis providers.

    Subclasses implement :meth:`analyze` to produce a :class:`GameAnalysis`
    from a game's video reference. The analysis is organized by event segments,
    aligning with the PBP event timeline for future coach-perspective overlays.
    """

    @abstractmethod
    def analyze(self, game_id: str, season: str, video_ref: str) -> schemas.GameAnalysis:
        """Produce a game analysis result.

        Args:
            game_id: The game identifier (dim_games.game_id).
            season: NBA season string (e.g. '2025').
            video_ref: Video reference (URL or /video-library/media/{id} path).

        Returns:
            A :class:`GameAnalysis` with summary and event-organized segments.
        """
        ...


class StaticAnalyzer(GameAnalyzer):
    """Default v1 analyzer: returns a template placeholder GameAnalysis.

    This is runnable and testable without any LLM. It produces a structured
    (but static) analysis that demonstrates the contract shape for future
    P2 providers.
    """

    def analyze(self, game_id: str, season: str, video_ref: str) -> schemas.GameAnalysis:
        return schemas.GameAnalysis(
            game_id=game_id,
            season=season,
            summary=(
                f"[Static Analysis] Game {game_id} ({season}) — "
                f"automated analysis is a P2 feature. This is a placeholder."
            ),
            segments=[
                schemas.AnalysisSegment(
                    event_index=0,
                    period_clock="Q1 12:00",
                    commentary="Game start — placeholder segment (StaticAnalyzer v1).",
                ),
            ],
        )


class LLMAnalyzer(GameAnalyzer):
    """P2 reserved analyzer: raises NotImplementedError → router maps to 50100.

    Future implementation will connect to Ollama or an LLM API to produce
    real commentary. The contract is locked here so the integration requires
    zero refactoring of the service/router layers.
    """

    def analyze(self, game_id: str, season: str, video_ref: str) -> schemas.GameAnalysis:
        raise NotImplementedError(
            "LLMAnalyzer is not enabled in v1. AI re-analysis is a P2 feature."
        )


# ── Registry (same pattern as TacticGenerator) ──

REGISTRY: Dict[str, Type[GameAnalyzer]] = {
    "static": StaticAnalyzer,
    "llm": LLMAnalyzer,
}
