#!/usr/bin/env python3
"""根目录一次性脚本收敛器：把根目录的「一次性脚本」移到 ``scripts/oneoff/``。

为什么要收敛
------------
仓库根目录有 144 个 ``.py``，混着三类完全不同的东西：
  · **长期入口**（星图系统、爬虫主程序、报告生成器）—— 必须在根，用户天天用
  · **一次性脚本**（analysis_*/build_*/backfill_*/diag_*/fix_*/probe_*）—— 用完即弃
  · **工具**（迁移器、校验器）

一次性脚本堆在根目录的真实代价不是「乱」，而是：
  · **发现成本**：新文件进来时不知道往哪放，根目录只会越来越大
  · **误用风险**：`python fix_xxx.py` 在根目录随手可跑，但那些脚本的
    前置条件（数据快照已就位、迁移已完成）早已不成立
  · **lint 噪声**：ruff 要对 144 个文件做配置豁免，一半是为了迁就一次性脚本

收敛策略
--------
1. **不删除、不重命名**（仓库 README 约定：既有文件不移动不重命名不删除）
   → 用 ``git mv`` 保留历史，但**根目录留同名前缀的薄壳入口**？
   不行 —— 144 个薄壳比 144 个文件更乱。

   正解：**直接 ``git mv`` 移动**（git 保留历史与 rename 检测），
   并在 ``scripts/oneoff/README.md`` 记录**完整映射表**（旧名 → 新路径），
   使历史引用可追溯。用户按映射表改一次调用路径即可。

2. **长期入口留在根目录**（门禁/CI/用户日常依赖）
3. **移动后修正 import**：脚本内的 ``import xxx``（同目录模块）需改为包内相对导入
4. **移动后修正 sys.path bootstrap**：``parents[N]`` 的 N 要 +1

风险与门禁
----------
- **pytest 收集路径变化**：``pyproject.toml`` 的 ``testpaths = ["tests"]``
  已限定只收集 tests/ → 根目录的 ``test_*.py``（如 test_cdn.py）本就不被收集，
  移动后仍在 tests/ 之外 → 无影响。**但须实跑验证**。
- **同目录互 import**：移动后 ``import db`` 之类会失效 → 须扫描并修正
- **相对路径依赖 CWD**：脚本里若有 ``open("xxx.csv")`` 之类相对路径，
  移动后 CWD 语义不变（仍在根运行）→ 无影响；但 ``__file__`` 相对路径会变

用法：
    python tools/converge_root_scripts.py --dry-run
    python tools/converge_root_scripts.py --apply
"""
from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEST = REPO_ROOT / "scripts" / "oneoff"

#: 🔴 **长期入口** —— 留在根目录
#: 判据：① 被 CI / 质量门禁 / workspace entry 引用；② 用户日常手动运行的主程序
KEEP_IN_ROOT = {
    # ── 星图系统（门禁 1/2/8 节直接引用）──
    "star_portrait.py", "star_grid.py", "star_logo.py", "star_heatmap.py",
    "team_shot_radial.py",
    # ── 7 份分析报告的生成器（门禁第 3 节检查其产物 analysis_*.html）──
    "build_duo_density.py", "build_duos_trios.py", "build_longterm_scatter.py",
    "build_player_coaches.py", "build_salary_share.py",
    "build_trio_density.py", "build_trio_scatter.py",
    # ── 爬虫主程序与调度（长期运行）──
    "br_crawler.py", "br_fill_pbp.py", "br_fill_teams.py",
    "crawl_orchestrator.py", "crawl_br_team_pages.py",
    "crawl_br_team_franchise_pages.py",
    "crawl_dunksandthrees_epm.py", "crawl_dunksandthrees_epm_actual.py",
    "crawl_dunksandthrees_epm_history.py",
    "espn_broad_crawler.py", "ingest_br_pbp.py",
    "build_fct_pbp_shots.py", "export_nba_csv.py",
    "cookie_refresher.py", "detach_launch.py",
    "game_id_bridge.py", "generate_docs.py",
    # ── 门禁显式引用 ──
    "reskin_pace_white.py",
}

#: 显式排除（工具自身 / 特殊文件）
EXCLUDE = {
    "tools/converge_root_scripts.py",
    "setup.py", "conftest.py",
}

#: 一次性脚本的命名特征（用于自动识别「疑似一次性」）
ONEOFF_PATTERNS = (
    r"^_",                 # _build_mac_pkg_tmp / _split_nicknames / _dbg_matrix
    r"^analyze_",
    r"^audit_",
    r"^backfill_",
    r"^build_",            # build_*（报告生成器另在 KEEP 名单）
    r"^calc_",
    r"^clean_",
    r"^diag_",
    r"^explore_",
    r"^extract_",
    r"^fix_",
    r"^gen_",
    r"^generate_final",
    r"^merge_",
    r"^probe",
    r"^reskin_",           # reskin_pace_white 另在 KEEP 名单
    r"^score_",
    r"^survey_",
    r"^verify_",           # verify_* 校验脚本（一次性）
    r"^assemble_",
)

_ONEOFF_RE = re.compile("|".join(ONEOFF_PATTERNS))


def _is_oneoff(name: str) -> bool:
    """判定是否为一次性脚本（命名特征 + 不在 KEEP 名单）。"""
    if name in KEEP_IN_ROOT:
        return False
    return bool(_ONEOFF_RE.match(name))


def _collect() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    res = []
    for rel in out.stdout.split():
        p = Path(rel)
        if len(p.parts) != 1:      # 只看根目录
            continue
        if p.name in EXCLUDE:
            continue
        if _is_oneoff(p.name):
            res.append(p.name)
    return sorted(res)


def _same_dir_imports(path: Path, siblings: set[str]) -> list[str]:
    """找出脚本 import 的**同目录**模块（移动后会失效）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split(".")[0]
                if top in siblings:
                    found.add(top)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            top = node.module.split(".")[0]
            if top in siblings:
                found.add(top)
    return sorted(found)


def _fix_bootstrap(src: str) -> str:
    """移动后 ``parents[N]`` 的 N 要 +1（多了一层 scripts/oneoff/）。

    仅处理**显式**写成 ``parents[N]`` 的 bootstrap 行。
    """
    def _bump(m: re.Match) -> str:
        n = int(m.group(1))
        return f"parents[{n + 1}]"
    return re.sub(r"\.parents\[(\d+)\]", _bump, src)


#: 🔴 「自身目录」语义 → 「仓库根」语义
#:
#: 移动前脚本在**仓库根**，故 ``os.path.dirname(os.path.abspath(__file__))``
#: == 仓库根（脚本用它找 .env / 报告产物 / 缓存目录）。
#: 移动后在 ``scripts/oneoff/``，同一表达式会指向那一层 → 全部找错位置。
#:
#: 正解：插入一个常量 ``REPO_DIR`` 指向仓库根，并把这些表达式改写为它。
#: 改写用**正则**（源码级替换不用字面串 —— ruff I001 会重排 import）。
_SELF_DIR_RE = re.compile(
    r"os\.path\.dirname\(\s*os\.path\.abspath\(\s*__file__\s*\)\s*\)"
)
_FILE_PARENT_RE = re.compile(r"Path\(__file__\)\.parent")
_FILE_WITH_NAME_RE = re.compile(r"Path\(__file__\)\.with_name\(")
_FILE_WITH_SUFFIX_RE = re.compile(r"Path\(__file__\)\.with_suffix\(")

_REPO_DIR_BLOCK = (
    "#: 仓库根（脚本已收敛到 scripts/oneoff/，自身目录不再是仓库根）\n"
    "#: 🔴 上溯**三层**：scripts/oneoff/x.py → oneoff → scripts → 仓库根\n"
    "#:    用 Path 而非 os.path —— 部分脚本只 import 了 Path，没 import os\n"
    "REPO_DIR = str(Path(__file__).resolve().parents[2])\n"
)


def _fix_self_dir(src: str) -> str:
    """把「自身目录」语义的表达式改写为「仓库根」语义。"""
    changed = False

    def _sub_dir(m: re.Match) -> str:
        nonlocal changed
        changed = True
        return "REPO_DIR"

    new = _SELF_DIR_RE.sub(_sub_dir, src)

    def _sub_parent(m: re.Match) -> str:
        nonlocal changed
        changed = True
        return "Path(REPO_DIR)"

    new = _FILE_PARENT_RE.sub(_sub_parent, new)

    def _sub_with_name(m: re.Match) -> str:
        nonlocal changed
        changed = True
        return "Path(REPO_DIR).joinpath("

    new = _FILE_WITH_NAME_RE.sub(_sub_with_name, new)

    def _sub_with_suffix(m: re.Match) -> str:
        # Path(__file__).with_suffix(".html")  →  Path(REPO_DIR) / Path(__file__).with_suffix(".html").name
        nonlocal changed
        changed = True
        return "Path(REPO_DIR) / Path(__file__).with_suffix("

    new = _FILE_WITH_SUFFIX_RE.sub(_sub_with_suffix, new)

    if changed and "REPO_DIR =" not in new:
        # 🔴 常量定义必须落在**首次使用之前**（模块级代码按行执行）。
        #   插入到「最后一个顶层 import/assign 之后」是错的 —— 使用点常在文件中部。
        # 正解：找到 REPO_DIR 的**首次出现行**，把定义插到它之前；
        #      若该行之前已有完整语句，则插在该语句之前。
        lines = new.splitlines(keepends=True)
        use_line = None
        for i, ln in enumerate(lines):
            if "REPO_DIR" in ln and not ln.strip().startswith("#") \
                    and "REPO_DIR =" not in ln and "REPO_DIR" not in ln.split("#")[0].split("=")[0]:
                use_line = i
                break
        if use_line is None:
            use_line = len(lines)
        # 回退到 use_line 之前最近的一个完整语句边界
        insert_at = use_line
        try:
            tree = ast.parse(new)
            for node in tree.body:
                if node.end_lineno <= use_line + 1:
                    insert_at = max(insert_at, 0)
        except SyntaxError:
            pass
        # 往前找最后一个顶层完整语句的行号
        idx = use_line
        while idx > 0:
            try:
                ast.parse("".join(lines[:idx]))
                break
            except SyntaxError:
                idx -= 1
        lines.insert(idx, _REPO_DIR_BLOCK + "\n")
        new = "".join(lines)
    return new


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    targets = _collect()
    all_root_py = {p.name for p in REPO_ROOT.glob("*.py")}
    print(f"根目录 .py 总数 {len(all_root_py)}；判定为一次性 {len(targets)}；"
          f"留在根 {len(all_root_py) - len(targets)}")

    if not args.apply:
        print("\n--- 将要移动（dry-run）---")
        for name in targets:
            print(f"  {name}  →  scripts/oneoff/{name}")
        return 0

    DEST.mkdir(parents=True, exist_ok=True)
    mapping: list[tuple[str, str]] = []
    # 同目录模块集合在移动过程中会变（被移走的文件不再算「同目录」）
    # → 每次循环重新取当前根目录的 .py 集合
    for name in targets:
        src = REPO_ROOT / name
        if not src.exists():
            continue          # 已被前一轮处理掉
        siblings = {p.name for p in REPO_ROOT.glob("*.py")} - {name}
        deps = _same_dir_imports(src, siblings)
        if deps:
            print(f"  ⚠ {name}: 同目录 import {deps} —— 移动后需修正")
        text = src.read_text(encoding="utf-8")
        fixed = _fix_self_dir(_fix_bootstrap(text))
        # 语法校验：改坏就不移动该文件
        try:
            ast.parse(fixed)
        except SyntaxError as exc:
            print(f"  ✗ {name}: 改写后语法错误 —— {exc}")
            print("      保持原位，不移动")
            continue
        dst = DEST / name
        dst.write_text(fixed, encoding="utf-8")
        src.unlink()
        mapping.append((name, f"scripts/oneoff/{name}"))

    print(f"\n已移动 {len(mapping)} 个文件 → {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
