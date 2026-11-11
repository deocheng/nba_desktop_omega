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


def _startup_probe() -> None:
    """启动横幅里的外部依赖自检（只打印，不改任何 router 行为）。

    🔴 用 ``is_port_open()`` 做轻量 TCP 探测，**不做**真实连接校验：
    后者会创建连接池，凭据缺失时抛异常并拖慢启动；真实凭据校验由 lifespan
    的 ``/health`` 承担。这里解决的是「双击后只看到 degraded、却不知道为什么」
    的可诊断性问题（2026-11-11 无凭据冒烟实测）。
    """
    from backend.core import db as db_mod

    port_ok = db_mod.is_port_open()
    has_password = bool(config.DB_PASSWORD)
    print(f"  Mode:      {'frozen (bundled)' if getattr(sys, 'frozen', False) else 'source'}")
    print(f"  DB port:   {config.DB_HOST}:{config.DB_PORT} "
          f"({'reachable' if port_ok else 'UNREACHABLE'})")
    print(f"  DB secret: {'configured' if has_password else 'NOT SET'}")
    if not port_ok:
        print("  [WARN] 数据库端口不可达 —— 数据类功能不可用，/health 会显示 degraded")
    elif not has_password:
        print("  [WARN] 端口可达但未提供口令 —— 请设 DB_PASSWORD，或在 exe 同目录放 .env")
    else:
        print("  [OK]   数据库前置条件齐备，连接结果以 /health 为准")


def main() -> None:
    """Entry point for standalone executable."""
    # 🔴 PyInstaller one-file 把 stdout 重定向到文件时是**块缓冲**：启动横幅会
    #    一直憋在缓冲区，日志里只剩走 stderr 的 uvicorn / app 日志（实测 2026-11-11）。
    #    强制行缓冲，保证自检信息在双击、重定向、CI 日志里都实时可见。
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError, ValueError):
        pass
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
    print("-" * 60)
    _startup_probe()
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
