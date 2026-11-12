"""外部资产探测与降级矩阵。

打包版（frozen）不自带 PostgreSQL / 43G 战术产物 / 6TB 录像素材 / 模型权重。
本模块只做**轻量存在性或 TCP 探测**，不建连接池、不加载模型、不遍历大目录；
结果供前端置灰对应步骤，而不是让按钮点了报 500。

两个 frozen 陷阱见 docs/unified-desktop-app-architecture.md §4：
  - REPO_ROOT 会漂移到解包目录，须由 NBA_REPO_ROOT / NBA_DATA_ROOT 显式指定；
  - sys.executable 是打包程序本身，解释器须由 STUDIO_PYTHON 显式指定。
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

from backend.core import config
from common.nba_paths import DATA_ROOT, REPO_ROOT, data_file, tactics_code_file, tactics_data_file


def interpreter() -> tuple[str | None, str]:
    """返回 (可执行解释器路径 or None, 来源说明)。frozen 下绝不退回 sys.executable。"""
    configured = os.environ.get("STUDIO_PYTHON", "").strip()
    if configured:
        return configured, "STUDIO_PYTHON"
    if getattr(sys, "frozen", False):
        return None, "frozen 下 sys.executable 是打包程序本身，请设置 STUDIO_PYTHON"
    return sys.executable, "sys.executable"


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _item(ok: bool, detail: str) -> dict:
    return {"ok": bool(ok), "detail": detail}


def detect() -> dict:
    """探测全部 capability；返回结构稳定，缺项一律 ok=false + 原因。"""
    py, py_src = interpreter()
    py_ok = bool(py) and Path(py).is_file() and os.access(py, os.X_OK)
    code_root = tactics_code_file()
    tactic_data = tactics_data_file()
    video_root = data_file("比赛录像")
    db_ok = _port_open(config.DB_HOST, config.DB_PORT)

    items = {
        "python": _item(
            py_ok,
            f"{py or '未配置'}（来源 {py_src}；{'' if py_ok else '不可执行'}）",
        ),
        "tactics_code": _item(
            code_root.is_dir(),
            f"{code_root}{' 存在' if code_root.is_dir() else ' 不存在（检查 NBA_REPO_ROOT）'}",
        ),
        "tactics_data": _item(
            tactic_data.is_dir(),
            f"{tactic_data}{' 存在' if tactic_data.is_dir() else ' 不存在（检查 NBA_DATA_ROOT）'}",
        ),
        "video_root": _item(
            video_root.is_dir(),
            f"{video_root}{' 存在' if video_root.is_dir() else ' 不存在'}",
        ),
        "database": _item(db_ok, f"{config.DB_HOST}:{config.DB_PORT} TCP {'可达' if db_ok else '不可达'}"),
    }
    return {
        "frozen": bool(getattr(sys, "frozen", False)),
        "repo_root": str(REPO_ROOT),
        "data_root": str(DATA_ROOT),
        "capabilities": items,
        "ready_for_run": items["python"]["ok"] and items["tactics_code"]["ok"],
    }
