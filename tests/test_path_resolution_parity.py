#!/usr/bin/env python3
"""shell / Python 路径解析一致性测试（跨语言契约）。

为什么需要这个测试
------------------
``common/paths.sh``（shell 侧）与 ``common/nba_paths.py``（Python 侧）是
**两份实现**，必须给出**同一个答案**。一旦不一致，后果不是「报错」，
而是**静默地指向不同位置**：

- shell 启动的 Postgres 在 ``A``，Python 连的是 ``B`` → 连不上 / 连到旧实例
- shell 读的数据在 ``A``，Python 写的在 ``B`` → 数据分叉

🔴 实测过的两次真实分叉
----------------------
1. **DATA_ROOT 兜底不同**：Python 侧兜底 = 仓库父目录；
   shell 侧曾硬编码 ``/Volumes/12T/NBA`` → CI 上仓库在
   ``/home/runner/work/...`` → 两侧指向不同位置（run 42876413458 失败）。
2. **软链口径不同**：Python 用 ``Path(__file__).resolve()``（**物理**路径），
   shell 用 ``cd && pwd``（**逻辑**路径）→ macOS 的 ``/tmp`` → ``/private/tmp``
   时两侧字符串不等。

本测试把「一致性」变成**可执行断言**，并**在临时目录里模拟 CI 环境**
（仓库不在 12T 上、父目录无特征标记、路径含软链）——本地全绿不代表
CI 也绿，只有模拟过才算。

运行：pytest tests/test_path_resolution_parity.py -v
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parent.parent
PATHS_SH = PROJ / "common" / "paths.sh"
NBA_PATHS_PY = PROJ / "common" / "nba_paths.py"

#: 三项必须一致的解析结果（顺序固定）
PARITY_KEYS = ("PG_DATA_DIR", "PROJ_ROOT", "DATA_ROOT")

#: 会影响路径解析的环境变量 —— 两侧都必须**清空**后才可比
ENV_KEYS = ("NBA_REPO_ROOT", "NBA_DATA_ROOT", "NBA_PG_DATA_DIR",
            "NBA_WORKSPACE_ROOT", "NBA_WORKSPACE_PARENT")


def _clean_env() -> dict[str, str]:
    """清掉会污染路径解析的环境变量。

    shell 侧与 Python 侧**必须**用同一套干净环境，否则：
    shell 读到 ``NBA_REPO_ROOT`` 走 env 分支、Python 侧被清掉走推导分支
    → 又是一处「假不一致」。
    """
    env = dict(os.environ)
    for k in ENV_KEYS:
        env.pop(k, None)
    return env


def _shell_resolve(cwd: Path) -> list[str]:
    """在给定目录里实跑 common/paths.sh，拿三项解析值。

    🔴 必须 source **该目录内**的 ``paths.sh``（模拟目录里复制过去的那份），
    而不是全局常量 —— 否则两侧测的根本不是同一份代码，会得出
    「shell 解析出真实仓库路径 / Python 解析出模拟目录路径」这种
    **测试自身的 bug**（本测试第一版就踩了这个坑）。
    """
    local_sh = cwd / "common" / "paths.sh"
    sh_path = local_sh if local_sh.exists() else PATHS_SH
    probe = (
        '. "' + str(sh_path) + '"; printf "%s|%s|%s" '
        '"$PG_DATA_DIR" "$PROJ_ROOT" "$DATA_ROOT"'
    )
    p = subprocess.run(["bash", "-c", probe], cwd=str(cwd),
                       capture_output=True, text=True, env=_clean_env(), check=True)
    return p.stdout.strip().split("|")


def _python_resolve(cwd: Path) -> list[str]:
    """在给定目录里实跑 common/nba_paths.py，拿三项解析值。"""
    code = (
        "import sys; sys.path.insert(0, " + repr(str(cwd)) + ")\n"
        "from common import nba_paths as np\n"
        "print('|'.join([str(np.PG_DATA_DIR), str(np.REPO_ROOT), str(np.DATA_ROOT)]))\n"
    )
    env = _clean_env()
    p = subprocess.run([sys.executable, "-c", code], cwd=str(cwd),
                       capture_output=True, text=True, env=env, check=True)
    return p.stdout.strip().split("|")


def _assert_parity(cwd: Path, label: str) -> None:
    sh = _shell_resolve(cwd)
    py = _python_resolve(cwd)
    assert len(sh) == 3 and len(py) == 3, f"{label}: 解析结果数量异常"
    for key, s, p in zip(PARITY_KEYS, sh, py):
        assert s == p, (
            f"{label}: {key} 不一致\n"
            f"  shell  = {s}\n"
            f"  python = {p}"
        )


def test_parity_in_current_repo():
    """当前仓库位置下两侧一致（本地开发环境）。"""
    _assert_parity(PROJ, "当前仓库")


def test_parity_in_ci_like_layout(tmp_path):
    """模拟 CI 环境：仓库在临时目录、父目录无特征标记、路径含软链。

    这是 run 42876413458 失败的场景 —— 那里 Python 侧回退到仓库父目录，
    而 shell 侧曾硬编码 /Volumes/12T/NBA。
    """
    # 用 symlink 造一个带软链的路径（macOS 的 /tmp 就是这种形态）
    real_root = tmp_path / "real"
    repo = real_root / "nba_desktop_omega"
    (repo / "common").mkdir(parents=True)
    shutil.copy2(PATHS_SH, repo / "common" / "paths.sh")
    shutil.copy2(NBA_PATHS_PY, repo / "common" / "nba_paths.py")

    link_root = tmp_path / "link"
    link_root.symlink_to(real_root, target_is_directory=True)
    linked_repo = link_root / "nba_desktop_omega"

    # 父目录（real_root）**刻意不含** nba_pg / raw_archive / headshots
    # → 强制走兜底分支（这正是 CI 的情形）
    assert not (real_root / "nba_pg").exists()
    assert not (real_root / "raw_archive").exists()

    _assert_parity(linked_repo, "CI 模拟（软链 + 无特征标记父目录）")


def test_paths_sh_uses_physical_path():
    """shell 侧必须用 ``pwd -P``（物理路径），与 Python 的 ``resolve()`` 对齐。

    macOS 的 /tmp → /private/tmp 软链会让逻辑路径与物理路径不等；
    这是实测过的第二处真实分叉。
    """
    src = PATHS_SH.read_text(encoding="utf-8")
    assert "pwd -P" in src, "common/paths.sh 未使用 pwd -P（物理路径）"
    # 不应出现裸的 `pwd)`（逻辑路径）
    bad = [ln for ln in src.splitlines() if "&& pwd)" in ln]
    assert not bad, f"common/paths.sh 存在逻辑路径 pwd: {bad}"
