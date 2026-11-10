#!/usr/bin/env python3
"""viz.base — 统一 HTML 页面骨架与小组件（纯标准库、零 CDN）。

page() 返回一个自包含 HTML 文档：单一 <style>（引用 viz.theme 的 CSS 变量）、
lang="zh-CN"、meta viewport、强制 5 项元信息、SVG 无障碍标注、@media 响应式，
以及 interactive=True 时内联的原生 JS（表格排序 / 文本筛选 / tooltip）。
"""
from __future__ import annotations

import html
import re
from datetime import datetime

try:  # 作为包导入: import viz.base / from viz import base
    from . import theme as _theme
except ImportError:  # 直接运行: python viz/base.py
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    import viz.theme as _theme

_META_KEYS = ("生成时间", "数据源", "口径", "快照版本", "行数")


def esc(v):
    """HTML 转义（含引号），用于所有动态文本/属性，避免 XSS。"""
    return html.escape(str(v), quote=True)


def _is_num(v) -> bool:
    """判断单元格是否为数值（数值列用等宽字体，便于对齐扫读）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---- 单一 <style> 内的基础样式（颜色全部走 :root 变量） ---------------------
_CSS_BASE = """
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font-family: var(--font-sans); line-height: 1.55; }
.viz-page { max-width: 1180px; margin: 0 auto; padding: 24px; }
.viz-head h1 { font-size: 1.6rem; margin: 0 0 12px; }
.viz-meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; margin-bottom: 20px; }
.viz-meta-item { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 8px 12px; }
.viz-meta-k { display: block; font-size: .72rem; color: var(--muted); letter-spacing: .04em; }
.viz-meta-v { font-family: var(--font-mono); font-size: .9rem; }
.viz-main { display: grid; gap: var(--gap); }
.viz-kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: var(--gap); }
.viz-kpi { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; }
.viz-kpi-value { font-size: 1.7rem; font-weight: 700; }
.viz-kpi-label { color: var(--muted); font-size: .82rem; }
.viz-kpi-delta { font-family: var(--font-mono); font-size: .8rem; margin-left: 6px; }
.viz-card { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; }
.viz-card h2 { font-size: 1.05rem; margin: 0 0 12px; }
.viz-card-foot { margin-top: 10px; color: var(--muted); font-size: .78rem; }
.viz-filter { width: 100%; max-width: 320px; margin-bottom: 10px; padding: 8px 10px; background: var(--bg); color: var(--fg); border: 1px solid var(--border); border-radius: 8px; }
table[data-sortable] { border-collapse: collapse; width: 100%; }
table[data-sortable] th, table[data-sortable] td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); }
table[data-sortable] th { color: var(--muted); user-select: none; }
table[data-sortable] th:hover { color: var(--accent); }
table[data-sortable] tbody tr:hover { background: var(--bg); }
svg[role="img"] { max-width: 100%; height: auto; }
.viz-axis { stroke: var(--muted); stroke-width: 1; }
.viz-axis-label, .viz-legend-label { fill: var(--muted); font-size: 12px; font-family: var(--font-sans); }
.viz-tooltip { position: absolute; display: none; z-index: 99; pointer-events: none; background: var(--fg); color: var(--bg); padding: 6px 10px; border-radius: 6px; font-size: .78rem; box-shadow: 0 4px 14px rgba(0,0,0,.35); }
.viz-foot { margin-top: 24px; color: var(--muted); font-size: .75rem; text-align: center; }
.viz-grid { display: grid; gap: var(--gap); grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
.viz-grid-2 { display: grid; gap: var(--gap); grid-template-columns: repeat(2, 1fr); }
.viz-section { margin-bottom: var(--gap); }
.viz-section > h2 { display: flex; align-items: center; gap: 10px; padding-bottom: 8px; border-bottom: 2px solid var(--accent); margin-bottom: 14px; font-size: 1.05rem; }
.viz-badge { display: inline-block; padding: 2px 8px; border-radius: 9999px; font-size: .72rem; font-weight: 600; background: var(--panel); border: 1px solid var(--border); color: var(--muted); }
.viz-badge-pos { color: var(--sports-positive); border-color: var(--sports-positive); }
.viz-badge-neg { color: var(--sports-negative); border-color: var(--sports-negative); }
.viz-note { color: var(--muted); font-size: .8rem; margin-top: 8px; }
.viz-num { font-family: var(--font-mono); }
@media (max-width: 900px) { .viz-grid-2 { grid-template-columns: 1fr; } }
@media (max-width: 720px) {
  .viz-page { padding: 12px; }
  .viz-head h1 { font-size: 1.25rem; }
  .viz-meta { grid-template-columns: repeat(2, 1fr); }
  .viz-kpi-value { font-size: 1.3rem; }
  table[data-sortable] th, table[data-sortable] td { padding: 6px; font-size: .82rem; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
"""

# ---- 交互 JS：表格排序 / 文本筛选 / tooltip（约 40-60 行，零 CDN） ----------
_JS = """
(function () {
  var filter = document.querySelector("[data-viz-filter]");
  if (filter) filter.addEventListener("input", function () {
    var term = this.value.trim().toLowerCase();
    document.querySelectorAll("[data-filter-row]").forEach(function (row) {
      row.style.display = row.textContent.toLowerCase().indexOf(term) !== -1 ? "" : "none";
    });
  });
  document.querySelectorAll("table[data-sortable]").forEach(function (table) {
    var body = table.tBodies[0];
    if (!body) return;
    Array.prototype.forEach.call(table.querySelectorAll("thead th"), function (th, col) {
      th.style.cursor = "pointer";
      th.addEventListener("click", function () {
        var asc = th.getAttribute("data-asc") !== "1";
        Array.prototype.slice.call(body.rows).sort(function (a, b) {
          var x = a.cells[col].textContent.trim();
          var y = b.cells[col].textContent.trim();
          var nx = parseFloat(x.replace(/[,%]/g, ""));
          var ny = parseFloat(y.replace(/[,%]/g, ""));
          var cmp = (isNaN(nx) || isNaN(ny)) ? x.localeCompare(y, "zh-CN") : nx - ny;
          return asc ? cmp : -cmp;
        }).forEach(function (row) { body.appendChild(row); });
        th.setAttribute("data-asc", asc ? "1" : "0");
      });
    });
  });
  var tip = document.createElement("div");
  tip.className = "viz-tooltip";
  tip.setAttribute("role", "tooltip");
  document.body.appendChild(tip);
  document.addEventListener("mouseover", function (e) {
    var el = e.target.closest && e.target.closest("[data-tip]");
    if (el) { tip.textContent = el.getAttribute("data-tip"); tip.style.display = "block"; }
  });
  document.addEventListener("mousemove", function (e) {
    if (tip.style.display === "block") {
      tip.style.left = (e.pageX + 14) + "px";
      tip.style.top = (e.pageY + 14) + "px";
    }
  });
  document.addEventListener("mouseout", function (e) {
    if (e.target.closest && e.target.closest("[data-tip]")) tip.style.display = "none";
  });
})();
"""

_SVG_TAG = re.compile(r"<svg\b[^>]*>", re.I)
_ARIA = re.compile(r'aria-label="([^"]*)"')


def _ensure_svg_a11y(fragment):
    """保证每个 <svg> 容器都带 role="img" 与 aria-label（幂等）。"""
    def repl(m):
        tag = m.group(0)
        am = _ARIA.search(tag)
        has_role = 'role="img"' in tag
        if has_role and am:
            return tag
        core = tag[:-1].rstrip()
        if core.endswith("/"):
            core = core[:-1].rstrip()
        if not has_role:
            core += ' role="img"'
        if not am:
            core += f' aria-label="{esc("图表")}"'
        return core + ">"

    return _SVG_TAG.sub(repl, fragment)


def _meta_html(meta):
    """强制输出 5 项元信息（缺失项自动补默认值），并保留调用方额外键值。"""
    m = dict(meta or {})
    m.setdefault("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    for key in _META_KEYS:
        m.setdefault(key, "—")
    pairs = [(k, m[k]) for k in _META_KEYS]
    pairs += [(k, v) for k, v in m.items() if k not in _META_KEYS]
    items = "".join(
        f'<div class="viz-meta-item"><span class="viz-meta-k">{esc(k)}</span>'
        f'<span class="viz-meta-v">{esc(v)}</span></div>'
        for k, v in pairs
    )
    return f'<div class="viz-meta" role="group" aria-label="报告元信息">{items}</div>'


def page(title, sections, meta=None, theme="dark", interactive=True):
    """返回完整 HTML 字符串。

    title       : 页面标题
    sections    : HTML 片段（字符串或可迭代）；其中的 <svg> 会自动补无障碍标注
    meta        : 元信息字典；无论如何都会输出 生成时间/数据源/口径/快照版本/行数
    theme       : "dark"（默认）或 "light"，决定引用哪套 :root CSS 变量
    interactive : True 时内联原生 JS（表格排序 / 文本筛选 / tooltip）
    """
    css_vars = _theme.CSS_VARS_LIGHT if theme == "light" else _theme.CSS_VARS_DARK
    if isinstance(sections, str):
        sections = [sections]
    body = _ensure_svg_a11y("".join(str(s) for s in (sections or [])))
    script = "<script>\n" + _JS + "\n</script>" if interactive else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
{css_vars}
{_CSS_BASE}
</style>
</head>
<body>
<div class="viz-page">
<header class="viz-head"><h1>{esc(title)}</h1>{_meta_html(meta)}</header>
<main class="viz-main">
{body}
</main>
<footer class="viz-foot">由 viz 内核生成 · 单一色板 / 零 CDN</footer>
</div>
{script}
</body>
</html>"""


def table(headers, rows, align=None, html_cells=False):
    """可排序、可筛选的数据表；rows 为可迭代的行（每个元素是一行单元格）。

    align : 每列对齐方式（"left" / "right" / "center"），缺省按值类型自动判断：
            数值列右对齐并使用等宽字体，便于扫读与排序。
    html_cells : True 时单元格内容**不转义**（允许 <span> 着色等）。
                 仅在内容由本进程生成时开启；外部数据务必保持 False。
    """
    if align is None:
        align = []
        for ci in range(len(headers)):
            col = [r[ci] for r in rows if ci < len(r)]
            align.append("right" if col and all(_is_num(v) for v in col) else "left")
    ths = "".join(
        f'<th scope="col" style="text-align:{align[i] if i < len(align) else "left"}" '
        f'data-tip="点击排序：{esc(h)}">{esc(h)}</th>'
        for i, h in enumerate(headers)
    )

    def _cell(c, i):
        a = align[i] if i < len(align) else "left"
        cls = ' class="viz-num"' if _is_num(c) else ""
        text = str(c) if c is not None else "—"
        if not html_cells:
            text = esc(text)
        return f'<td style="text-align:{a}"{cls}>{text}</td>'

    trs = "".join(
        "<tr data-filter-row>" + "".join(_cell(c, i) for i, c in enumerate(row)) + "</tr>"
        for row in rows
    )
    return (
        '<div class="viz-table-wrap">'
        '<input class="viz-filter" data-viz-filter type="search" '
        'placeholder="筛选表格…" aria-label="表格筛选">'
        f'<table data-sortable aria-label="数据表"><thead><tr>{ths}</tr></thead>'
        f'<tbody>{trs}</tbody></table></div>'
    )


def card(title, body, foot=None):
    """卡片容器。body 为已生成的 HTML 片段（由调用方负责，不再转义）。"""
    foot_html = f'<div class="viz-card-foot">{esc(foot)}</div>' if foot else ""
    return (
        f'<section class="viz-card" role="group" aria-label="{esc(title)}">'
        f'<h2>{esc(title)}</h2><div class="viz-card-body">{body}</div>{foot_html}</section>'
    )


def kpi(label, value, delta=None, tone=None):
    """单个 KPI 指标。tone='up'/'down' 用 FINANCE 语义色（涨红跌绿）。"""
    delta_html = ""
    if delta is not None:
        color = {"up": _theme.FINANCE["up"], "down": _theme.FINANCE["down"]}.get(tone)
        style = f' style="color:{color}"' if color else ""
        delta_html = f'<span class="viz-kpi-delta"{style}>{esc(delta)}</span>'
    return (
        f'<div class="viz-kpi" role="group" aria-label="{esc(label)}：{esc(value)}">'
        f'<div class="viz-kpi-value" data-tip="{esc(label)}">{esc(value)}{delta_html}</div>'
        f'<div class="viz-kpi-label">{esc(label)}</div></div>'
    )


def kpi_row(items):
    """KPI 指标行。items: [(label, value, delta, tone), ...] 或 [(label, value), ...]。"""
    cards = []
    for it in items:
        if len(it) == 2:
            cards.append(kpi(it[0], it[1]))
        else:
            cards.append(kpi(it[0], it[1], it[2], it[3] if len(it) > 3 else None))
    return f'<div class="viz-kpi-row">{"".join(cards)}</div>'


def grid(*cards, columns=None):
    """网格布局。columns=None 时按内容自适应，否则指定 2 / 3 列。"""
    cls = "viz-grid" if columns is None else f"viz-grid viz-grid-{columns}"
    return f'<div class="{cls}">{"".join(cards)}</div>'


def section(title, body, subtitle=None):
    """带标题的区块容器（标题下有 accent 分隔线）。"""
    sub = f'<div class="viz-note">{esc(subtitle)}</div>' if subtitle else ""
    return (
        f'<section class="viz-section" role="group" aria-label="{esc(title)}">'
        f'<h2>{esc(title)}</h2>{sub}{body}</section>'
    )


def badge(text, tone=None):
    """徽章标签。tone='pos' / 'neg' 分别使用正/负语义色。"""
    cls = {"pos": "viz-badge viz-badge-pos", "neg": "viz-badge viz-badge-neg"}.get(
        tone, "viz-badge"
    )
    return f'<span class="{cls}">{esc(text)}</span>'


def note(text):
    """小字注释（口径说明、单位提示等）。"""
    return f'<div class="viz-note">{esc(text)}</div>'


def chart(title, svg_content, *, subtitle=None, foot=None, width=760, height=360):
    """图表容器：标题 + 响应式 SVG + 可选副标题/脚注。

    svg_content 必须是 viz.svg / viz.charts 生成的片段；本函数只负责包裹，
    不做二次转义（图表片段内部已自行转义）。
    """
    sub = f'<div class="viz-note">{esc(subtitle)}</div>' if subtitle else ""
    foot_html = f'<div class="viz-card-foot">{esc(foot)}</div>' if foot else ""
    svg = (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{esc(title)}" style="width:100%; height:auto; display:block;">'
        f"{svg_content}</svg>"
    )
    return (
        f'<section class="viz-card" role="group" aria-label="{esc(title)}">'
        f'<h2>{esc(title)}</h2>{sub}{svg}{foot_html}</section>'
    )


if __name__ == "__main__":
    from pathlib import Path

    try:
        from . import svg as _svg
    except ImportError:
        import viz.svg as _svg

    demo_svg = _svg.svg_frame(
        520, 260, "示例气泡图", "演示统一内核输出的带无障碍标注的 SVG",
        content="".join([
            _svg.axes("出手数", "命中率"),
            _svg.bubble(90, 180, 26, _theme.SPORTS["made"], "球员A：命中率 48%"),
            _svg.bubble(220, 120, 34, _theme.SPORTS["win"], "球员B：命中率 55%"),
            _svg.bubble(360, 70, 20, _theme.FINANCE["up"], "球员C：命中率 41%"),
            _svg.legend([("命中", _theme.SPORTS["made"]), ("胜负", _theme.SPORTS["win"])]),
        ]),
    )
    sections = [
        '<div class="viz-kpi-row">' + "".join([
            kpi("总出手", "1,284", "+8.2%", "up"),
            kpi("命中率", "47.6%", "-1.1%", "down"),
            kpi("快照行数", "30"),
        ]) + "</div>",
        card("投篮分布气泡图", demo_svg, foot="数据源：demo（静态样例，非真实 DB）"),
        card("球员明细", table(
            ["球员", "球队", "出手", "命中率"],
            [["SGA", "OKC", 312, "53.2%"],
             ["Jokic", "DEN", 288, "58.1%"],
             ["Tatum", "BOS", 301, "46.7%"]],
        )),
    ]
    demo = page(
        "NBA 可视化内核 Demo",
        sections,
        meta={"数据源": "viz/base.py demo", "口径": "样例数据", "快照版本": "demo-1", "行数": 3},
        theme="dark",
        interactive=True,
    )
    Path("/tmp/viz_demo.html").write_text(demo, encoding="utf-8")
    print(f"Wrote /tmp/viz_demo.html ({len(demo)} bytes)")

    import json

    tokens = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "css_vars_dark_keys": re.findall(r"(--[A-Za-z0-9-]+)\s*:", _theme.CSS_VARS_DARK),
        "css_vars_dark": dict(re.findall(r"(--[A-Za-z0-9-]+)\s*:\s*([^;]+);", _theme.CSS_VARS_DARK)),
        "css_vars_light_keys": re.findall(r"(--[A-Za-z0-9-]+)\s*:", _theme.CSS_VARS_LIGHT),
        "sports": dict(_theme.SPORTS),
        "finance": dict(_theme.FINANCE),
        "diverging": dict(_theme.DIVERGING),
        "categorical": list(_theme.CATEGORICAL),
        "spacing": dict(_theme.SPACING),
        "typo": dict(_theme.TYPO),
        "radius": dict(_theme.RADIUS),
        "shadow": dict(_theme.SHADOW),
        "team_colors_count": len(_theme.TEAM_COLORS),
        "team_colors": dict(_theme.TEAM_COLORS),
    }
    tokens_path = Path(__file__).with_name("theme_tokens.json")
    tokens_path.write_text(json.dumps(tokens, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {tokens_path} ({len(tokens['css_vars_dark_keys'])} css vars, "
          f"{tokens['team_colors_count']} teams)")


__all__ = [
    "page", "table", "card", "kpi", "kpi_row", "grid", "section",
    "badge", "note", "chart", "esc",
]
