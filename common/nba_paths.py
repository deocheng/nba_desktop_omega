#!/usr/bin/env python3
"""nba_paths — 全项目路径解析的唯一来源（纯标准库、零依赖）。

问题背景：本项目横跨两个代码根 + 一个仓外产物目录，硬编码绝对路径
（/Users/deocheng/... 与 /Volumes/12T/...）曾散落在 60+ 个脚本中，
换机 / 迁移 / 容器化即断。

本模块提供统一的路径解析，优先级自高而低：
    1. 环境变量覆盖（NBA_REPO_ROOT / NBA_WORKSPACE_ROOT / NBA_ANALYSIS_ROOT ...）
    2. 由本文件位置反推（repo root = 本文件的上上级）
    3. 已知候选路径探测（存在即用）

用法：
    from nba_paths import REPO_ROOT, WORKSPACE_ROOT, env_file, repo_file

设计约束：
- **不递归扫描**大目录（外置盘 6TB 素材区会导致卡死 / exit 137）。
  探测只做 os.path.exists 单次 stat。
- 路径解析是纯函数式读取，模块导入不产生副作用。
"""
from __future__ import annotations

import os
from pathlib import Path

# ── 根目录候选（按优先级）──────────────────────────────────────────────────
# 主仓库（本文件位于 R/<sub>/nba_paths.py 时，R = parents[1]）
_THIS = Path(__file__).resolve()
REPO_ROOT_DEFAULT = _THIS.parent.parent

# 会话工作区（W）与仓外产物（P）的已知候选
_WORKSPACE_CANDIDATES = (
    os.path.expanduser("~/WorkBuddy/2026-07-13-10-47-43"),
    str(REPO_ROOT_DEFAULT / "workspace" / "workbuddy-scripts"),
)
_ANALYSIS_CANDIDATES = (
    str(REPO_ROOT_DEFAULT.parent / "nba_analysis"),
)


def _from_env(name: str) -> str | None:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else None


def _abs(p: str) -> Path:
    """转绝对路径但**不解析符号链接**。

    本机的会话工作区本身是软链
    （/Users/deocheng/WorkBuddy/<会话> -> /Volumes/12T/WorkBuddy/<会话>），
    若用 Path.resolve() 会把逻辑路径换成物理路径，报告输出路径将与
    用户预期不一致，也会让脚本之间的路径比较失败。故统一用 abspath。
    """
    return Path(os.path.abspath(os.path.expanduser(p)))


def _first_existing(candidates) -> Path | None:
    """返回第一个存在的候选路径；全不存在返回 None。只做单次 stat，不递归。"""
    for c in candidates:
        if c and os.path.exists(c):
            return _abs(c)
    return None


def _resolve(name: str, candidates, fallback: Path | None = None) -> Path:
    """解析一个根路径：环境变量 > 已知候选 > fallback。"""
    env = _from_env(name)
    if env:
        return _abs(env)
    found = _first_existing(candidates)
    if found is not None:
        return found
    if fallback is not None:
        return _abs(str(fallback))
    raise RuntimeError(
        f"无法定位 {name}：请设置环境变量 {name} 指向正确路径"
    )


# ── 三个逻辑来源 ──────────────────────────────────────────────────────────
#: R —— 主仓库，唯一代码根
REPO_ROOT: Path = _resolve(
    "NBA_REPO_ROOT", (str(REPO_ROOT_DEFAULT),), REPO_ROOT_DEFAULT
)
#: W —— 会话工作区（一次性脚本 / 报告产物层）
WORKSPACE_ROOT: Path = _resolve(
    "NBA_WORKSPACE_ROOT", _WORKSPACE_CANDIDATES, REPO_ROOT_DEFAULT / "workspace"
)
#: P —— 仓外报告产物目录
ANALYSIS_ROOT: Path = _resolve(
    "NBA_ANALYSIS_ROOT", _ANALYSIS_CANDIDATES, REPO_ROOT_DEFAULT.parent / "nba_analysis"
)

#: R 内逻辑入口（workspace/ 与 reports/ 的只读软链入口）
WORKSPACE_LINK: Path = REPO_ROOT / "workspace" / "workbuddy-scripts"
ANALYSIS_LINK: Path = REPO_ROOT / "reports" / "nba-analysis"

#: 数据库 .env（口令严禁硬编码，统一从此处或环境变量读取）
ENV_FILE: Path = REPO_ROOT / ".env"


def env_file() -> Path:
    """返回 .env 路径；不存在时抛 RuntimeError（调用方需处理缺失）。"""
    if ENV_FILE.exists():
        return ENV_FILE
    raise RuntimeError(f"未找到 {ENV_FILE}；请设置 NBA_REPO_ROOT 或补齐 .env")


def repo_file(*parts: str) -> Path:
    """主仓库内的路径：repo_file("backend", "core", "db.py")"""
    return REPO_ROOT.joinpath(*parts)


def workspace_file(*parts: str) -> Path:
    """会话工作区内的路径"""
    return WORKSPACE_ROOT.joinpath(*parts)


def analysis_file(*parts: str) -> Path:
    """仓外产物目录内的路径"""
    return ANALYSIS_ROOT.joinpath(*parts)


def output_file(name: str, *, root: Path | None = None) -> Path:
    """报告输出路径。默认写到工作区；传 root 则写到指定目录。"""
    base = root or WORKSPACE_ROOT
    p = base / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir(name: str) -> Path:
    """缓存目录（主仓库内，按需创建）。"""
    d = REPO_ROOT / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def describe() -> str:
    """人类可读的路径概览（用于 --check / 诊断输出）。"""
    lines = [
        "路径解析结果：",
        f"  R 主仓库      : {REPO_ROOT}  [{'存在' if REPO_ROOT.exists() else '缺失'}]",
        f"  W 会话工作区  : {WORKSPACE_ROOT}  [{'存在' if WORKSPACE_ROOT.exists() else '缺失'}]",
        f"  P 仓外产物    : {ANALYSIS_ROOT}  [{'存在' if ANALYSIS_ROOT.exists() else '缺失'}]",
        f"  .env          : {ENV_FILE}  [{'存在' if ENV_FILE.exists() else '缺失'}]",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
