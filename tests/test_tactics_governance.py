#!/usr/bin/env python3
"""tactics/ 代码治理回归测试 —— 防止「迁入即破损 / 路径再次分叉」。

事故背景（2026-11-11）
----------------------
早期用**行级正则**批量改写 tactics/ 的绝对路径，把 import 注进 docstring、
重复注入、替换中文全角标点、并留下未闭合三引号 —— 458 个 .py 里 443 个
无法解析（而迁移前备份是 458/458 可解析）。修复后必须把这些不变量变成
**可执行断言**，否则下一次批量改写还会把代码改坏且无人发现。

🔴 探测禁令
----------
全程只用 ast / 文本读取，**绝不 import tactics/ 下的任何模块**：17% 的脚本
没有 ``__main__`` 守卫，import 即执行，会重写数据盘上的语料 / 轨迹产物
（2026-11-11 实测曾误重写 42 个数据产物）。

🔴 路径字面量的自指问题
----------------------
本文件本身也在门禁 11a 的 ``git ls-files "*.py"`` 受检范围内，
所以禁止的字面量用**拼接**构造，源码里不留连续绝对路径。

运行：pytest tests/test_tactics_governance.py -v
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parent.parent
TACTICS = PROJ / "tactics"
BACKUP = PROJ / ".trash" / "tactics_pre_migration_20261111"
GOVERNOR = PROJ / "tools" / "fix_tactics_paths.py"

# 拼接构造：避免本测试文件自己触发门禁 11a
FORBIDDEN = ("/Volumes" + "/12T", "/Users" + "/deocheng")
BOOT_MARK = "nba-paths bootstrap"


def _python_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.py")
        if not any(x in {"__pycache__", ".venv", "node_modules"} for x in p.parts)
    )


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_tactics_python_files_all_parse() -> None:
    """458 个 .py 必须全部可 ast.parse —— 这是事故里最直接被破坏的不变量。"""
    files = _python_files(TACTICS)
    assert files, "tactics/ 下没有 .py 文件，迁移可能未完成"
    broken = []
    for p in files:
        try:
            ast.parse(_text(p))
        except SyntaxError as exc:
            broken.append(f"{p.relative_to(PROJ)}: {exc.msg}")
    assert not broken, f"{len(broken)} 个文件语法损坏: {broken[:5]}"


def test_no_hardcoded_absolute_paths() -> None:
    """与门禁 11a 同口径：.py 全文（含 docstring/注释）不得残留绝对路径字面量。"""
    bad = []
    for p in _python_files(TACTICS):
        text = _text(p)
        if any(x in text for x in FORBIDDEN):
            bad.append(str(p.relative_to(PROJ)))
    assert not bad, f"{len(bad)} 个文件残留硬编码路径: {bad[:5]}"


def test_governor_is_idempotent() -> None:
    """治理器 --check 必须 rc=0；非 0 说明又出现了未治理的路径或改写失败。"""
    if not GOVERNOR.exists():
        pytest.skip("治理器不存在")
    r = subprocess.run([sys.executable, str(GOVERNOR), "--check"],
                       cwd=PROJ, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, (
        f"治理器 --check 返回 {r.returncode}；"
        f"stdout={r.stdout[-400:]} stderr={r.stderr[-300:]}"
    )


def test_bootstrap_single_and_ordered() -> None:
    """bootstrap 每文件最多一份，且 sys.path.insert 必须先于 common.nba_paths 的 import。

    顺序颠倒 = 从任意 cwd / 软链运行时 ``common`` 找不到，脚本静默失效。
    """
    wrong_order, duplicated = [], []
    for p in _python_files(TACTICS):
        lines = _text(p).splitlines()
        marks = [i for i, ln in enumerate(lines) if BOOT_MARK in ln]
        if len(marks) > 1:
            duplicated.append(str(p.relative_to(PROJ)))
        if not marks:
            continue
        ins = next((i for i, ln in enumerate(lines) if "_nba_sys.path.insert" in ln), -1)
        imp = next((i for i, ln in enumerate(lines)
                    if ln.startswith("from common.nba_paths import")), -1)
        if ins >= 0 and imp >= 0 and ins > imp:
            wrong_order.append(str(p.relative_to(PROJ)))
    assert not duplicated, f"重复注入 bootstrap: {duplicated[:5]}"
    assert not wrong_order, f"bootstrap 顺序被打乱: {wrong_order[:5]}"


def test_path_helper_import_is_not_abused() -> None:
    """``Path`` 属标准库，不能从 common.nba_paths 导入（治理器早期版本的瑕疵）。"""
    bad = []
    for p in _python_files(TACTICS):
        for ln in _text(p).splitlines():
            if ln.startswith("from common.nba_paths import ") and "Path" in ln:
                bad.append(str(p.relative_to(PROJ)))
                break
    assert not bad, f"错误导入 Path: {bad[:5]}"


def test_migration_completeness_against_backup() -> None:
    """备份与 tactics/ 的相对路径集合必须一致 —— 治理不得丢文件。"""
    if not BACKUP.exists():
        pytest.skip("迁移备份不存在（可能已按保留策略清理）")
    def _source_set(root: Path) -> set[str]:
        return {
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        }

    b = _source_set(BACKUP)
    c = _source_set(TACTICS)
    # 只禁止「丢失」；治理过程新增 README / 测试产物是合理的，不应判失败
    missing = b - c
    assert not missing, (
        f"备份 {len(b)} / 当前 {len(c)}；丢失 {len(missing)} 个: {sorted(missing)[:5]}"
    )


def test_ruff_clean_on_tactics() -> None:
    """入库后 ruff 仍须零违规；CI 的 lint job 与本地同一套配置。"""
    ruff = PROJ / ".venv" / "bin" / "ruff"
    if not ruff.exists():
        pytest.skip("ruff 未安装")
    r = subprocess.run([str(ruff), "check", "--output-format=concise", str(TACTICS)],
                       cwd=PROJ, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, f"ruff 违规: {r.stdout[-500:]}"
