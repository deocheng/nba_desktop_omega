#!/usr/bin/env python3
"""tactics/ 硬编码绝对路径治理器（tokenize / AST 感知，安全幂等）。

事故复盘（2026-11-11）：
  早期版本用**行级正则**猜 docstring 边界，把 import 注进了 docstring、
  重复注入、批量替换中文标点、并留下未闭合三引号；结果 458 个文件里
  443 个无法解析（而迁移前备份是 458/458 可解析）。本版从备份恢复的
  干净基线重做，强制以下不变量：

  1. 只改「字符串字面量 / 注释」里的路径文本，绝不改中文标点、缩进、
     代码结构，也不再补 __main__ 守卫（那是独立议题，会改变执行语义）；
  2. 代码里的路径字面量 -> ``str(<helper>("相对路径"))``；
     docstring / 注释里的路径 -> 占位符，保持文档可读，
     同时让质量门禁 11a 的**全文**扫描零命中；
  3. 每个文件改完立刻做 ast.parse + 路径语义等价求值，
     任一失败即**整文件丢弃**，绝不落盘破损内容；
  4. 幂等：已有 bootstrap 不重复注入，已治理过的文件零改动。

用法：
    python3 tools/fix_tactics_paths.py --check   # 只体检，不写盘（残留则 rc=1）
    python3 tools/fix_tactics_paths.py --apply   # 执行改写
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import json
import re
import sys
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TACTICS_ROOT = REPO_ROOT / "tactics"

# 绝对路径前缀 -> (helper, 文档占位符)。**长前缀必须排在短前缀前面**。
RULES: tuple[tuple[str, str, str], ...] = (
    ("/Volumes/12T/NBA/action_analysis", "tactics_data_file", "<TACTICS_DATA_ROOT>"),
    ("/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13", "repo_file", "<REPO_ROOT>"),
    ("/Volumes/12T/NBA", "data_file", "<DATA_ROOT>"),
    ("/Users/deocheng/WorkBuddy/2026-07-13-10-47-43", "workspace_file", "<WORKSPACE_ROOT>"),
    ("/Users/deocheng", "__home__", "~"),
)
SCAN_PREFIXES = ("/Volumes/12T", "/Users/deocheng")
BOOT_MARK = "nba-paths bootstrap"


def _match(path: str) -> tuple[str, str, str] | None:
    for prefix, helper, placeholder in RULES:
        if path.startswith(prefix):
            return prefix, helper, placeholder
    return None


def _expr_for(path: str) -> tuple[str, set[str]]:
    """把一条绝对路径变成等价表达式，返回 (表达式, 需要导入的名字)。"""
    m = _match(path)
    if m is None:
        raise ValueError(f"无匹配前缀: {path}")
    prefix, helper, _ = m
    rest = path[len(prefix):].lstrip("/")
    had_slash = path.endswith("/")
    arg = json.dumps(rest, ensure_ascii=False)
    needs: set[str] = set()
    if helper == "__home__":
        expr = f"str(Path.home() / {arg})"
        needs.add("Path")
    else:
        expr = f"str({helper}({arg}))"
        needs.add(helper)
    if had_slash:
        expr += ' + "/"'
    return expr, needs


def _placeholder(text: str) -> str:
    """docstring / 注释里的绝对路径 -> 占位符（保持其余文本原样）。"""
    for prefix, _, placeholder in RULES:
        text = text.replace(prefix, placeholder)
    return text


def _docstring_starts(tree: ast.Module) -> set[tuple[int, int]]:
    """收集模块/类/函数 docstring 的起始 (lineno, col_offset)。"""
    out: set[tuple[int, int]] = set()

    def walk(node: ast.AST) -> None:
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                out.add((first.lineno, first.col_offset))
        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(tree)
    return out


def _unquote(raw: str) -> tuple[str, str] | None:
    """拆分 STRING token -> (前缀+引号形态, 引号内原文)。不解析转义。"""
    i = 0
    while i < len(raw) and raw[i] in "rRuUbBfF":
        i += 1
    prefix, body = raw[:i], raw[i:]
    for q in ('"""', "'''", '"', "'"):
        if body.startswith(q) and body.endswith(q) and len(body) >= 2 * len(q):
            return prefix, body[len(q):-len(q)]
    return None


def _offsets(lines: list[str]) -> list[int]:
    out = [0]
    for line in lines:
        out.append(out[-1] + len(line))
    return out


def _probe_env() -> dict:
    """直接加载单文件模块，绕开 common/__init__.py 的第三方依赖。"""
    spec = importlib.util.spec_from_file_location(
        "_nba_paths_probe", REPO_ROOT / "common" / "nba_paths.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return {
        "str": str,
        "Path": Path,
        "data_file": mod.data_file,
        "repo_file": mod.repo_file,
        "workspace_file": mod.workspace_file,
        "tactics_data_file": mod.tactics_data_file,
    }


def _bootstrap_lines(rel: str, needs: set[str], src: str) -> list[str]:
    """生成自举块：保证脚本从任意 cwd / 软链运行时都能 import common.nba_paths。

    ``Path`` 属标准库，不能从 common.nba_paths 导入；若原文件已有该 import
    则完全复用，否则补一行，避免 F811 重复定义。
    """
    depth = len(Path(rel).parts)
    nba = sorted(needs - {"Path"})
    out = [f"# --- {BOOT_MARK} (auto, idempotent) ---"]
    if nba:
        out += [
            "import sys as _nba_sys",
            "from pathlib import Path as _nba_Path",
            f'_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[{depth}]))',
        ]
    if "Path" in needs and not re.search(r"(?m)^\s*from pathlib import .*\bPath\b", src):
        out.append("from pathlib import Path")
    if nba:
        out.append("from common.nba_paths import " + ", ".join(nba))
    out.append("")
    return out


def _insert_bootstrap(src: str, lines: list[str]) -> str:
    """插到模块 docstring 与所有 __future__ import 之后（future 必须是首个语句）。"""
    tree = ast.parse(src)
    after = 0
    if (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)):
        after = max(after, tree.body[0].end_lineno or 0)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            after = max(after, node.end_lineno or 0)
    buf = src.splitlines(keepends=True)
    if after and not buf[after - 1].endswith("\n"):
        buf[after - 1] += "\n"
    buf[after:after] = [ln + "\n" for ln in lines]
    return "".join(buf)


def transform(src: str, rel: str, env: dict) -> tuple[str, dict]:
    """返回 (新源码, 统计)。任何校验失败抛 ValueError，调用方须丢弃该文件。"""
    tree = ast.parse(src)
    doc_starts = _docstring_starts(tree)
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))

    edits: list[tuple[int, int, str]] = []   # (start_abs, end_abs, new_text)
    checks: list[tuple[str, str]] = []      # (原字面量, 新表达式) 供语义等价校验
    all_needs: set[str] = set()
    lines = src.splitlines(keepends=True)
    off = _offsets(lines)

    def ab(row: int, col: int) -> int:
        return off[row - 1] + col

    # 预扫描：相邻 STRING token 属于同一「隐式拼接」组（Python 会合成一个值）。
    # 只替换首段会在表达式后留下裸字符串 -> invalid syntax，必须整组一起处理。
    gap = {tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
           tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING}
    concat: dict[int, list[int]] = {}
    i, n = 0, len(toks)
    while i < n:
        if toks[i].type != tokenize.STRING:
            i += 1
            continue
        followers: list[int] = []
        j = i + 1
        while j < n and toks[j].type in gap:
            j += 1
        while j < n and toks[j].type == tokenize.STRING:
            followers.append(j)
            j += 1
            while j < n and toks[j].type in gap:
                j += 1
        if followers:
            concat[i] = followers
            i = j
        else:
            i += 1

    consumed: set[int] = set()
    for idx, tok in enumerate(toks):
        if idx in consumed:
            continue
        if tok.type == tokenize.COMMENT:
            if any(p in tok.string for p in SCAN_PREFIXES):
                new = _placeholder(tok.string)
                edits.append((ab(*tok.start), ab(*tok.end), new))
            continue
        if tok.type != tokenize.STRING or not any(p in tok.string for p in SCAN_PREFIXES):
            continue

        is_doc = (tok.start[0], tok.start[1]) in doc_starts
        parsed = _unquote(tok.string)
        inner = parsed[1] if parsed else ""
        is_plain = (not is_doc and parsed is not None
                    and "f" not in parsed[0].lower()
                    and "\n" not in inner and "{" not in inner
                    and inner == inner.strip()
                    and inner.startswith(SCAN_PREFIXES))

        if is_plain:
            followers = concat.get(idx, [])
            if followers:
                parts = [inner]
                for fj in followers:
                    follow = _unquote(toks[fj].string)
                    if follow is None or "f" in follow[0].lower():
                        raise ValueError(f"第 {tok.start[0]} 行拼接组含 f-string，需人工处置")
                    parts.append(follow[1])
                    consumed.add(fj)
                full = "".join(parts)
                if not full.startswith(SCAN_PREFIXES):
                    raise ValueError(f"第 {tok.start[0]} 行拼接组无法归一: {full[:60]!r}")
                # 首段负责「绝对路径前缀 -> helper」，后续片段原样用 + 连接，
                # 否则完整值会被重复拼接（等价性校验会拦下）。
                expr, needs = _expr_for(inner)
                for fj in followers:
                    t2 = toks[fj]
                    edits.append((ab(*t2.start), ab(*t2.end), "+ " + t2.string))
                full_expr = expr + " + " + " + ".join(toks[fj].string for fj in followers)
                checks.append((full, full_expr))
            else:
                expr, needs = _expr_for(inner)
                full_expr = expr
                checks.append((inner, full_expr))
            edits.append((ab(*tok.start), ab(*tok.end), expr))
            all_needs |= needs
        elif is_doc:
            # docstring：只做前缀占位符替换，不动任何中文标点/换行
            edits.append((ab(*tok.start), ab(*tok.end), _placeholder(tok.string)))
        else:
            # 代码里的混合文本字符串：占位符替换会悄悄改坏运行时路径，
            # 因此整文件放弃改写，交由人工处置（绝不静默破坏）。
            raise ValueError(
                f"第 {tok.start[0]} 行存在混合文本路径，需人工处置: {inner[:60]!r}"
            )

    if not edits:
        return src, {"changed": False, "expr": 0, "doc": 0}

    # 语义等价：新表达式求值必须逐字符等于原字面量
    for original, expr in checks:
        try:
            actual = eval(expr, {"__builtins__": {}}, env)  # noqa: S307 - 表达式由本文件生成
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"表达式求值失败 {expr}: {exc}") from exc
        if actual != original:
            raise ValueError(f"语义不等价: {original!r} != {actual!r} ({expr})")

    buf = src
    for start, end, new in sorted(edits, reverse=True):
        buf = buf[:start] + new + buf[end:]

    if all_needs and BOOT_MARK not in buf:
        buf = _insert_bootstrap(buf, _bootstrap_lines(rel, all_needs, src))
    elif all_needs and BOOT_MARK in buf:
        # 幂等补名：已有 bootstrap 但缺新 helper 时，扩展其 import 行
        wanted = all_needs - {"Path"}
        if wanted:
            for line in buf.splitlines():
                if line.startswith("from common.nba_paths import "):
                    have = {x.strip() for x in line.split("import ", 1)[1].split(",")}
                    if wanted - have:
                        buf = buf.replace(
                            line,
                            "from common.nba_paths import " + ", ".join(sorted(have | wanted)),
                            1,
                        )
                    break

    ast.parse(buf)  # 最终语法门禁：不过就整文件丢弃
    if any(p in buf for p in SCAN_PREFIXES):
        raise ValueError("改写后仍残留绝对路径字面量")
    return buf, {"changed": buf != src, "expr": len(checks), "doc": len(edits) - len(checks)}


def main() -> int:
    ap = argparse.ArgumentParser(description="tactics/ 硬编码路径治理")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="只体检，不写盘")
    mode.add_argument("--apply", action="store_true", help="执行改写")
    args = ap.parse_args()

    env = _probe_env()
    changed = failed = residual = 0
    expr_total = doc_total = 0
    failures: list[str] = []

    for path in sorted(TACTICS_ROOT.rglob("*.py")):
        if any(part in {"__pycache__", ".venv", "node_modules"} for part in path.parts):
            continue
        rel = path.relative_to(TACTICS_ROOT).as_posix()
        try:
            src = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            failures.append(f"{rel}: 读取失败 {exc}")
            failed += 1
            continue
        if not any(p in src for p in SCAN_PREFIXES):
            continue
        residual += 1
        try:
            new, stat = transform(src, rel, env)
        except (ValueError, SyntaxError, tokenize.TokenError) as exc:
            failures.append(f"{rel}: {exc}")
            failed += 1
            continue
        if args.apply and stat["changed"]:
            path.write_text(new, encoding="utf-8")
            changed += 1
        expr_total += stat["expr"]
        doc_total += stat["doc"]

    label = "APPLY" if args.apply else "CHECK"
    print(f"[{label}] 含绝对路径文件={residual}  待改写={changed if args.apply else residual}  "
          f"表达式替换={expr_total}  文档/注释占位={doc_total}  失败={failed}")
    for f in failures[:15]:
        print(f"  [FAIL] {f}")
    if len(failures) > 15:
        print(f"  ... 另有 {len(failures) - 15} 条")

    if args.check:
        return 1 if (residual or failed) else 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
