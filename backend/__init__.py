"""NBACore Studio v8 — Backend Package.

Four-Layer Architecture (strictly enforced per v8 contract §2):
    Layer 1  backend.data_layer        — PostgreSQL batch SELECT (immutable)
    Layer 2  backend.services.metric_engine  — SOLE compute layer
    Layer 3  backend.api               — pure orchestration (no SQL/compute/logic)
    Layer 4  frontend/                 — pure render (separate package)

Cross-layer access is blocked by backend.core.runtime_guard at startup.
"""
__version__ = "8.0.0"
