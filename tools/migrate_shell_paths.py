#!/usr/bin/env python3
"""Shell 脚本硬编码绝对路径迁移器（37 个 .sh）。

与 Python 侧迁移器（tools/migrate_hardcoded_paths.py）**共用同一套 AST/tokenize
定位思想**，但实现针对 shell：

- shell 没有 AST，改用**行级正则 + 语法感知**的替换
- 替换只发生在**双引号/裸字面量**位置，且保留原有引号风格
- 每个脚本注入一次 ``. "$PROJ_ROOT/common/paths.sh"``（幂等）

为什么 shell 侧要有独立的 paths.sh
---------------------------------
Python 侧是 ``common/nba_paths.py``，shell 侧无法 import。
故建 ``common/paths.sh``，**解析规则与 Python 侧一一对应**
（尤其 PG 数据目录的解析顺序必须一致，否则 shell 启动的 PG 与 Python
读到的 PG 会指向不同目录）。

🔴 边界约束
-----------
路径字面量后面常跟下划线/字母（如 ``/Volumes/12T/NBA/nba_pg/postmaster.pid``
的 ``nba_pg`` 目录 vs ``nba_pg_old``）。替换必须加负向前瞻
``(?![A-Za-z0-9_])``，否则会把 ``nba_pg_old`` 误判成 ``nba_pg`` + ``_old``。

用法：
    python tools/migrate_shell_paths.py            # dry-run
    python tools/migrate_shell_paths.py --apply
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# ── 已知路径（与 Python 侧 rules() 一一对应）──────────────────────────────
R = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
D = "/Volumes/12T/NBA"
HOME = "/Users/deocheng"

#: (源字面量, 替换文本)。替换文本里的变量引用**必须自带 $**。
#:
#: 🔴 顺序敏感：更长路径优先（按长度倒序匹配）。
#:    ``/Users/deocheng/nba_pg`` 必须先于 ``/Users/deocheng`` 命中，
#:    否则会被拆成 ``$HOME/nba_pg``（语义不同：那是本机 PG，而 12T 那份是旧副本）。
RULES: list[tuple[str, str]] = [
    # WorkBuddy 托管的 Python（**版本目录不可写死** —— 升级即失效）
    (f"{HOME}/.workbuddy/binaries/python/versions/[^/\"'\\s]+/bin/python3",
     "$WB_PYTHON"),
    # 仓库根 → common/paths.sh 的 PROJ_ROOT
    (f"{R}", "$PROJ_ROOT"),
    # 数据盘根 → DATA_ROOT
    (f"{D}", "$DATA_ROOT"),
    # 本机生产 PG 数据目录 → PG_DATA_DIR（与 Python 侧同一解析规则）
    (f"{HOME}/nba_pg", "$PG_DATA_DIR"),
    # 用户目录其余部分 → $HOME（等价替换，保留后缀）
    (f"{HOME}", "$HOME"),
]

def _is_regex(p: str) -> bool:
    """规则是否为正则（含正则元字符）。"""
    return bool(re.search(r"[\^\$\*\+\?\(\)\[\]\{\}\|]", p))


def _build_rule_map() -> tuple[dict[str, str], list[tuple[re.Pattern, str]]]:
    """把规则编译成 ({字面量: 替换}, [(正则, 替换)])。

    正则规则（如版本目录段）无法用字面量做 key，故用 ``re.Pattern`` 单独匹配。
    """
    literal = {}
    patterns: list[tuple[re.Pattern, str]] = []
    for src, dst in RULES:
        if _is_regex(src):
            patterns.append((re.compile(src), dst))
        else:
            literal[src] = dst
    return literal, patterns


#: 负向前瞻：路径后不能紧跟字母/数字/下划线
#:
#: 🔴 规则表里既有**字面量**（需 re.escape）也有**正则**（版本目录段）。
#:    故统一按「正则」处理，字面量用 re.escape 包一层。
_PATH_RE = re.compile(
    "|".join(
        (p if _is_regex(p) else re.escape(p)) + r"(?![A-Za-z0-9_])"
        for p, _ in sorted(RULES, key=lambda t: -len(t[0]))
    )
)
_LITERAL_MAP, _PATTERNS = _build_rule_map()


_LITERAL_MAP, _PATTERNS = _build_rule_map()

#: 已 source paths.sh 的标记（幂等检测）
_SOURCE_MARK = "common/paths.sh"

#: 不迁移的文件
EXEMPT_FILES = {
    "tools/migrate_shell_paths.py",
    "common/paths.sh",   # 它自己就是定义处
}

#: paths.sh 的 source 片段（按脚本所在层级调整相对路径）
_SOURCE_TMPL = (
    '# source 统一路径解析（与 Python 侧 common/nba_paths.py 对齐）\n'
    'if [ -f "{rel}" ]; then\n'
    '  . "{rel}"\n'
    'fi\n'
)


def _find_paths_sh(rel: str) -> str:
    """按脚本层级算出 common/paths.sh 的相对路径。

    顶层脚本 → ``common/paths.sh``；``external_crawler/crawler/x.sh`` → ``../../common/paths.sh``
    """
    depth = len(Path(rel).parts) - 1          # 目录深度
    up = "../" * depth if depth else ""
    return f"{up}common/paths.sh"


def _insert_source(src: str, rel: str) -> str:
    """在 shebang 之后、首个非注释块之前插入 source。"""
    if _SOURCE_MARK in src:
        return src
    block = _SOURCE_TMPL.format(rel=_find_paths_sh(rel))
    lines = src.splitlines(keepends=True)
    # 找 shebang 行号
    idx = 0
    if lines and lines[0].startswith("#!"):
        idx = 1
    # 跳过紧随其后的注释块（文件头说明）
    while idx < len(lines) and lines[idx].lstrip().startswith("#"):
        idx += 1
    lines.insert(idx, "\n" + block + "\n")
    return "".join(lines)


def _sub_paths(text: str, counter: list[int]) -> str:
    """把文本里的路径字面量换成变量引用。

    顺序：先正则规则（更长、更具体），再字面量规则。
    """
    for pat, dst in _PATTERNS:
        def _rp(m: re.Match) -> str:
            counter[0] += 1
            return dst
        text = pat.sub(_rp, text)

    def _lr(m: re.Match) -> str:
        counter[0] += 1
        return _LITERAL_MAP[m.group(0)]
    return _PATH_RE.sub(_lr, text)


def _rewrite_line(line: str) -> tuple[str, int]:
    """替换单行里的路径字面量 → 变量引用。返回 (新行, 替换次数)。"""
    counter = [0]
    if not _PATH_RE.search(line) and not any(p.search(line) for p, _ in _PATTERNS):
        return line, 0

    # 先处理带引号的字面量（保留引号形式）
    def _quoted(m: re.Match) -> str:
        quote = m.group(0)[0]
        body = m.group(0)[1:-1]
        if not (_PATH_RE.search(body) or any(p.search(body) for p, _ in _PATTERNS)):
            return m.group(0)
        return f"{quote}{_sub_paths(body, counter)}{quote}"

    new = re.sub(r'"([^"\n]*)"|\'([^\'\n]*)\'', _quoted, line)

    # 未被引号包裹的裸字面量（bash 里是词的一部分）
    def _bare(m: re.Match) -> str:
        start = m.start()
        # 前面紧跟 $ 或字母数字 → 已在变量/标识符中，跳过
        if start > 0 and (line[start - 1].isalnum() or line[start - 1] in "_$/"):
            if not (start >= 2 and line[start - 2] == "$"):
                return m.group(0)
        counter[0] += 1
        return _LITERAL_MAP[m.group(0)]

    new = _PATH_RE.sub(_bare, new)
    return new, counter[0]


def migrate_file(path: Path, rel: str, apply: bool) -> dict:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    total = 0
    new_lines: list[str] = []
    for line in lines:
        nl, n = _rewrite_line(line)
        total += n
        new_lines.append(nl)
    new_src = "".join(new_lines)

    if total:
        new_src = _insert_source(new_src, rel)

    # 语法校验：bash -n
    proc = subprocess.run(["bash", "-n"], input=new_src, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"status": "syntax-error", "detail": proc.stderr.strip()[:200]}

    if apply and total:
        path.write_text(new_src, encoding="utf-8")

    return {"status": "changed" if total else "clean", "count": total}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    out = subprocess.run(
        ["git", "ls-files", "*.sh"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    stats = {"changed": 0, "clean": 0, "skipped": 0, "error": 0}
    for rel in out.stdout.split():
        if rel in EXEMPT_FILES:
            stats["skipped"] += 1
            continue
        p = REPO_ROOT / rel
        if not p.exists():
            stats["skipped"] += 1
            continue
        res = migrate_file(p, rel, args.apply)
        stats[res["status"]] = stats.get(res["status"], 0) + 1
        if res["status"] == "changed":
            print(f"  {rel}: {res['count']} 处")
        elif res["status"] == "syntax-error":
            print(f"  ✗ {rel}: {res['detail']}")

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] changed={stats.get('changed', 0)} clean={stats.get('clean', 0)} "
          f"skipped={stats.get('skipped', 0)} error={stats.get('error', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
