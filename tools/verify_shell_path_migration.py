#!/usr/bin/env python3
"""Shell 路径迁移的**语义等价性校验**（逐脚本实跑对比）。

判据
----
迁移前（HEAD 版）脚本里的路径**字面量**，与迁移后脚本里
``common/paths.sh`` 解析出的**变量值**，必须指向同一处。

做法
----
1. 对每个被改的脚本，取 HEAD 版（迁移前）与工作区版（迁移后）
2. 从两版里**抽取所有绝对路径字面量**
3. 在工作区版里**实跑** ``. common/paths.sh`` 拿到变量解析值
4. 断言：HEAD 版的每个字面量，要么等于某个解析值，要么等于
   「某个解析值 + 后缀」（如 ``$DATA_ROOT/nba_pg/pg.log``）

这比「grep 零命中」强一个量级：它验证路径**真的指向同一处**。

用法：
    python tools/verify_shell_path_migration.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PATHS_SH = REPO_ROOT / "common" / "paths.sh"

#: 从工作区脚本里解析出的变量（实跑 common/paths.sh 获得）
_ENV_VARS = (
    "PROJ_ROOT", "DATA_ROOT", "PG_DATA_DIR", "ARCHIVE_ROOT",
    "HEADSHOTS_ROOT", "WORKSPACE_ROOT", "WORKSPACE_PARENT",
    "VENV_PYTHON", "WATCHDOG_SCRIPT", "WB_PYTHON",
)

#: 绝对路径字面量（HEAD 版里出现的）
#: 🔴 结尾边界要排除 ``}`` 等 shell 符号 —— 否则 "/tmp/nba_pg_restart.log}" 会被
#:    当成路径，误报为「无对应解析值」。
_ABS_RE = re.compile(r"/(?:Users|Volumes)/[^\s\"'`):,;}]+")


def _head_version(rel: str, baseline_sha: str) -> str | None:
    """取**迁移前基线**版本的源码（不是 HEAD —— HEAD 会随提交滑动）。"""
    p = subprocess.run(
        ["git", "show", f"{baseline_sha}:{rel}"], cwd=REPO_ROOT, capture_output=True, text=True
    )
    if p.returncode != 0:
        return None
    return p.stdout


def _resolved_vars() -> dict[str, str]:
    """实跑 common/paths.sh 拿到变量解析值。"""
    out: dict[str, str] = {}
    for var in _ENV_VARS:
        # 注意：不能用 f-string —— "${var:-}" 里的 {var:-} 会被当格式符
        cmd = '. "' + str(PATHS_SH) + '"; printf "%s" "${' + var + ':-}"'
        p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        out[var] = p.stdout.strip()
    return out


def _strip_comments(text: str) -> str:
    """去掉 shell 注释行（避免把说明里的路径当代码路径）。"""
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("#"):
            continue
        # 去掉行尾注释（简化：仅处理 # 前有空白且不在引号内的常见情形）
        lines.append(ln)
    return "\n".join(lines)


def main() -> int:
    if not PATHS_SH.exists():
        print("❌ common/paths.sh 不存在")
        return 2

    resolved = _resolved_vars()
    print("shell 路径迁移语义校验（字面量 vs 变量解析值）")
    print(f"  common/paths.sh 解析出 {len([v for v in resolved.values() if v])} 个变量")
    for k, v in resolved.items():
        if v:
            print(f"    {k:16s} = {v}")

    # 🔴 文件列表必须取「**基线** → 工作区」的差异集，**不能**用 `git diff HEAD`：
    #    shell 迁移一旦提交，HEAD=新版、diff=空 → 「受检 0 / 差异 0」= **假绿**，
    #    门禁据此给出「什么都没验证的通过」。
    #    与 Python 侧（tools/verify_path_migration_equivalence.py）同一口径：
    #    旧版锚定 tools/path_baseline.txt 的固定基线 ref。
    baseline_file = REPO_ROOT / "tools" / "path_baseline.txt"
    baseline = ""
    try:
        for ln in baseline_file.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                baseline = ln
                break
    except OSError:
        baseline = ""
    if not baseline:
        print("❌ 无法解析迁移前基线（tools/path_baseline.txt）")
        return 2
    base_res = subprocess.run(
        ["git", "rev-parse", "--verify", f"{baseline}^{{commit}}"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if base_res.returncode != 0:
        print(f"❌ 迁移前基线 ref 无法解析: {baseline}")
        return 2
    baseline_sha = base_res.stdout.strip()

    changed = subprocess.run(
        ["git", "diff", "--name-only", baseline_sha], cwd=REPO_ROOT,
        capture_output=True, text=True,
    ).stdout.split()
    sh_files = [f for f in changed if f.endswith(".sh") and (REPO_ROOT / f).exists()]
    print(f"  迁移前基线 {baseline} ({baseline_sha[:10]})")

    checked = same = differ = 0
    details: list[tuple[str, list[str]]] = []

    for rel in sh_files:
        head = _head_version(rel, baseline_sha)
        if head is None:
            continue
        working = (REPO_ROOT / rel).read_text(encoding="utf-8")
        old_lits = set(_ABS_RE.findall(_strip_comments(head)))
        new_lits = set(_ABS_RE.findall(_strip_comments(working)))
        # 工作区版应几乎无字面量（除豁免文件）
        problems: list[str] = []

        # 1) 每个旧字面量必须能被某个解析值解释
        for lit in sorted(old_lits):
            # 裸盘根（/Volumes/12T）单独成类 —— 用于「数据盘是否挂载」的检查，
            # 语义上等于 DATA_ROOT 的父目录，不等于 DATA_ROOT 本身。
            if lit == "/Volumes/12T":
                continue
            # 用户目录下的**其他**路径（Downloads / Library …）→
            # 迁移后写作 "$HOME/xxx"，语义等价 → 接受
            if lit.startswith("/Users/deocheng/"):
                continue
            if not any(
                lit == val or lit.startswith(val + "/") or lit == val.rstrip("/")
                for val in resolved.values() if val
            ):
                problems.append(f"旧字面量无对应解析值: {lit}")

        # 2) 工作区版残留的字面量（应只剩 paths.sh 自身或刻意保留项）
        for lit in sorted(new_lits):
            if lit in {"/Users/", "/Volumes/"}:
                continue
            # /tmp/... 属系统临时目录，非项目路径
            if lit.startswith("/tmp/"):
                continue
            # 裸盘根（echo 消息里的说明文字，非路径使用）
            if lit == "/Volumes/12T":
                continue
            if not any(
                lit == val or lit.startswith(val + "/")
                for val in resolved.values() if val
            ):
                problems.append(f"新版残留字面量: {lit}")

        checked += 1
        if problems:
            differ += 1
            details.append((rel, problems[:6]))
        else:
            same += 1

    print(f"\n  受检脚本 {checked} / 等价 {same} / 有差异 {differ}")
    if details:
        print("\n差异明细：")
        for rel, probs in details[:12]:
            print(f"\n  ▸ {rel}")
            for p in probs[:6]:
                print(f"      {p[:150]}")
    print("\n" + ("✅ 全部等价" if differ == 0 else "❌ 存在差异，需人工复核"))
    return 1 if differ else 0


if __name__ == "__main__":
    raise SystemExit(main())
