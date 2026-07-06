"""NBACore v8 §2 Layer 3 — /crawler router (pure orchestration).

Crawler control — start, stop, status, SSE log streaming.
Python interpreter path is read exclusively from NBA_PYTHON env var.
No hardcoded paths — fail fast with clear 503 if not configured.

Robustness hardening (2026-07-07):
    - threading.Lock protects all global state (race-condition safe)
    - Cross-platform process termination (proc.terminate + proc.kill)
    - SSE async generator with client-disconnect detection
    - Structured error handling in background thread
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.core import config

logger = logging.getLogger("nbacore.routers.crawler")

router = APIRouter(prefix="/crawler", tags=["crawler"])

# ── Global state (all access guarded by _state_lock) ──
_state_lock = threading.Lock()
_log_queue: queue.Queue = queue.Queue(maxsize=1000)
_crawl_running = False
_crawl_thread: threading.Thread | None = None
_crawl_process: subprocess.Popen | None = None
_last_result: dict | None = None


# ── Request / Response models ──
class CrawlStartRequest(BaseModel):
    mode: str = "check"
    params: dict = {}


# ── Helpers ──
def _get_python_exe() -> str:
    """Get Python interpreter path from NBA_PYTHON env var only.

    Raises HTTPException 503 if not set or path does not exist.
    NO hardcoded fallback paths — configuration must be explicit.
    """
    python_exe = os.environ.get("NBA_PYTHON", "").strip()
    if not python_exe:
        raise HTTPException(
            status_code=503,
            detail="Python interpreter not configured. Set NBA_PYTHON environment variable.",
        )
    if not os.path.exists(python_exe):
        raise HTTPException(
            status_code=503,
            detail=(
                f"Python interpreter not found at '{python_exe}'. "
                "Set NBA_PYTHON environment variable to a valid python.exe path."
            ),
        )
    return python_exe


def _get_crawler_script() -> str:
    """Get crawler script path from CRAWLER_SCRIPT env var or default.

    Raises HTTPException 400 if the script does not exist.
    """
    script_path = os.environ.get("CRAWLER_SCRIPT", "").strip()
    if not script_path:
        script_path = str(config.BASE_DIR / "crawler" / "main.py")
    if not os.path.exists(script_path):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Crawler script not found at '{script_path}'. "
                "Set CRAWLER_SCRIPT environment variable to a valid script path."
            ),
        )
    return script_path


def _build_command(mode: str, params: dict) -> list[str]:
    """Build the command line for the crawler script."""
    python_exe = _get_python_exe()
    script = _get_crawler_script()

    if mode == "check":
        cmd = [python_exe, script, "--check"]
    elif mode == "daily":
        cmd = [python_exe, script]
        if params.get("date"):
            cmd += ["--date", str(params["date"])]
    elif mode == "backfill":
        cmd = [python_exe, script, "--backfill", str(params.get("days", 7))]
    elif mode == "single":
        table = params.get("table", "team_game_splits")
        cmd = [python_exe, script, "--table", table]
        if params.get("season"):
            cmd += ["--season", str(params["season"])]
        if params.get("teams"):
            cmd += ["--teams", str(params["teams"])]
    elif mode == "full_season":
        cmd = [python_exe, script, "--full-season", str(params.get("season", config.current_season()))]
    elif mode == "list_tables":
        cmd = [python_exe, script, "--list-tables"]
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown mode: {mode}. Valid modes: check, daily, backfill, single, full_season, list_tables",
        )
    return cmd


def _terminate_process(proc: subprocess.Popen | None, timeout: float = 5.0) -> bool:
    """Cross-platform process termination.

    Tries graceful terminate() first, then forceful kill() if needed.
    Returns True if the process was terminated successfully.
    """
    if proc is None:
        return True
    try:
        proc.terminate()  # SIGTERM on Unix, TerminateProcess on Windows
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()  # SIGKILL on Unix, forceful on Windows
            proc.wait(timeout=timeout)
        return True
    except (ProcessLookupError, OSError):
        # Process already exited
        return True
    except Exception as exc:
        logger.error("Failed to terminate process: %s", exc)
        return False


def _run_crawl_task(mode: str, params: dict) -> None:
    """Background thread that runs the crawler subprocess."""
    global _crawl_running, _last_result, _crawl_process
    start_time = time.time()
    logger.info("=== Crawl started: mode=%s, params=%s ===", mode, params)

    timer: threading.Timer | None = None
    try:
        cmd = _build_command(mode, params)
        logger.info("Command: %s", " ".join(cmd))

        crawl_env = {**os.environ, "HTTP_PROXY": "", "HTTPS_PROXY": ""}
        if params.get("interval"):
            crawl_env["CRAWL_INTERVAL"] = str(params["interval"])
        if params.get("duration"):
            crawl_env["CRAWL_DURATION"] = str(params["duration"])

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=crawl_env,
        )
        with _state_lock:
            _crawl_process = proc

        duration_limit = params.get("duration")
        if duration_limit:
            def _kill_after_duration() -> None:
                with _state_lock:
                    target_proc = _crawl_process
                if target_proc is not None and target_proc.poll() is None:
                    logger.info("Duration limit (%ss) reached, stopping...", duration_limit)
                    _terminate_process(target_proc)

            timer = threading.Timer(float(duration_limit), _kill_after_duration)
            timer.start()

        for line in proc.stdout:
            line = line.rstrip()
            if line:
                level = "INFO"
                if "[ERROR]" in line or "Error" in line:
                    level = "ERROR"
                elif "[WARNING]" in line or "Warning" in line:
                    level = "WARNING"
                logger.info(line)
                try:
                    _log_queue.put_nowait({"time": time.time(), "level": level, "msg": line})
                except queue.Full:
                    pass

        proc.wait()
        rc = proc.returncode
        duration = time.time() - start_time

        if rc == 0:
            _last_result = {"status": "success", "duration": round(duration, 1)}
            logger.info("=== Crawl completed in %.1fs ===", duration)
        else:
            _last_result = {"status": "error", "error": f"Exit code {rc}", "duration": round(duration, 1)}
            logger.error("=== Crawl failed (exit %d) in %.1fs ===", rc, duration)
    except HTTPException:
        raise
    except Exception as exc:
        duration = time.time() - start_time
        _last_result = {"status": "error", "error": str(exc)[:200], "duration": round(duration, 1)}
        logger.error("=== Crawl failed: %s ===", exc)
    finally:
        if timer:
            timer.cancel()
        with _state_lock:
            _crawl_process = None
            _crawl_running = False


# ── Endpoints ──
@router.post("/start")
def start_crawl(req: CrawlStartRequest) -> dict:
    """Start a crawler job in a background thread."""
    global _crawl_running, _crawl_thread, _last_result

    with _state_lock:
        if _crawl_running:
            raise HTTPException(status_code=409, detail="A crawl is already running")

        _get_python_exe()
        _get_crawler_script()

        _crawl_running = True
        _last_result = None
        _crawl_thread = threading.Thread(
            target=_run_crawl_task,
            args=(req.mode, req.params),
            daemon=True,
        )
        _crawl_thread.start()
    return {"status": "started", "mode": req.mode}


@router.get("/status")
def crawl_status() -> dict:
    """Get current crawler status and last result."""
    with _state_lock:
        return {"running": _crawl_running, "last_result": _last_result}


@router.post("/stop")
def stop_crawl() -> dict:
    """Stop the currently running crawler process."""
    global _crawl_running, _last_result

    with _state_lock:
        if not _crawl_running or _crawl_process is None:
            raise HTTPException(status_code=400, detail="No crawl is running")
        proc = _crawl_process

    pid = proc.pid
    logger.info("Stopping crawl process (PID=%d)...", pid)
    success = _terminate_process(proc)

    if success:
        with _state_lock:
            _crawl_running = False
            _last_result = {"status": "stopped", "duration": 0}
        logger.info("Crawl stopped by user.")
        return {"status": "stopped"}
    else:
        raise HTTPException(status_code=500, detail="Failed to terminate crawl process")


@router.get("/logs/stream")
async def logs_stream(request: Request) -> StreamingResponse:
    """SSE stream for real-time crawler logs.

    Uses async generator with client-disconnect detection to avoid
    infinite loops when the browser tab is closed.
    """
    async def generate():
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                logger.debug("SSE client disconnected, stopping stream.")
                break
            try:
                msg = _log_queue.get_nowait()
                yield f"data: {json.dumps(msg)}\n\n"
            except queue.Empty:
                # Send keepalive and wait
                yield ": keepalive\n\n"
                await asyncio.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
