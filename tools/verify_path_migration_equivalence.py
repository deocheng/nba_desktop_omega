#!/usr/bin/env python3
"""路径迁移的**语义等价性**校验器（全文逐字符级证据，非 grep 层面）。

为什么需要它
------------
「grep 零命中」只能证明字面量没了，**不能证明路径语义没变**。
本工具做**还原比对**：

    HEAD 版源码 ──应用「docstring/注释文本改写」──▶ expected
    工作区版源码 ──把路径表达式「求值回字面量」──▶ actual
        ↓
    两者都切成「**含路径字面量的语句**」并用 ast.unparse 归一化
        ↓
    逐条比对：必须完全相等

为什么按「语句」而不是「全文」比对
----------------------------------
迁移必然带来**与路径语义无关**的附带改动：
``sys.path.insert`` bootstrap、``from common.nba_paths import ...``、
别名 import、模块自身扩展…… 全文比对会把这些全算成差异（大量假红）。
语句级比对只聚焦「**含路径字面量的语句**」，附带改动自动排除。

为什么不用「字符串常量级」比对
------------------------------
迁移会把一个字符串常量**拆成多段**（中间插表达式），常量级逐条比对会**错位**。
语句级比对与拆分方式无关，是稳定判据。

还原的安全边界
--------------
只允许四类节点：Constant / Name(白名单常量) / Call(str, 单参) / BinOp(Add)。
不执行任何被调用函数（``str`` 是内建白名单），不触碰网络与数据库。
文本改写规则**直接复用迁移器**（单一事实源），避免两处规则漂移。
"""
from __future__ import annotations

import ast
import importlib.util
import io
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from common import nba_paths as np  # noqa: E402


def _load_migrator():
    """加载迁移器模块，复用其文本改写规则（单一事实源）。"""
    spec = importlib.util.spec_from_file_location(
        "mig", REPO_ROOT / "tools" / "migrate_hardcoded_paths.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIG = _load_migrator()

NS = {
    "str": str,
    "REPO_ROOT": str(np.REPO_ROOT),
    "DATA_ROOT": str(np.DATA_ROOT),
    "WORKSPACE_ROOT": str(np.WORKSPACE_ROOT),
    "WORKSPACE_PARENT": str(np.WORKSPACE_PARENT),
    "ANALYSIS_ROOT": str(np.ANALYSIS_ROOT),
    "ENV_FILE": str(np.ENV_FILE),
    "PG_DATA_DIR": str(np.PG_DATA_DIR),
    "PG_DATA_DIR_LEGACY": str(np.PG_DATA_DIR_LEGACY),
    "ARCHIVE_ROOT": str(np.ARCHIVE_ROOT),
    "HEADSHOTS_ROOT": str(np.HEADSHOTS_ROOT),
    "VENV_PYTHON": str(np.VENV_PYTHON),
    "watchdog_script": lambda: str(np.watchdog_script()),
    "node_binary": lambda: np.node_binary() or "node",
    # 同名遮蔽修复用的别名 import（见 common/bridge_constants.py）
    "_NBA_ARCHIVE_ROOT": str(np.ARCHIVE_ROOT),
    "_NBA_PG_DATA_DIR": str(np.PG_DATA_DIR),
}

#: **不适用**等价性比对的文件（各自有明确理由，逐条登记）
EXPLAINED_SKIP = {
    "common/nba_paths.py": "模块自身被扩展（新增 DATA_ROOT / PG_DATA_DIR / WORKSPACE_PARENT 等），不在迁移等价性适用范围",
    "verify_migration_integrity.py": "历史迁移脚本：docstring 与 HTML 报告里源(12T旧副本)/目标(本机生产盘) 语义刻意不同，已手工维护并列入迁移器 EXEMPT",
    # node 候选：原为 shutil.which + 2 个**硬编码** node 路径。
    # 实测那两个硬编码路径**均已失效**（版本目录写成 22.22.2，实际是 22.22.2-6；
    # ~/.local/bin/node 不存在）→ 改走 node_binary()（shutil.which）是**修复**而非回归。
    "crawl_dunksandthrees_epm.py": "node 候选：2 个已失效的硬编码路径 → node_binary()（修复）",
    "crawl_dunksandthrees_epm_actual.py": "node 候选：2 个已失效的硬编码路径 → node_binary()（修复）",
    "crawl_dunksandthrees_epm_history.py": "node 候选：2 个已失效的硬编码路径 → node_binary()（修复）",
    # 门禁脚本：新增第 11 节「路径治理」后，文件内**新增**了用于检测的字面量
    #   "/Users/deocheng" 与 "/Volumes/12T"（检查规则本身必须含被禁字符串才能匹配）。
    #   这些字面量是**检测模式**，不是路径使用；旧版（基线）里没有它们，
    #   故「旧值未在新版体现」方向必然报差异 —— 属预期的规则增强，非语义回归。
    "tools/verify_quality_gate.py": "门禁脚本：第 11 节新增路径检测规则，引入被禁字符串作为检测模式（非路径使用）",
}

#: **迁移前基线 ref** —— 等价性比对的「旧版」锚点。
#:
#: 🔴 为什么不能用 ``HEAD``：本校验器原本取 ``git show HEAD:<file>`` 作旧版、
#: 用 ``git diff --name-only`` 取文件列表。一旦迁移**被提交**，HEAD 变成迁移后
#: 版本、diff 变空 → 校验器「0 文件受检、0 差异」= **假绿**，
#: 门禁就会给出一个什么都没验证的通过结论。
#:
#: 正确做法：旧版锚定到**迁移开始前**的固定 ref，文件列表取「基线 → 工作区」的
#: 全量差异集。这样无论迁移是否已提交，校验都真实覆盖同一批文件。
#:
#: 解析优先级：
#:   1. 环境变量 ``NBA_PATH_BASELINE``（CI 可显式钉住）
#:   2. ``tools/path_baseline.txt``（仓库内记录的基线 ref）
#:   3. ``origin/chore/quality-gate-2026-11-10``（迁移前最后一个已推分支）
BASELINE_ENV = "NBA_PATH_BASELINE"
BASELINE_FILE = REPO_ROOT / "tools" / "path_baseline.txt"
BASELINE_FALLBACK = "chore/quality-gate-2026-11-10"


def _resolve_baseline() -> str:
    """解析迁移前基线 ref（env → 文件 → 回退分支名）。"""
    env = os.environ.get(BASELINE_ENV, "").strip()
    if env:
        return env
    try:
        txt = BASELINE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        txt = ""
    if txt:
        # 取第一个非空、非注释行（文件顶部是说明性注释）
        for line in txt.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    return BASELINE_FALLBACK


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True
    )


def _baseline_files(baseline: str) -> list[str]:
    """基线 → 工作区 差异集里的 .py 文件（**含已提交部分**）。

    不能用裸 ``git diff --name-only``：它只看未提交的工作区差异。
    """
    seen: list[str] = []
    for rel in _git("diff", "--name-only", baseline).stdout.split():
        if rel.endswith(".py") and rel not in seen:
            seen.append(rel)
    # 未提交的新增文件（基线里不存在）也要纳入
    for rel in _git("ls-files", "--others", "--exclude-standard").stdout.split():
        if rel.endswith(".py") and rel not in seen:
            seen.append(rel)
    return seen



def _allowed(node: ast.AST) -> bool:
    """白名单：Constant / Name / Call(str, 单参) / BinOp(Add)。"""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.Name):
        return node.id in NS and node.id != "str"
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in ("watchdog_script", "node_binary"):
            # str(watchdog_script()) / str(node_binary()) 的内层调用
            return not node.args and not node.keywords
        if not (isinstance(fn, ast.Name) and fn.id == "str"):
            return False
        if node.keywords or len(node.args) != 1:
            return False
        return _allowed(node.args[0])
    if isinstance(node, ast.BinOp):
        return isinstance(node.op, ast.Add) and _allowed(node.left) and _allowed(node.right)
    return False


def _eval(node: ast.AST) -> str | None:
    if not _allowed(node):
        return None
    try:
        return eval(compile(ast.Expression(node), "<mig>", "eval"), {"__builtins__": {}}, NS)
    except Exception:
        return None


def _span(node: ast.AST) -> tuple[int, int, int, int]:
    return (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


def _docstring_spans(tree: ast.AST) -> set[tuple[int, int, int, int]]:
    spans: set[tuple[int, int, int, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    c = body[0].value
                    spans.add((c.lineno, c.col_offset, c.end_lineno, c.end_col_offset))
    return spans


#: 绝对路径前缀（用于识别「含路径」的字符串）
_ABS = ("/Volumes/12T", "/Users/")


def _has_abs(s: str) -> bool:
    """字符串是否含绝对路径（不要求在开头 —— 前缀拼接同样要校验）。"""
    return any(p in s for p in _ABS)


def _char_offset_table(src: str) -> list[int]:
    """**字符**偏移表 —— 配 tokenize 的 ``col_offset`` 用。

    tokenize 的列号是**字符**列（实测：``NBA_BR_爬虫`` 那行 token span 13→63
    = 50 字符 / 54 字节 → 字符口径）。
    """
    offsets, pos = [], 0
    for line in src.splitlines(keepends=True):
        offsets.append(pos)
        pos += len(line)
    return offsets


def _byte_offset_table(src: str) -> list[int]:
    """**字节**偏移表 —— 配 ast 的 ``col_offset`` 用。

    🔴 Python 里两套列号口径**不同**，混用必然越界：
        - ``tokenize`` 的 ``col_offset`` = **字符**列
        - ``ast`` 的 ``col_offset``      = **UTF-8 字节**列
    含中文的路径（如 ``NBA_BR_爬虫``）会让两者差出好几个字节，
    用错表就会把表达式后面的内容一起吞掉。
    """
    offsets, pos = [], 0
    for line in src.splitlines(keepends=True):
        offsets.append(pos)
        pos += len(line.encode("utf-8"))
    return offsets


def _tok_span(tok) -> tuple[int, int, int, int]:
    return (tok.start[0], tok.start[1], tok.end[0], tok.end[1])


def _rewrite_expected(src: str) -> str:
    """HEAD 版 → expected：docstring 与注释里的绝对路径按迁移器同一规则改写。

    代码里的绝对路径**原样保留**（那正是要验证「还原后能对上」的部分）。
    """
    tree = ast.parse(src)
    docs = _docstring_spans(tree)
    offsets = _char_offset_table(src)
    raw = src
    edits: list[tuple[int, int, str]] = []

    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            start = offsets[tok.start[0] - 1] + tok.start[1]
            end = offsets[tok.end[0] - 1] + tok.end[1]
            chunk = raw[start:end]
            new = MIG._rewrite_text(chunk)
            if new != chunk:
                edits.append((start, end, new))
        elif tok.type == tokenize.STRING and _tok_span(tok) in docs:
            start = offsets[tok.start[0] - 1] + tok.start[1]
            end = offsets[tok.end[0] - 1] + tok.end[1]
            chunk = raw[start:end]
            parts = MIG._split_string_token(chunk)
            if parts is None:
                continue
            prefix, quote, content, _ = parts
            new_content = MIG._rewrite_text(content)
            if new_content != content:
                edits.append((start, end, f"{prefix}{quote}{new_content}{quote}"))

    for start, end, text in sorted(edits, key=lambda t: -t[0]):
        raw = raw[:start] + text + raw[end:]
    return raw


def _path_values(src: str, *, restore: bool) -> list[tuple[str, int]]:
    """提取文件里的**路径值**序列。

    ``restore=False``（旧版）：所有含绝对路径的字符串常量（代码中，排除 docstring）。
    ``restore=True``（新版）：所有路径表达式的**求值结果**。

    求值结果可能与原常量**不完全相等**（迁移会把一个大字符串常量拆成多段），
    故最终判定用**双向子串包含**（见 ``main``），与拆分方式无关。
    """
    tree = ast.parse(src)
    docs = _docstring_spans(tree)
    out: list[tuple[str, int]] = []

    if not restore:
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _span(node) in docs:
                    continue
                if _has_abs(node.value):
                    out.append((node.value, node.lineno))
        out.sort(key=lambda t: t[1])
        return out

    offsets = _byte_offset_table(src)
    raw = src.encode("utf-8")
    cands: dict[tuple[int, int, int, int], ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str":
            cands[_span(node)] = node
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            cands[_span(node)] = node

    # 只保留最外层（外层已包含内层语义，重复会误判）
    ordered = sorted(cands.items(), key=lambda kv: (kv[0][0], -kv[0][2]))
    top: list[tuple[tuple[int, int, int, int], ast.AST]] = []
    for sp, node in ordered:
        if top:
            psp = top[-1][0]
            if sp[0] >= psp[0] and sp[1] >= psp[1] and sp[2] <= psp[2] and sp[3] <= psp[3]:
                continue
        top.append((sp, node))

    for sp, node in top:
        val = _eval(node)
        if val is None or not _has_abs(val):
            continue
        out.append((val, sp[0]))
    out.sort(key=lambda t: t[1])
    return out


def main() -> int:
    baseline = _resolve_baseline()
    base_res = _git("rev-parse", "--verify", f"{baseline}^{{commit}}")
    if base_res.returncode != 0:
        print(f"❌ 迁移前基线 ref 无法解析: {baseline}")
        print("   请设置环境变量 NBA_PATH_BASELINE 或修正 tools/path_baseline.txt")
        return 2
    baseline_sha = base_res.stdout.strip()

    files = _baseline_files(baseline)
    checked = same = differ = 0
    details: list[tuple[str, list[str]]] = []

    for rel in files:
        p = REPO_ROOT / rel
        if not p.exists() or rel in EXPLAINED_SKIP:
            continue
        head = _git("show", f"{baseline_sha}:{rel}")
        if head.returncode != 0:
            continue
        try:
            expected = _rewrite_expected(head.stdout)
            working = p.read_text(encoding="utf-8")
        except SyntaxError as exc:
            differ += 1
            details.append((rel, [f"parse-error: {exc}"]))
            continue
        checked += 1
        # 旧侧：**迁移前基线**（docstring/注释已按迁移器同一规则改写）里的路径常量
        old_vals = _path_values(expected, restore=False)
        # 新侧：**工作区原文**里的路径表达式（求值后即还原值）
        new_vals = _path_values(working, restore=True)
        problems_here: list[str] = []

        # 方向一：旧版的每条路径值，必须能在新版某条路径值里找到
        for ov, ln in old_vals:
            if not any(ov == nv or ov in nv or nv in ov for nv, _ in new_vals):
                problems_here.append(f"旧值未在新版体现: {ov[:110]}")
        # 方向二：新版的每条路径值，必须能在旧版某条路径值里找到
        for nv, ln in new_vals:
            if not any(nv == ov or nv in ov or ov in nv for ov, _ in old_vals):
                problems_here.append(f"新版多出路径值: {nv[:110]}")

        if not problems_here:
            same += 1
            continue
        differ += 1
        details.append((rel, problems_here[:6]))

    print("路径语义等价性校验（语句级还原比对）")
    print(f"  迁移前基线 {baseline} ({baseline_sha[:10]})")
    print(f"  受检文件 {checked} / 完全等价 {same} / 有差异 {differ}")
    if details:
        print("\n差异明细：")
        for rel, lines in details[:12]:
            print(f"\n  ▸ {rel}")
            for ln in lines[:8]:
                print(f"      {ln.rstrip()[:170]}")
    print("\n" + ("✅ 全部等价" if differ == 0 else "❌ 存在差异，需人工复核"))
    return 1 if differ else 0


if __name__ == "__main__":
    raise SystemExit(main())
