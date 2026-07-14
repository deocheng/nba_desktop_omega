"""NBACore v8 §5.1 / §5.2 — Structured Logging with query_id / request_id tracing.

All SQL queries and requests are traceable via contextvars-injected IDs.
Zero external dependencies (stdlib logging only).
"""
from __future__ import annotations

import contextvars
import logging
import uuid
from datetime import datetime, timezone

# ── Context Vars (propagate through FastAPI threadpool automatically) ──
query_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "query_id", default="-"
)
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class _StructuredFilter(logging.Filter):
    """Inject trace IDs + ISO timestamp into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.query_id = query_id_var.get()
        record.request_id = request_id_var.get()
        record.ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return True


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with structured format. Idempotent."""
    root = logging.getLogger()
    if root.handlers and getattr(root, "_nbacore_configured", False):
        return
    fmt = (
        "%(ts)s [%(levelname)s] "
        "[req=%(request_id)s q=%(query_id)s] "
        "%(name)s | %(message)s"
    )
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(_StructuredFilter())
    root.handlers = [handler]
    root.setLevel(level.upper())
    root._nbacore_configured = True  # type: ignore[attr-defined]


def new_query_id() -> str:
    """Generate + bind a fresh query_id to the current context."""
    qid = uuid.uuid4().hex[:12]
    query_id_var.set(qid)
    return qid


def new_request_id() -> str:
    """Generate + bind a fresh request_id to the current context."""
    rid = uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    return rid


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
