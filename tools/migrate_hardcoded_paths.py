#!/usr/bin/env python3
"""一次性迁移器：把散落的绝对路径字面量改为 ``common.nba_paths`` 解析式。

背景
----
本仓库横跨「仓库根 R / 数据盘根 D / 会话工作区 W」三处文件系统，
历史脚本把 ``/Volumes/12T/NBA/...`` 与 ``~/...`` 直接写进源码字面量。
硬编码路径的代价不是「不好看」，而是**会静默失效**：

    实测：源码里写的 node 路径是 ``.../node/versions/22.22.2/bin/node``，
    而机器上真实存在的是 ``.../node/versions/22.22.2-6/bin/node``
    → 换一次 node 版本，所有调用它的脚本一起断。

本工具把这些字面量换成 ``common.nba_paths`` 提供的解析式常量，
从而做到「路径只在一处定义 + 可用环境变量覆盖」。

工程约束（均为本仓库既有铁律，勿违反）
----------------------------------------
1. **不用字面串全局替换** —— ruff I001 会重排 import，若迁移逻辑依赖字面串，
   一次 autofix 就会让脚本失效。故本工具用 **AST + tokenize 定位偏移**，
   按字符偏移倒序替换。
2. **docstring 不改成表达式** —— 位置上的字符串常量才是 docstring；
   换成 ``str(X) + "..."`` 会让 ``__doc__`` 变 None，文档静默丢失。
   docstring / 注释只做**纯文本**改写（绝对路径 → 相对示意）。
3. **纯标准库**，不递归扫描大目录（外置盘 6TB 素材区会卡死 / exit 137）。
4. **不删不改业务逻辑** —— 只动路径字面量与新增 import。

用法
----
    python tools/migrate_hardcoded_paths.py --dry-run     # 只统计，不写盘
    python tools/migrate_hardcoded_paths.py --apply       # 写盘
    python tools/migrate_hardcoded_paths.py --apply --files a.py,b.py
"""
from __future__ import annotations

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# ── 已知绝对路径（迁移前的历史字面量）──────────────────────────────────────
REPO_NAME = "nba_desktop_omega_mac_migrate_2026-07-13"
R = f"/Volumes/12T/NBA/{REPO_NAME}"
D = "/Volumes/12T/NBA"
HOME = "/Users/deocheng"
WS = f"{HOME}/WorkBuddy/2026-07-13-10-47-43"

#: 迁移后允许出现在源码里的**唯一**绝对路径字面量（common/nba_paths 的兜底）
ALLOWED_AFTER = {"common/nba_paths.py"}

#: 不迁移的文件（门禁自身含字面量用于检测；迁移会使命禁失效）
EXEMPT_FILES = {
    "tools/verify_quality_gate.py",
    "tools/migrate_hardcoded_paths.py",
    "common/nba_paths.py",
    # 历史迁移验证脚本：docstring 与 HTML 报告里**同时**出现「源（12T 旧副本）」
    # 与「目标（本机生产盘）」两个**语义不同**的位置，通用规则会把两者合并 →
    # 只能手工维护，不可批量迁移。
    "verify_migration_integrity.py",
}


# ── 表达式级替换规则（按 key 长度倒序，先长后短）─────────────────────────
#   key    : 源字面量中的路径片段
#   value  : 替换后的 Python 表达式
#   symbol : 需要从 common.nba_paths import 的名字
def _rules() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = [
        # ── 仓库自身 ──
        (f"{R}/.env", "str(ENV_FILE)", "ENV_FILE"),
        (f"{R}/.venv/bin/python", "str(VENV_PYTHON)", "VENV_PYTHON"),
        # ── 数据盘根下的已知资产（用专用常量更清晰）──
        (f"{D}/raw_archive", "str(ARCHIVE_ROOT)", "ARCHIVE_ROOT"),
        (f"{D}/headshots", "str(HEADSHOTS_ROOT)", "HEADSHOTS_ROOT"),
        (f"{D}/nba_pg", "str(PG_DATA_DIR_LEGACY)", "PG_DATA_DIR_LEGACY"),
        # ── 用户目录 ──
        (
            f"{HOME}/.workbuddy/skills/nba-crawler-watch/scripts/watch_crawlers.py",
            "str(watchdog_script())",
            "watchdog_script",
        ),
        (f"{HOME}/nba_pg", "str(PG_DATA_DIR)", "PG_DATA_DIR"),
        (WS, "str(WORKSPACE_ROOT)", "WORKSPACE_ROOT"),
        (f"{HOME}/WorkBuddy", "str(WORKSPACE_PARENT)", "WORKSPACE_PARENT"),
        # ── 仓库 / 数据盘根本体 ──
        (R, "str(REPO_ROOT)", "REPO_ROOT"),
        (D, "str(DATA_ROOT)", "DATA_ROOT"),
    ]
    out.sort(key=lambda t: len(t[0]), reverse=True)
    return out


EXPR_RULES = _rules()

#: node 可执行文件：版本目录名带构建号，必须走 shutil.which，不能写死
NODE_PATTERNS = [
    re.compile(r"/Users/[^/]+/\.workbuddy/binaries/node/versions/[^/]+/bin/node"),
    re.compile(r"/Users/[^/]+/\.local/bin/node"),
    re.compile(r"/opt/homebrew/bin/node"),
]

#: 纯文本改写规则（用于 docstring 与注释；保持字符串为纯字符串）
TEXT_RULES = [
    (f"{R}", "<项目根>"),
    (f"{D}", "<数据盘根>"),
    # 裸盘根（不带 /NBA）也要覆盖：注释里常写「本机 /Volumes/12T」
    ("/Volumes/12T", "<数据盘根>"),
    (WS, "<会话工作区>"),
    (f"{HOME}/WorkBuddy", "~/WorkBuddy"),
    (HOME, "~"),
]

_ABS_RE = re.compile(r"/(?:Users|Volumes)/[^\s\"'`)]+")


# ── 文本工具 ───────────────────────────────────────────────────────────────
def _offset_table(src: str) -> list[int]:
    offsets, pos = [], 0
    for line in src.splitlines(keepends=True):
        offsets.append(pos)
        pos += len(line)
    return offsets


def _offset(offsets: list[int], row: int, col: int) -> int:
    return offsets[row - 1] + col


def _docstring_spans(tree: ast.AST) -> set[tuple[int, int, int, int]]:
    """返回所有 docstring 常量节点的位置元组 (lineno, col, end_lineno, end_col)。"""
    spans: set[tuple[int, int, int, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    c = body[0].value
                    spans.add((c.lineno, c.col_offset, c.end_lineno, c.end_col_offset))
    return spans


def _rewrite_text(text: str) -> str:
    """纯文本改写（docstring / 注释）：绝对路径 → 相对示意。"""
    for src, dst in TEXT_RULES:
        text = text.replace(src, dst)
    text = NODE_PATTERNS[0].sub("node", text)
    text = NODE_PATTERNS[1].sub("node", text)
    return text


_EXPR_MAP = {src: (expr, sym) for src, expr, sym in EXPR_RULES}

#: 所有已知路径的合并正则（长路径优先，单次扫描，避免多条规则二次替换）
#:
#: 🔴 **必须加路径边界负向前瞻**：``/Volumes/12T/NBA/headshots`` 是
#: ``/Volumes/12T/NBA/headshots_crawl.log`` 的**前缀**，若不做边界约束，
#: 会被误判成「headshots 目录 + _crawl.log 后缀」——
#: 结果虽然恰好拼回同一个字符串，但**语义已错**（日志文件 ≠ 目录），
#: 一旦目录改名日志路径就跟着漂。
_PATH_RE = re.compile(
    "|".join(
        re.escape(p) + r"(?![A-Za-z0-9_])"
        for p in sorted(_EXPR_MAP, key=len, reverse=True)
    )
)
_NODE_RE = re.compile("|".join(p.pattern for p in NODE_PATTERNS))


def _rewrite_expression(text: str) -> tuple[str, set[str]]:
    """表达式级改写（普通字符串字面量）。

    返回 (新表达式文本, 需要的符号集合)。**返回值是 Python 表达式源码，
    不带引号** —— 调用方用它整体替换掉原字符串 token。

    实现要点（两个坑都在这里踩过）：
    - **必须一次扫描替换全部出现处**：用 ``str.partition`` 只会替换首个匹配，
      会漏掉同一个字符串里的第 2、3 处（如 HTML 模板里嵌的 JS 路径）。
    - **多条规则不能依次作用于同一文本**：第一条规则改写后文本形态已变，
      后续规则可能二次替换（或匹配不到）。故用**占位符 + 重组**：
      先把每处路径换成占位符，最后统一把片段拼成 ``片段 + 表达式 + 片段``。
    """
    symbols: set[str] = set()
    hits: list[str] = []

    def _repl(m: re.Match) -> str:
        expr, sym = _EXPR_MAP[m.group(0)]
        symbols.add(sym)
        hits.append(expr)
        return f"\x00{len(hits) - 1}\x00"

    out = _PATH_RE.sub(_repl, text)

    def _node_repl(m: re.Match) -> str:
        symbols.add("node_binary")
        hits.append("node_binary()")
        return f"\x00{len(hits) - 1}\x00"

    out = _NODE_RE.sub(_node_repl, out)

    if not hits:
        return out, symbols

    segs = re.split(r"\x00(\d+)\x00", out)
    parts: list[str] = []
    for i, seg in enumerate(segs):
        if i % 2 == 0:
            if seg:
                parts.append(repr(seg))
        else:
            parts.append(hits[int(seg)])
    return " + ".join(parts), symbols


def _split_string_token(text: str) -> tuple[str, str, str, str] | None:
    """拆分一个 STRING token 文本 → (prefix, quote, content, suffix)。

    无法安全解析时返回 None（调用方跳过该 token）。
    """
    m = re.match(r"^([A-Za-z]*)('''|\"\"\"|'|\")", text)
    if not m:
        return None
    prefix, quote = m.group(1), m.group(2)
    if not text.endswith(quote) or len(text) < len(prefix) + 2 * len(quote):
        return None
    content = text[len(prefix) + len(quote) : -len(quote)]
    return prefix, quote, content, quote


# ── 主流程 ─────────────────────────────────────────────────────────────────
def migrate_file(path: Path, rel: str, apply: bool) -> dict:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return {"status": "parse-error", "detail": str(exc)}

    docstrings = _docstring_spans(tree)
    offsets = _offset_table(src)

    edits: list[tuple[int, int, str]] = []  # (start, end, new_text)
    needed: set[str] = set()
    doc_count = code_count = comment_count = 0

    # 1) 字符串 token（docstring 与普通字符串分开处理）
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except tokenize.TokenError as exc:
        return {"status": "tokenize-error", "detail": str(exc)}

    for tok in tokens:
        if tok.type == tokenize.STRING:
            start = _offset(offsets, *tok.start)
            end = _offset(offsets, *tok.end)
            raw = src[start:end]
            parts = _split_string_token(raw)
            if parts is None:
                continue
            prefix, quote, content, _ = parts
            is_fstring = "f" in prefix.lower()
            is_doc = (tok.start[0], tok.start[1], tok.end[0], tok.end[1]) in docstrings

            if is_doc:
                new_content = _rewrite_text(content)
                if new_content != content:
                    doc_count += 1
                    edits.append((start, end, f"{prefix}{quote}{new_content}{quote}"))
                continue

            if is_fstring:
                # f-string 内部不能裸放表达式 → 用 {expr} 占位
                new_content, syms = _rewrite_fstring(content)
                if syms:
                    needed |= syms
                    if new_content != content:
                        code_count += 1
                        edits.append((start, end, f"{prefix}{quote}{new_content}{quote}"))
                continue

            if "b" in prefix.lower():
                # bytes 字面量：路径语义与 str 不同，跳过（实践中不出现）
                continue

            new_expr, syms = _rewrite_expression(content)
            if syms and new_expr != content:
                needed |= syms
                code_count += 1
                # 表达式整体替换原 token（不再套引号）
                edits.append((start, end, new_expr))

        elif tok.type == getattr(tokenize, "FSTRING_MIDDLE", -1):
            # Python 3.12+ 把 f-string 拆成 FSTRING_START / FSTRING_MIDDLE / FSTRING_END，
            # 3.10 下则是单个带 f 前缀的 STRING token —— 两条路径都要覆盖，
            # 否则 3.12 运行时 f-string 内的路径会整体漏迁。
            start = _offset(offsets, *tok.start)
            end = _offset(offsets, *tok.end)
            new_text, syms = _rewrite_fstring(tok.string)
            if syms and new_text != tok.string:
                needed |= syms
                code_count += 1
                edits.append((start, end, new_text))

        elif tok.type == tokenize.COMMENT:
            start = _offset(offsets, *tok.start)
            end = _offset(offsets, *tok.end)
            raw = src[start:end]
            new_raw = _rewrite_text(raw)
            if new_raw != raw:
                comment_count += 1
                edits.append((start, end, new_raw))

    # 2) 需要 import 的符号 → 插入 import 语句
    import_line = ""
    if needed:
        import_line = _build_import(needed, tree, src)

    if not edits and not import_line:
        return {"status": "clean"}

    # 3) 应用编辑（按偏移倒序，避免前面的改动影响后面的偏移）
    new_src = src
    for start, end, text in sorted(edits, key=lambda t: -t[0]):
        new_src = new_src[:start] + text + new_src[end:]

    if import_line:
        new_src = _insert_import(new_src, import_line)

    # 4) 语法校验（改坏就丢弃该文件）
    try:
        ast.parse(new_src)
    except SyntaxError as exc:
        return {"status": "syntax-error", "detail": str(exc)}

    if apply:
        path.write_text(new_src, encoding="utf-8")

    return {
        "status": "changed",
        "docstrings": doc_count,
        "code": code_count,
        "comments": comment_count,
        "symbols": sorted(needed),
        "import": import_line.strip(),
    }


def _rewrite_fstring(content: str) -> tuple[str, set[str]]:
    """f-string 内部改写：把路径片段换成 ``{expr}`` 占位。"""
    symbols: set[str] = set()
    out = content
    for src, expr, sym in EXPR_RULES:
        if src in out:
            out = out.replace(src, "{" + expr + "}")
            symbols.add(sym)
    for pat in NODE_PATTERNS:
        if pat.search(out):
            out = pat.sub("{node_binary()}", out)
            symbols.add("node_binary")
    return out, symbols


def _build_import(symbols: set[str], tree: ast.AST, src: str) -> str:
    """生成 import 语句；若已有 from common.nba_paths import 则合并。"""
    existing = re.search(r"^from common\.nba_paths import (.+)$", src, re.MULTILINE)
    if existing:
        have = {s.strip() for s in existing.group(1).split(",")}
        merged = sorted(have | symbols)
        return f"__MERGE_NBA_PATHS__{', '.join(merged)}"
    return f"from common.nba_paths import {', '.join(sorted(symbols))}"


def _root_module(node: ast.AST) -> str:
    """取 import 语句的根模块名（用于 stdlib 判定）。"""
    if isinstance(node, ast.Import):
        return node.names[0].name.split(".")[0] if node.names else ""
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")[0]
    return ""


def _insert_import(src: str, import_line: str) -> str:
    """把 import 插到合法位置。

    位置规则（按优先级）：
      1. ``from __future__`` 之后 —— 否则触发 F404
      2. 最后一个 **stdlib** import 之后 —— ruff isort 的分组是
         future / stdlib / third-party / first-party，``common`` 属 first-party，
         插在 stdlib 之前会同时触发 I001
      3. 无 stdlib import 时，插在第一个 import 之前

    精确排序交给 ``ruff check --select I001 --fix`` 收尾（迁移逻辑不依赖字面串，
    此处 autofix 安全）。
    """
    if import_line.startswith("__MERGE_NBA_PATHS__"):
        merged = import_line.replace("__MERGE_NBA_PATHS__", "")
        return re.sub(
            r"^from common\.nba_paths import .+$",
            f"from common.nba_paths import {merged}",
            src,
            count=1,
            flags=re.MULTILINE,
        )

    tree = ast.parse(src)
    imports = [
        n
        for n in tree.body
        if isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    if not imports:
        # 无 import：放在 docstring 之后
        if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant):
            insert_at = tree.body[0].end_lineno
        else:
            insert_at = 0
    else:
        stdlib_names = getattr(sys, "stdlib_module_names", frozenset())
        insert_at = None
        for node in imports:
            mod = _root_module(node)
            if mod == "__future__":
                insert_at = node.end_lineno  # future 之后
                break
        if insert_at is None:
            for node in imports:
                mod = _root_module(node)
                if mod and mod not in stdlib_names:
                    break
                insert_at = node.end_lineno
            if insert_at is None:
                insert_at = imports[-1].end_lineno

    lines = src.splitlines(keepends=True)
    lines.insert(insert_at, import_line + "\n")
    return "".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="硬编码绝对路径迁移器")
    ap.add_argument("--apply", action="store_true", help="写盘（默认 dry-run）")
    ap.add_argument("--files", help="逗号分隔的文件（相对仓库根），默认全仓已跟踪 .py")
    args = ap.parse_args()

    if args.files:
        targets = [REPO_ROOT / f.strip() for f in args.files.split(",") if f.strip()]
    else:
        out = subprocess.run(
            ["git", "ls-files", "*.py"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        targets = [REPO_ROOT / p for p in out.stdout.splitlines() if p]

    stats = {"changed": 0, "clean": 0, "skipped": 0, "error": 0}
    for path in targets:
        rel = str(path.relative_to(REPO_ROOT))
        if rel in EXEMPT_FILES:
            stats["skipped"] += 1
            continue
        if not path.exists():
            stats["skipped"] += 1
            continue
        res = migrate_file(path, rel, args.apply)
        stats[res["status"]] = stats.get(res["status"], 0) + 1
        if res["status"] == "changed":
            print(
                f"  {rel}: doc={res['docstrings']} code={res['code']} cmt={res['comments']} "
                f"sym={','.join(res['symbols'])}"
            )
        elif res["status"] in ("syntax-error", "parse-error", "tokenize-error"):
            print(f"  ✗ {rel}: {res['status']} — {res.get('detail', '')}")

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] changed={stats.get('changed', 0)} clean={stats.get('clean', 0)} "
          f"skipped={stats.get('skipped', 0)} error={stats.get('error', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
