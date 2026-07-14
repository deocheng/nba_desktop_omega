"""NBACore Studio v8 — Standalone EXE Entry Point.

Launches uvicorn server, opens browser, runs until Ctrl+C.
Used by PyInstaller to build a single-file executable.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from backend.core import config


def _open_browser_after_delay(delay: float = 1.5) -> None:
    """Open browser after server is likely ready."""
    time.sleep(delay)
    url = f"http://127.0.0.1:{config.SERVER_PORT}/app/"
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> None:
    """Entry point for standalone executable."""
    if getattr(sys, "frozen", False):
        _base = Path(sys._MEIPASS)
    else:
        _base = Path(__file__).resolve().parent

    _logo_dir = _base / "NBAlogo"
    _frontend_dir = _base / "frontend"

    print("=" * 60)
    print(f"  NBACore Studio v{config.APP_VERSION}")
    print("=" * 60)
    print(f"  Server:  http://127.0.0.1:{config.SERVER_PORT}")
    print(f"  App:     http://127.0.0.1:{config.SERVER_PORT}/app/")
    print(f"  API Doc: http://127.0.0.1:{config.SERVER_PORT}/docs")
    print("=" * 60)
    print(f"  Resources: {_base}")
    print(f"  Frontend:  {_frontend_dir} ({'OK' if _frontend_dir.is_dir() else 'MISSING'})")
    print(f"  Logos:     {_logo_dir} ({'OK' if _logo_dir.is_dir() else 'MISSING'})")
    print("=" * 60)
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    print()

    # Open browser in background thread
    threading.Thread(target=_open_browser_after_delay, daemon=True).start()

    # Run uvicorn
    try:
        uvicorn.run(
            "backend.app:create_app",
            factory=True,
            host="127.0.0.1",
            port=config.SERVER_PORT,
            log_level=config.LOG_LEVEL.lower(),
            access_log=config.DEBUG,
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
        sys.exit(0)


if __name__ == "__main__":
    main()
