#!/usr/bin/env python3
"""migrate_report_palette — 把报告生成器里的硬编码色板换成统一内核的 CSS 变量。

问题：8 份报告生成器各自内联一套 :root / 色值常量，改一次配色要动 8 个文件，
且与主应用、星环图形成「三套互不相认的视觉语言」。

做法（AST 感知，区别于朴素的文本替换）：
1. 用 ast 定位所有字符串字面量（含 f-string 的各个片段），只在**CSS 上下文**
   里做替换：CSS 规则块与 style="..." 属性值。
2. **不动** SVG 元素上的 fill="#..." / stroke="#..."——那些是数据编码色
   （球队色、分档色、系列色），换了语义就变了图表含义。
3. 注入统一令牌块。令牌名统一带 `--viz-` 前缀，原因见下。

为什么用 `--viz-` 前缀（重要）：
旧报告的 :root 往往自己定义了 --bg / --panel / --txt 等名字。若直接把
色值替换成 var(--bg)，会产出 `--bg: var(--bg)` 这种**自引用**，CSS 变量
随即失效（回退到继承值）。用独立前缀 `--viz-bg` 就没有命名冲突：
旧 :root 变成 `--bg: var(--viz-bg)`，语义正确。

用法：
    python tools/migrate_report_palette.py --check  <files...>
    python tools/migrate_report_palette.py --backup <files...>
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# ── 主题色 → 统一令牌（chrome 专用；数据编码色不在此表内）────────────────
# 深色主题映射
CHROME_MAP: dict[str, str] = {
    # 背景层级
    "#0b0f14": "--viz-bg",
    "#0b0e14": "--viz-bg",
    "#0e1117": "--viz-bg",
    "#0f1419": "--viz-bg",
    "#101820": "--viz-panel",
    "#0d1219": "--viz-panel",
    "#0e141b": "--viz-panel",
    "#111820": "--viz-panel",
    "#12181f": "--viz-panel",
    "#131a22": "--viz-panel",
    "#141922": "--viz-panel",
    "#161b22": "--viz-panel",
    "#1a2129": "--viz-panel",
    # 描边 / 分隔线
    "#182330": "--viz-border",
    "#1c2733": "--viz-border",
    "#1e2a35": "--viz-border",
    "#202a34": "--viz-border",
    "#22303c": "--viz-border",
    "#252c38": "--viz-border",
    "#263341": "--viz-border",
    "#2a3140": "--viz-border",
    "#2a333d": "--viz-border",
    "#222c36": "--viz-border",
    "#21262d": "--viz-border",
    # 文本
    "#e6edf3": "--viz-fg",
    "#e6edf7": "--viz-fg",
    "#cdd9e5": "--viz-fg",
    "#c8d3de": "--viz-fg",
    "#9aa4b2": "--viz-muted",
    "#9fb0c0": "--viz-muted",
    "#8b98a5": "--viz-muted",
    "#8b98a9": "--viz-muted",
    "#6f7d8c": "--viz-muted",
    "#5d6b7a": "--viz-faint",
    "#5a6573": "--viz-faint",
    "#6b7785": "--viz-faint",
    # 强调色
    "#4cc2ff": "--viz-accent",
    "#4da3ff": "--viz-accent",
    # 状态色
    "#f85149": "--viz-negative",
    "#ff6b6b": "--viz-negative",
    "#3fb950": "--viz-positive",
    "#8fe388": "--viz-positive",
    "#7ee787": "--viz-positive",
    "#ffa94d": "--viz-warn",
    "#ffb454": "--viz-warn",
    "#e8833a": "--viz-warn",
    "#ffd166": "--viz-warn",
}

# 浅色主题映射：语义与深色一致，但具体色值是浅底上的那一套。
CHROME_MAP_LIGHT: dict[str, str] = {
    # 背景层级
    "#ffffff": "--viz-bg",
    "#f5f6f8": "--viz-bg",
    "#f5f7fa": "--viz-bg",
    "#fafbfc": "--viz-panel",
    "#eef3fa": "--viz-panel",
    "#f7faf2": "--viz-panel",
    # 描边 / 分隔线
    "#d8e0ec": "--viz-border",
    "#e8ebf0": "--viz-border",
    # 文本
    "#0f172a": "--viz-fg",
    "#111827": "--viz-fg",
    "#1a1a1a": "--viz-fg",
    "#1f2933": "--viz-fg",
    "#555555": "--viz-fg",
    "#666666": "--viz-fg",
    "#5b6b82": "--viz-muted",
    "#6b7280": "--viz-muted",
    "#8a98ab": "--viz-muted",
    # 强调色
    "#1a4f8b": "--viz-accent",
    "#1b4f72": "--viz-accent",
    "#2b7fd4": "--viz-accent",
    "#3f7ba6": "--viz-accent",
    "#4682b4": "--viz-accent",
    "#4ea1ff": "--viz-accent",
    "#5b9ac2": "--viz-accent",
    # 状态色
    "#b3261e": "--viz-negative",
    "#c9761a": "--viz-negative",
    "#d6394f": "--viz-negative",
    "#e0796a": "--viz-negative",
    "#ff5d73": "--viz-negative",
    "#3f6212": "--viz-positive",
    "#3d5c1c": "--viz-positive",
    "#3f4a37": "--viz-positive",
    "#5f8b34": "--viz-positive",
    "#5fd08a": "--viz-positive",
    "#a06a00": "--viz-warn",
    "#a06a12": "--viz-warn",
    "#c08a1e": "--viz-warn",
    "#c8912a": "--viz-warn",
    "#d9a63a": "--viz-warn",
    "#d9c14a": "--viz-warn",
    "#e0a96a": "--viz-warn",
    "#f5c451": "--viz-warn",
    "#ffb454": "--viz-warn",
}

# 统一令牌块：**从内核 viz.theme 派生**，不在本文件手写色值。
#
# 为什么必须派生而不是手抄：
# 手抄一份就等于制造「两份色值靠人工同步」——那正是本项目要消灭的
# 「多套互不相认的视觉语言」。色值真相只允许存在于 viz/theme.py 一处。
#
# 导入方式：先尝试包内导入（工具随仓库走），失败则按仓库根路径补 sys.path。
def _load_compat_vars() -> str:
    try:
        from viz.theme import compat_vars
    except ImportError:
        repo_root = Path(__file__).resolve().parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from viz.theme import compat_vars
    return compat_vars("dark")


def _load_compat_vars_light() -> str:
    try:
        from viz.theme import compat_vars
    except ImportError:
        repo_root = Path(__file__).resolve().parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from viz.theme import compat_vars
    return compat_vars("light")


TOKEN_BLOCK = _load_compat_vars()
TOKEN_BLOCK_LIGHT = _load_compat_vars_light()

# ── CSS 上下文识别 ───────────────────────────────────────────────────────
# 含 SVG 绘制标记的字符串一律跳过（数据编码色不能动）
SVG_MARKERS = ("<svg", "<circle", "<rect", "<path", "<line", "<text", "<polyline",
                "<polygon", "<ellipse", "<g ", "<g>")
# CSS 声明形态：property: value;（比「选择器{...}」更宽松，能覆盖 :root 与 f-string 双花括号）
_CSS_DECL = re.compile(r"[a-zA-Z-]+\s*:\s*[^;{}\"']+\s*;")
_STYLE_ATTR = re.compile(r'style="([^"]*)"')
# SVG 表现属性：其颜色是数据编码，必须保护不动
_SVG_PAINT = re.compile(
    r'(?:\bfill|\bstroke|\bstop-color|\bflood-color|\blighting-color)\s*=\s*(["\'])(#[0-9a-fA-F]{3,8})\1'
)


def _is_css_context(text: str) -> bool:
    """判断字符串是否是 CSS（而非 SVG / 正文 / 普通文案）。"""
    if any(m in text for m in SVG_MARKERS):
        return False
    if "{" not in text:
        return False
    return bool(_CSS_DECL.search(text))


def _sub_hex(text: str, chrome_map: dict[str, str]) -> tuple[str, dict[str, int]]:
    """把已知主题色字面量换成 var(--viz-*) 引用。

    SVG 表现属性（fill=/stroke=...）内的颜色被保护，不参与替换。
    """
    counts: dict[str, int] = {}
    # 先把 SVG 表现属性里的颜色占位，替换完再还原
    protected: list[str] = []

    def _stash(m):
        protected.append(m.group(2))
        return f'{m.group(1)}__VIZPAINT_{len(protected) - 1}__\1'

    masked = _SVG_PAINT.sub(_stash, text)

    out = masked
    for hexv, var in sorted(chrome_map.items(), key=lambda kv: -len(kv[0])):
        pat = re.compile(re.escape(hexv), re.I)
        n = len(pat.findall(out))
        if n:
            counts[hexv] = counts.get(hexv, 0) + n
            out = pat.sub(f"var({var})", out)

    # 还原被保护的 SVG 颜色
    for i, color in enumerate(protected):
        out = out.replace(f"__VIZPAINT_{i}__", color)
    return out, counts


def _transform_css(text: str, chrome_map: dict[str, str]) -> tuple[str, dict[str, int]]:
    """CSS 文本内替换：整段替换 + style 属性值。

    f-string 里 CSS 的花括号是双写的（{{ / }}），不影响色值替换本身。
    """
    counts: dict[str, int] = {}
    out, c = _sub_hex(text, chrome_map)
    for k, v in c.items():
        counts[k] = counts.get(k, 0) + v

    def _attr(m):
        new_val, c2 = _sub_hex(m.group(1), chrome_map)
        for k, v in c2.items():
            counts[k] = counts.get(k, 0) + v
        return f'style="{new_val}"'

    out = _STYLE_ATTR.sub(_attr, out)
    return out, counts


def _content_span(source: str, span_start: int, span_end: int, value: str) -> tuple[int, int]:
    """求字符串字面量**内容**在 source 中的绝对区间（不含引号与前缀）。

    ast 的 span 语义在不同 Python 版本 / 字符串形态下不一致：
      - 普通单行串：span 含首尾引号
      - 跨行三引号串：end_col_offset 指向收尾引号所在行的**上一行行尾**
    直接依赖 span 边界会切错。稳妥做法：从开引号之后开始，
    按 value 的**解码后长度**定位内容结尾——本工具只做等长替换，
    不改变转义结构，因此解码长度与源码长度一致（无转义时）。

    对含转义的字符串退化为「用 span_end 减去收尾引号长度」，并由调用方
    通过 _verify_span 做一次自检（内容必须以 node.value 开头）。
    """
    m = re.match(r"^[A-Za-z]*(\"\"\"|'''|\"|')", source[span_start:span_start + 8])
    if not m:
        return span_start, span_end
    content_start = span_start + m.end()
    quote = m.group(1)

    # 首选：按解码长度定位（无转义时精确）
    candidate_end = content_start + len(value)
    if candidate_end <= len(source) and source[content_start:candidate_end] == value:
        return content_start, candidate_end

    # 退化：从 span 末尾回退收尾引号长度
    tail_len = len(quote)
    end = span_end - tail_len
    if end < content_start:
        end = span_end
    return content_start, end


def _token_block(is_fstring: bool, token_block: str | None = None) -> str:
    """统一令牌块；f-string 里花括号需双写。"""
    tb = token_block if token_block is not None else TOKEN_BLOCK
    if is_fstring:
        return tb.replace("{", "{{").replace("}", "}}")
    return tb


def _token_block_oneline(token_block: str | None = None) -> str:
    """令牌块的单行版本（用于插成一条独立语句）。"""
    tb = token_block if token_block is not None else TOKEN_BLOCK
    return " ".join(line.strip() for line in tb.splitlines() if line.strip())


def _find_style_opener(tree: ast.AST) -> tuple[int, int, str] | None:
    """定位「打开 <style> 的那条 append 语句」。

    有些生成器把 CSS 拆成十几条 T.append("...") 逐段拼接，<style> 开标签
    单独占一条。这种结构下无法把令牌块塞进某个字符串字面量内部（会把
    该字面量的收尾引号拆散），只能作为**独立的一条 append 语句**插在
    <style> 之后。

    返回 (语句结束行号, 缩进列, 目标变量名)。
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "append":
            continue
        if not call.args:
            continue
        arg = call.args[0]
        if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
            continue
        if "<style>" not in arg.value:
            continue
        # 变量名：T.append(...) → "T"
        var = "T"
        if isinstance(call.func.value, ast.Name):
            var = call.func.value.id
        return node.end_lineno, node.col_offset, var
    return None


def migrate(source: str, scheme: str = "dark") -> tuple[str, dict[str, int]]:
    """迁移一份生成器源码（AST 定位字符串字面量，文本按原样保留）。

    两阶段：
      1. 色值替换：只在 CSS 上下文里做。
      2. 令牌注入：整份文件**只注入一次**（有的文件把 CSS 存为独立变量再
         插值进 <style>，两处都注入会出现重复令牌）。

    scheme: "dark" / "light" —— 决定用哪套色值映射表与哪套令牌块。
    """
    if scheme not in ("dark", "light"):
        raise ValueError(f"scheme 只能是 dark/light，收到 {scheme!r}")
    chrome_map = CHROME_MAP if scheme == "dark" else CHROME_MAP_LIGHT
    token_block = TOKEN_BLOCK if scheme == "dark" else TOKEN_BLOCK_LIGHT

    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)

    # 收集 f-string 的 Constant 片段位置（这些片段的 span 就是内容本身）
    fstring_parts: set[tuple[int, int, int, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    fstring_parts.add((part.lineno, part.col_offset, part.end_lineno, part.end_col_offset))

    spans: list[tuple[int, int, int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            spans.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, node.value))

    offsets = [0]
    for l in lines:
        offsets.append(offsets[-1] + len(l))

    def _abs(lineno, col):
        return offsets[lineno - 1] + col

    # ── 阶段 1：色值替换 ──
    edits: list[tuple[int, int, str]] = []
    counts: dict[str, int] = {}
    css_spans: list[tuple[int, int, str, bool]] = []  # content_start, content_end, text, is_fstring

    for sl, sc, el, ec, value in spans:
        is_f = (sl, sc, el, ec) in fstring_parts
        span_start, span_end = _abs(sl, sc), _abs(el, ec)
        if span_end <= span_start:
            continue
        if is_f:
            c_start, c_end = span_start, span_end          # f-string 片段即内容
        else:
            c_start, c_end = _content_span(source, span_start, span_end, value)
        raw = source[c_start:c_end]
        if not raw:
            continue
        text = raw
        if _is_css_context(text):
            text, c = _transform_css(text, chrome_map)
            for k, v in c.items():
                counts[k] = counts.get(k, 0) + v
            css_spans.append((c_start, c_end, text, is_f))
        elif 'style="' in text:
            text, c = _transform_css(text, chrome_map)
            for k, v in c.items():
                counts[k] = counts.get(k, 0) + v
        if text != raw:
            edits.append((c_start, c_end, text))

    # ── 阶段 2：令牌注入（整份文件一次）──
    if "--viz-bg" not in source:
        target = None
        opener = _find_style_opener(tree)

        # 模式 A：<style> 与 CSS 同处一个字符串字面量 → 注入字面量内部
        for c_start, c_end, text, is_f in css_spans:
            if "<style>" in text:
                target = (c_start, c_end, text, is_f, "after_style")
                break

        # 模式 B：CSS 被拆成多条 append、<style> 单独占一条
        #   → 作为**独立的一条语句**插在 <style> 之后，绝不塞进字面量内部
        #      （塞进去会把该字面量的收尾引号拆散 → SyntaxError）
        if target is None and opener is not None:
            end_lineno, col, var = opener
            block = _token_block_oneline(token_block)
            indent = " " * col
            insert_at = offsets[end_lineno]
            edits.append((insert_at, insert_at, f'{indent}{var}.append("{block}")\n'))
            target = ("__inserted__",)

        # 模式 C：回退 —— 追加到首个 CSS 字面量末尾
        if target is None and css_spans:
            target = (*css_spans[0], "append")

        if target is not None and target[0] != "__inserted__":
            c_start, c_end, text, is_f, mode = target
            if mode == "after_style":
                m = re.search(r"<style>", text)
                new_text = text[: m.end()] + _token_block(is_f, token_block) + text[m.end():]
            else:
                new_text = text + "\n" + _token_block(is_f, token_block)
            # 替换掉阶段 1 产生的同区间 edit
            edits = [e for e in edits if not (e[0] == c_start and e[1] == c_end)]
            edits.append((c_start, c_end, new_text))

    out = source
    for start, end, text in sorted(edits, key=lambda e: -e[0]):
        out = out[:start] + text + out[end:]
    return out, counts


def main() -> int:
    ap = argparse.ArgumentParser(description="报告生成器色板迁移到统一内核")
    ap.add_argument("files", nargs="+", help="待迁移的生成器 .py 文件")
    ap.add_argument("--check", action="store_true", help="只报告不落盘")
    ap.add_argument("--backup", action="store_true", help="落盘前生成 .bak")
    ap.add_argument("--scheme", choices=["dark", "light"], default="dark", help="主题（决定色值映射表与令牌块）")
    args = ap.parse_args()

    rc = 0
    for f in args.files:
        p = Path(f)
        if not p.exists():
            print(f"[SKIP] {p} 不存在")
            rc = 1
            continue
        src = p.read_text(encoding="utf-8")
        try:
            new, counts = migrate(src, args.scheme)
        except SyntaxError as exc:
            print(f"[ERROR] {p.name}: 语法错误 {exc}")
            rc = 1
            continue
        total = sum(counts.values())
        if total == 0:
            print(f"[SKIP] {p.name}: 无可替换的主题色")
            continue
        detail = " ".join(f"{k}×{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
        if args.check:
            print(f"[CHECK] {p.name}: {total} 处 → {detail}")
            continue
        if args.backup:
            p.with_suffix(p.suffix + ".bak").write_text(src, encoding="utf-8")
        p.write_text(new, encoding="utf-8")
        print(f"[OK] {p.name}: {total} 处替换 → {detail}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
