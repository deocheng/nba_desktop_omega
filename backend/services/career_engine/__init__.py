"""NBACore v8.2-C — Career engine (Peak / Age Curve / Similar Evolution).

Shared engine package. Mirrors the clutch_engine layout: all read-only SQL
lives in ``career_queries``, computation/post-processing in ``career_service``,
pure helpers in ``career_utils``, constants in ``career_constants``.
"""
from __future__ import annotations

from backend.services.career_engine import (
    career_constants,
    career_queries,
    career_service,
    career_utils,
)

__all__ = [
    "career_constants",
    "career_queries",
    "career_service",
    "career_utils",
]
