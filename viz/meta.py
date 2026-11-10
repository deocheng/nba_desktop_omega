#!/usr/bin/env python3
"""viz.meta — 报告元信息（可追溯性）生成器。

项目原则「先证据再决策」要求：任何一份报告都必须能回答
「这份图是哪份数据、哪个口径、哪个版本生成的」。

本模块提供：
- git_sha / git_branch / git_dirty : 代码版本溯源
- generation_timestamp              : 生成时间（ISO 8601 带时区）
- build_meta                        : 组装标准 5 项元信息 + 额外项
- lineage                           : 数据血缘文本块

标准 5 项（与 viz.base._META_KEYS 对齐，缺一不可）：
    生成时间 / 数据源 / 口径 / 快照版本 / 行数
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

# 与 viz.base 的强制元信息键保持一致
META_KEYS = ("生成时间", "数据源", "口径", "快照版本", "行数")


def _run(cmd: list[str], cwd: Optional[str] = None) -> Optional[str]:
    """执行命令并返回 stdout.strip()；失败返回 None。"""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=5)
        if p.returncode == 0:
            return p.stdout.strip()
    except Exception:  # noqa: BLE001 — git 不可用时静默降级
        return None
    return None


def git_sha(repo_path: Optional[str] = None, short: bool = True) -> str:
    """当前 git commit SHA；不在仓库内或 git 不可用时返回 "unknown"。"""
    cmd = ["git", "rev-parse", "--short=8" if short else "HEAD"]
    return _run(cmd, cwd=repo_path) or "unknown"


def git_branch(repo_path: Optional[str] = None) -> str:
    """当前 git 分支名；不可用时返回 "unknown"。"""
    return _run(["git", "branch", "--show-current"], cwd=repo_path) or "unknown"


def git_dirty(repo_path: Optional[str] = None) -> bool:
    """工作区是否有未提交改动。"""
    out = _run(["git", "status", "--porcelain"], cwd=repo_path)
    return bool(out)


def generation_timestamp(iso: bool = True) -> str:
    """生成时间。iso=True 输出带本地时区偏移的 ISO 8601。"""
    now = datetime.now().astimezone()
    if iso:
        return now.isoformat(timespec="seconds")
    return now.strftime("%Y-%m-%d %H:%M:%S")


def python_version() -> str:
    """当前 Python 版本字符串。"""
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def build_meta(
    *,
    data_source: str = "",
    scope: str = "",
    snapshot: str = "",
    row_counts: Optional[dict[str, int]] = None,
    extra: Optional[dict[str, Any]] = None,
    repo_path: Optional[str] = None,
    include_git: bool = True,
) -> dict[str, str]:
    """组装标准元信息字典。

    参数：
        data_source : 数据来源，如 "PostgreSQL nba@5433 / dim_games + player_per_game"
        scope       : 口径与覆盖范围，如 "2024-25 Regular Season, 30 teams, 1230 games"
        snapshot    : 快照版本标识
        row_counts  : {表名: 行数}，渲染为「行数 (表名)」条目
        extra       : 额外键值
        repo_path   : git 仓库路径；默认取当前工作目录
        include_git : 是否注入 Git 提交 / 分支 / 工作区状态
    """
    meta: dict[str, str] = {
        "生成时间": generation_timestamp(),
        "数据源": data_source or "—",
        "口径": scope or "—",
        "快照版本": snapshot or "—",
        "行数": "—",
    }
    if include_git:
        meta["Git 提交"] = git_sha(repo_path)
        meta["Git 分支"] = git_branch(repo_path)
        meta["工作区"] = "有未提交改动" if git_dirty(repo_path) else "干净"
    meta["Python"] = python_version()

    for table, count in (row_counts or {}).items():
        meta[f"行数 ({table})"] = f"{count:,}"

    for k, v in (extra or {}).items():
        meta[str(k)] = str(v)

    return meta


def lineage(
    sources: dict[str, str],
    transformations: Optional[list[str]] = None,
) -> str:
    """数据血缘文本块（等宽字体，零依赖）。"""
    lines = [
        '<div class="viz-lineage" style="font-family:var(--font-mono); '
        'font-size:var(--font-size-xs); color:var(--text-muted); line-height:1.8;">',
        '  <div style="font-weight:var(--font-weight-semibold); color:var(--text); '
        'margin-bottom:var(--space-xs);">数据血缘</div>',
    ]
    for table, source in sources.items():
        lines.append(f"  <div>└─ {_esc(table)} ← {_esc(source)}</div>")
    if transformations:
        lines.append(
            '  <div style="margin-top:var(--space-sm); font-weight:var(--font-weight-semibold); '
            'color:var(--text);">转换步骤</div>'
        )
        for i, step in enumerate(transformations, 1):
            lines.append(f"  <div>&nbsp;&nbsp;{i}. {_esc(step)}</div>")
    lines.append("</div>")
    return "\n".join(lines)


def _esc(v: Any) -> str:
    import html

    return html.escape(str(v), quote=True)


__all__ = [
    "META_KEYS", "git_sha", "git_branch", "git_dirty",
    "generation_timestamp", "python_version", "build_meta", "lineage",
]
