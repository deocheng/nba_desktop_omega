#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
raw_archiver.py —— 原始响应落盘封装（原子写 + 去重 + 哈希）
============================================================
贯穿 G2/G3 的非功能护栏（P0-3）：BR HTML 与 ESPN JSON 原始响应必须落盘，
保证可离线重解析、可审计，且不重复抓取/重复写。

契约（由本模块强制）：
  - 写入临时文件 *.tmp → fsync → 原子 rename 到目标名；
  - 若目标已存在且字节数 > 0 → 跳过（除非显式 rearchive=True）；
  - 可选：写 .sha256 伴生文件供 verify_archive.py 校验。

路径布局（照 OQ-a，引用 common.bridge_constants 模板）：
  raw_archive/br/{season}/{gid}.html
  raw_archive/espn/{date}/{event}.json

幂等：重跑安全；同一内容重复落盘不产生副作用。
"""
from __future__ import annotations

import hashlib
import json
import os

from common.bridge_constants import (
    ARCHIVE_BASE,
    BR_ARCHIVE_TMPL,
    ESPN_ARCHIVE_TMPL,
    season_start_year,
)

# 归档根基准(可被测试重定向): 默认 = ARCHIVE_BASE(= ARCHIVE_ROOT 的父目录
# /Volumes/12T/NBA), 与模板 "raw_archive/..." 拼接即得 <ARCHIVE_ROOT>/br|espn/...。
# 测试里通过 raw_archiver.PROJECT_ROOT = tmp_dir 隔离, 避免污染真实归档。
PROJECT_ROOT = ARCHIVE_BASE


# ---------------------------------------------------------------------------
# 基础原子写
# ---------------------------------------------------------------------------
def atomic_write(path: str, data: "Union[str, bytes]",
                 *, write_sha256: bool = False,
                 rearchive: bool = False, fsync: bool = True) -> bool:
    """原子写文件。

    - 若目标已存在且字节数 > 0 且 rearchive=False → 跳过，返回 False。
    - 否则写 path + '.tmp' → fsync → rename 到 path。
    - 可选写 path + '.sha256'（hexdigest）。
    返回 True 表示实际写入；False 表示跳过（目标已存在且非空）。
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    # 去重：目标存在且非空则跳过（除非 rearchive）
    if not rearchive and os.path.exists(path) and os.path.getsize(path) > 0:
        return False

    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
        if fsync:
            fh.flush()
            os.fsync(fh.fileno())
    os.replace(tmp, path)  # 原子 rename（覆盖目标）

    if write_sha256:
        _write_sha256(path, data)
    return True


def _write_sha256(path: str, data: bytes) -> None:
    """写 .sha256 伴生文件（hexdigest）。"""
    digest = hashlib.sha256(data).hexdigest()
    with open(path + ".sha256", "w", encoding="utf-8") as fh:
        fh.write(f"{digest}  {os.path.basename(path)}\n")


def verify_sha256(path: str) -> bool:
    """校验 path 的 .sha256 伴生文件是否存在且匹配。无伴生文件返回 False。"""
    sha_path = path + ".sha256"
    if not os.path.exists(sha_path) or not os.path.exists(path):
        return False
    with open(path, "rb") as fh:
        actual = hashlib.sha256(fh.read()).hexdigest()
    with open(sha_path, "r", encoding="utf-8") as fh:
        expected = fh.read().split()[0]
    return actual == expected


# ---------------------------------------------------------------------------
# BR / ESPN 专用封装（引用归档模板）
# ---------------------------------------------------------------------------
def save_br_html(season: "Union[int, str]", gid: str, html: "Union[str, bytes]",
                 *, write_sha256: bool = False, rearchive: bool = False) -> bool:
    """落盘 BR PBP 原始 HTML → raw_archive/br/{season}/{gid}.html。"""
    path = os.path.join(PROJECT_ROOT, BR_ARCHIVE_TMPL.format(season=season, gid=gid))
    return atomic_write(path, html, write_sha256=write_sha256, rearchive=rearchive)


def save_espn_json(date_str: str, event: str,
                   payload: "Union[str, bytes, dict, list]",
                   *, write_sha256: bool = False, rearchive: bool = False) -> bool:
    """落盘 ESPN summary 原始 JSON → raw_archive/espn/{date}/{event}.json。

    payload 可为 str/bytes（直接写）或 dict/list（json.dumps 后写）。
    """
    if isinstance(payload, (dict, list)):
        data: "Union[str, bytes]" = json.dumps(payload, ensure_ascii=False)
    else:
        data = payload
    path = os.path.join(PROJECT_ROOT, ESPN_ARCHIVE_TMPL.format(date=date_str, event=event))
    return atomic_write(path, data, write_sha256=write_sha256, rearchive=rearchive)


def br_html_path(season: "Union[int, str]", gid: str) -> str:
    return os.path.join(PROJECT_ROOT, BR_ARCHIVE_TMPL.format(season=season, gid=gid))


def espn_json_path(date_str: str, event: str) -> str:
    return os.path.join(PROJECT_ROOT, ESPN_ARCHIVE_TMPL.format(date=date_str, event=event))


def season_for(gdate) -> int:
    """由比赛日期求赛季起始年（透传 common.bridge_constants.season_start_year）。"""
    return season_start_year(gdate)


if __name__ == "__main__":
    # 简单自测：写入+跳过+哈希
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.txt")
    assert atomic_write(p, b"hello", write_sha256=True) is True
    assert atomic_write(p, b"world") is False          # 已存在且非空 → 跳过
    assert open(p, "rb").read() == b"hello"            # 内容未被覆盖
    assert verify_sha256(p) is True
    print("raw_archiver self-test OK")
