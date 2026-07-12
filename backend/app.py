"""NBACore v8 — FastAPI Application Entry Point.

Phase 10 scope (v7 feature migration):
    - lifespan: init/close DB pool
    - request middleware: bind request_id, log latency
    - /health: DB ping + runtime guard results
    - /: minimal root info (no business logic)
    - Phase 3 routers: /players, /metrics, /vs, /batch
    - Phase 5 router: /context (similar, evolution, trend)
    - Phase 6 router: /export (rankings, vs, player)
    - Phase 7 router: /monitor (stats)
    - Phase 10 routers: /teams, /games, /charts, /system, /crawler, /leaderboard
    - /app: static frontend files (7 pages: VS, Rankings, Teams, Games, Context, Crawler, System)
    - /assets/logos: NBA team logo assets

No routes here may contain SQL or computation. All business endpoints are
delegated to Layer 3 routers which in turn call Layer 2 metric_engine.
Frontend is pure render (Layer 4) — served via StaticFiles.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routers import (
    analytics_builder, batch, career, cba_aux, charts, clutch, clutch_replay,
    context, crawler, data_import, draft, export, games, intelligence, leaderboard,
    metrics, monitor, players, system, teams, trade, tactics, video_library, vs,
    workspace,
)
from backend.core import config
from backend.core.db import close_pool, init_pool, ping
from backend.core.logging import new_request_id, setup_logging
from backend.core.runtime_guard import run_startup_checks

setup_logging(config.LOG_LEVEL)
logger = logging.getLogger("nbacore.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: pool init on startup, close on shutdown."""
    logger.info("Lifespan START | %s v%s", config.APP_NAME, config.APP_VERSION)
    try:
        init_pool()
    except Exception as exc:
        logger.error("DB pool init failed (app will start in degraded mode) | %s", exc)
    yield
    close_pool()
    logger.info("Lifespan END")


def create_app() -> FastAPI:
    """Application factory (v8 §3 — pure orchestration, no logic)."""
    app = FastAPI(
        title=config.APP_NAME,
        version=config.APP_VERSION,
        lifespan=lifespan,
    )
    # CORS: restrict to localhost in production, allow all in debug mode
    _allowed_origins = (
        ["*"]
        if config.DEBUG
        else ["http://127.0.0.1:5577", "http://localhost:5577"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def trace_request(request: Request, call_next):
        rid = new_request_id()
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %d | %.1fms | rid=%s",
            request.method, request.url.path,
            response.status_code, elapsed_ms, rid,
        )
        return response

    @app.get("/")
    def root():
        return {
            "name": config.APP_NAME,
            "version": config.APP_VERSION,
            "phase": "10-v7-feature-migration",
            "docs": "/docs",
            "health": "/health",
            "app": "/app/",
        }

    @app.get("/health")
    def health():
        """v8 Phase 0 validation: DB ping + runtime guard."""
        db_ok = ping()
        guard = run_startup_checks()
        status = "ok" if db_ok and all(g.get("ok") for g in guard.values()) else "degraded"
        return {
            "status": status,
            "version": config.APP_VERSION,
            "database_connected": db_ok,
            "runtime_guard": guard,
        }

    # Phase 3: register Layer 3 routers (pure orchestration, no logic)
    app.include_router(players.router)
    app.include_router(metrics.router)
    app.include_router(vs.router)
    app.include_router(batch.router)
    app.include_router(context.router)
    app.include_router(export.router)
    app.include_router(monitor.router)
    # Phase 10: v7 feature migration
    app.include_router(teams.router)
    app.include_router(games.router)
    app.include_router(charts.router)
    app.include_router(system.router)
    app.include_router(crawler.router)
    app.include_router(leaderboard.router)
    app.include_router(intelligence.router)
    app.include_router(workspace.router)
    app.include_router(data_import.router)
    app.include_router(draft.router)
    app.include_router(clutch.router)
    app.include_router(clutch_replay.router)
    app.include_router(career.router)
    app.include_router(cba_aux.router)
    app.include_router(trade.router)
    app.include_router(tactics.router)
    app.include_router(video_library.router)
    app.include_router(analytics_builder.router)

    # Phase 4: mount frontend static files (Layer 4 — pure render)
    from pathlib import Path
    import sys

    class _NoCacheStaticFiles(StaticFiles):
        """StaticFiles that sends ``Cache-Control: no-cache`` so the browser
        always revalidates against the server. Dev-friendly: front-end edits
        show on a normal refresh (no hard reload needed), while unchanged files
        still 304 quickly via their ETag / Last-Modified."""

        async def get_response(self, path: str, scope) -> "Response":
            response = await super().get_response(path, scope)
            response.headers.setdefault("Cache-Control", "no-cache")
            return response

    if getattr(sys, "frozen", False):
        _base = Path(sys._MEIPASS)
    else:
        _base = Path(__file__).resolve().parent.parent

    _frontend_dir = _base / "frontend"
    _logo_dir = _base / "NBAlogo"
    if _frontend_dir.is_dir():
        app.mount("/app", _NoCacheStaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
    if _logo_dir.is_dir():
        app.mount("/assets/logos", _NoCacheStaticFiles(directory=str(_logo_dir)), name="logos")
        app.mount("/app/assets/logos", _NoCacheStaticFiles(directory=str(_logo_dir)), name="logos-app")

    return app


app = create_app()


def main() -> None:
    """Run with uvicorn when invoked as `python -m backend.app`."""
    import uvicorn
    uvicorn.run(
        "backend.app:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=config.DEBUG,
        log_level=config.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
