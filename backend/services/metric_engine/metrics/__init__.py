"""NBACore v8 §2 Layer 2 — Built-in metric definitions.

Importing this package registers all built-in metrics with the singleton
MetricRegistry. Metric Engine users only need:
    import backend.services.metric_engine  # triggers registration
"""
from backend.services.metric_engine.metrics import advanced, basic, composite  # noqa: F401

__all__ = ["basic", "advanced", "composite"]
