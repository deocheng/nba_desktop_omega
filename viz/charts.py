#!/usr/bin/env python3
"""viz.charts — 高层图表原语（纯标准库、零 CDN、零第三方依赖）。

设计原则：
- **颜色一律走语义 CSS 变量**（var(--text) / var(--border) / var(--diverging-pos) ...），
  绝不写死 hex。这样同一份代码在 light / dark 两套主题下都正确。
- 每个数据标记都带 role="img" + aria-label + <title>，可被 viz.base 的
  原生 tooltip JS 消费（data-tip）。
- 输入为纯 Python 元组/字典，输出为 SVG 字符串片段；组合由调用方用 svg_frame 包裹。

原语清单：
    rank_bars        横向排名条（数值标签在条外）
    diverging_bars   发散条（中轴左右分向，用于 +/- 偏差）
    stacked_bars     堆叠横向条（多段构成）
    lollipop         棒棒糖（细杆 + 圆点，比条形更省墨）
    scatter          散点（可选网格 + 轴 + 标签）
    action_bars      分组动作条（进攻动作类型等）
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional, Sequence

from . import theme as _theme

# ---- 颜色语义别名（与 viz.theme.CSS_VARS_* 中的变量一一对应）----------------
C_TEXT = "var(--text)"
C_MUTED = "var(--text-muted)"
C_BORDER = "var(--border)"
C_POS = "var(--diverging-pos)"
C_NEG = "var(--diverging-neg)"
C_MID = "var(--diverging-mid)"
F_SANS = "var(--font-sans)"
F_MONO = "var(--font-mono)"
F_SM = "var(--font-size-sm)"
F_BASE = "var(--font-size-base)"


def _esc(v):
    import html

    return html.escape(str(v), quote=True)


def _fmt(v: float, digits: int = 1) -> str:
    """数值格式化：整数去掉小数点，其余保留 digits 位。"""
    if v is None:
        return "—"
    if isinstance(v, int) or float(v).is_integer():
        return str(int(v))
    return f"{v:.{digits}f}"


def _linear(domain: tuple[float, float], rng: tuple[float, float]) -> Callable[[float], float]:
    """线性比例尺（domain → range），零跨度时退化到 range 起点。"""
    d0, d1 = float(domain[0]), float(domain[1])
    r0, r1 = float(rng[0]), float(rng[1])
    if d1 == d0:
        return lambda _x: r0
    k = (r1 - r0) / (d1 - d0)
    return lambda x: r0 + (float(x) - d0) * k


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    """在 [lo, hi] 上取 n+1 个等距刻度（含端点）。"""
    if hi == lo:
        return [lo]
    step = (hi - lo) / n
    return [lo + i * step for i in range(n + 1)]


def _label(x: float, y: float, content: str, *, anchor: str = "middle",
           fill: str = C_TEXT, size: str = F_SM, mono: bool = False,
           weight: str = "") -> str:
    """文本节点（统一字体与填充，锚点可配）。"""
    family = F_MONO if mono else F_SANS
    w = f' font-weight="{weight}"' if weight else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" fill="{fill}" '
        f'font-size="{size}" font-family="{family}"{w}>{_esc(content)}</text>'
    )


def _bar_rows(n: int, y: float, height: float, gap_ratio: float = 0.32):
    """计算 n 行条形的位置：返回 [(row_y, bar_h), ...]。"""
    if n <= 0:
        return []
    slot = height / n
    bar_h = slot / (1 + gap_ratio)
    return [(y + i * slot + slot * gap_ratio / 2, bar_h) for i in range(n)]


def rank_bars(
    data: Sequence[tuple[str, float, str]],
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    max_value: Optional[float] = None,
    value_format: Optional[Callable[[float], str]] = None,
    label_width: float = 92,
    show_values: bool = True,
) -> str:
    """横向排名条。

    data: [(label, value, color), ...]，按传入顺序即排名顺序。
    color 建议传 CATEGORICAL 中的色值或语义别名（var(--...)）。
    """
    if not data:
        return ""
    fmt = value_format or (lambda v: _fmt(v))
    max_v = max_value if max_value is not None else max((v for _, v, _ in data), default=0)
    if max_v == 0:
        max_v = 1
    plot_x = x + label_width
    plot_w = max(width - label_width - 56, 10)
    scale = _linear((0, max_v), (0, plot_w))

    parts = []
    for (label, value, color), (row_y, bar_h) in zip(data, _bar_rows(len(data), y, height)):
        bw = max(scale(value), 0)
        tip = f"{label}：{fmt(value)}"
        parts.append(
            f'<g role="img" aria-label="{_esc(tip)}" data-tip="{_esc(tip)}">'
            f'<rect x="{plot_x:.1f}" y="{row_y:.1f}" width="{bw:.1f}" height="{bar_h:.1f}" '
            f'fill="{_esc(color)}" rx="2"><title>{_esc(tip)}</title></rect>'
            f'</g>'
        )
        parts.append(_label(x + label_width - 8, row_y + bar_h / 2 + 4, label,
                            anchor="end", fill=C_TEXT, size=F_BASE))
        if show_values:
            parts.append(_label(plot_x + bw + 6, row_y + bar_h / 2 + 4, fmt(value),
                                anchor="start", fill=C_MUTED, size=F_SM, mono=True))
    return "\n".join(parts)


def diverging_bars(
    data: Sequence[tuple[str, float]],
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    max_abs: Optional[float] = None,
    label_width: float = 92,
    center_label: str = "0",
) -> str:
    """发散条：正值向右、负值向左，共享中轴。

    data: [(label, value), ...]，value 可正可负。
    """
    if not data:
        return ""
    max_v = max_abs if max_abs is not None else max((abs(v) for _, v in data), default=0)
    if max_v == 0:
        max_v = 1
    label_w = label_width
    plot_x = x + label_w
    plot_w = max(width - label_w, 10)
    center = plot_x + plot_w / 2
    half = plot_w / 2 - 6
    scale = _linear((0, max_v), (0, half))

    parts = [
        f'<line x1="{center:.1f}" y1="{y - 10:.1f}" x2="{center:.1f}" y2="{y + height:.1f}" '
        f'stroke="{C_BORDER}" stroke-width="1"/>',
        _label(center, y - 14, center_label, fill=C_MUTED, size=F_SM, mono=True),
    ]
    for (label, value), (row_y, bar_h) in zip(data, _bar_rows(len(data), y, height)):
        color = C_POS if value >= 0 else C_NEG
        bw = max(scale(abs(value)), 0)
        tip = f"{label}：{value:+.1f}"
        if value >= 0:
            bx = center
            tx = center + bw + 6
            anchor = "start"
        else:
            bx = center - bw
            tx = center - bw - 6
            anchor = "end"
        parts.append(
            f'<g role="img" aria-label="{_esc(tip)}" data-tip="{_esc(tip)}">'
            f'<rect x="{bx:.1f}" y="{row_y:.1f}" width="{bw:.1f}" height="{bar_h:.1f}" '
            f'fill="{color}" rx="2"><title>{_esc(tip)}</title></rect>'
            f'</g>'
        )
        parts.append(_label(x + label_w - 8, row_y + bar_h / 2 + 4, label,
                            anchor="end", fill=C_TEXT, size=F_BASE))
        parts.append(_label(tx, row_y + bar_h / 2 + 4, f"{value:+.1f}",
                            anchor=anchor, fill=color, size=F_SM, mono=True))
    return "\n".join(parts)


def stacked_bars(
    data: Sequence[tuple[str, Sequence[tuple[float, str]]]],
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    max_value: Optional[float] = None,
    label_width: float = 92,
    show_total: bool = True,
) -> str:
    """堆叠横向条。

    data: [(label, [(value, color), ...]), ...]
    """
    if not data:
        return ""
    totals = [sum(v for v, _ in segs) for _, segs in data]
    max_v = max_value if max_value is not None else max(totals, default=0)
    if max_v == 0:
        max_v = 1
    plot_x = x + label_width
    plot_w = max(width - label_width - 56, 10)
    scale = _linear((0, max_v), (0, plot_w))

    parts = []
    for (label, segs), (row_y, bar_h), total in zip(data, _bar_rows(len(data), y, height), totals):
        cursor = plot_x
        for value, color in segs:
            if value <= 0:
                continue
            bw = scale(value)
            tip = f"{label}：{_fmt(value)}"
            parts.append(
                f'<g role="img" aria-label="{_esc(tip)}" data-tip="{_esc(tip)}">'
                f'<rect x="{cursor:.1f}" y="{row_y:.1f}" width="{bw:.1f}" height="{bar_h:.1f}" '
                f'fill="{_esc(color)}"><title>{_esc(tip)}</title></rect>'
                f'</g>'
            )
            cursor += bw
        parts.append(_label(x + label_width - 8, row_y + bar_h / 2 + 4, label,
                            anchor="end", fill=C_TEXT, size=F_BASE))
        if show_total:
            parts.append(_label(cursor + 6, row_y + bar_h / 2 + 4, _fmt(total),
                                anchor="start", fill=C_MUTED, size=F_SM, mono=True))
    return "\n".join(parts)


def lollipop(
    data: Sequence[tuple[str, float, str]],
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    max_value: Optional[float] = None,
    label_width: float = 92,
) -> str:
    """棒棒糖图：细杆 + 圆点。同样的数据比条形更省墨，适合排名浏览。"""
    if not data:
        return ""
    max_v = max_value if max_value is not None else max((v for _, v, _ in data), default=0)
    if max_v == 0:
        max_v = 1
    plot_x = x + label_width
    plot_w = max(width - label_width - 56, 10)
    scale = _linear((0, max_v), (0, plot_w))

    parts = []
    for (label, value, color), (row_y, bar_h) in zip(data, _bar_rows(len(data), y, height)):
        mid = row_y + bar_h / 2
        tip = f"{label}：{_fmt(value)}"
        parts.append(
            f'<g role="img" aria-label="{_esc(tip)}" data-tip="{_esc(tip)}">'
            f'<line x1="{plot_x:.1f}" y1="{mid:.1f}" x2="{plot_x + scale(value):.1f}" y2="{mid:.1f}" '
            f'stroke="{_esc(color)}" stroke-width="2" stroke-linecap="round"/>'
            f'<circle cx="{plot_x + scale(value):.1f}" cy="{mid:.1f}" r="{max(bar_h / 2.6, 3):.1f}" '
            f'fill="{_esc(color)}"><title>{_esc(tip)}</title></circle>'
            f'</g>'
        )
        parts.append(_label(x + label_width - 8, mid + 4, label,
                            anchor="end", fill=C_TEXT, size=F_BASE))
        parts.append(_label(plot_x + scale(value) + 8, mid + 4, _fmt(value),
                            anchor="start", fill=C_MUTED, size=F_SM, mono=True))
    return "\n".join(parts)


def scatter(
    data: Sequence[tuple[float, float, str, str]],
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    x_domain: tuple[float, float],
    y_domain: tuple[float, float],
    x_label: str = "",
    y_label: str = "",
    radius: float = 4,
    radius_fn: Optional[Callable[[float, float], float]] = None,
    show_point_labels: bool = True,
    grid: bool = True,
    extra_svg: str = "",
) -> str:
    """散点图（含网格 + 双轴 + 可选点标签）。

    data: [(x_val, y_val, label, color), ...]
    radius_fn : 可选的点半径函数 (x_val, y_val) -> r，用于「大小编码第三变量」
                （如生涯分钟）；给定后 radius 参数被忽略。
    extra_svg  : 额外 SVG 片段（象限线 / 象限标签等），原样插入绘图区。
    """
    if not data:
        return ""
    pad = 46
    plot_x = x + pad
    plot_y = y + 10
    plot_w = max(width - pad - 16, 10)
    plot_h = max(height - pad - 10, 10)
    sx = _linear(x_domain, (0, plot_w))
    sy = _linear(y_domain, (plot_h, 0))  # SVG y 轴向下，故反转

    parts = []
    if grid:
        for t in _ticks(*x_domain):
            gx = plot_x + sx(t)
            parts.append(f'<line x1="{gx:.1f}" y1="{plot_y:.1f}" x2="{gx:.1f}" '
                         f'y2="{plot_y + plot_h:.1f}" stroke="{C_BORDER}" stroke-width="0.5" opacity="0.55"/>')
        for t in _ticks(*y_domain):
            gy = plot_y + sy(t)
            parts.append(f'<line x1="{plot_x:.1f}" y1="{gy:.1f}" x2="{plot_x + plot_w:.1f}" '
                         f'y2="{gy:.1f}" stroke="{C_BORDER}" stroke-width="0.5" opacity="0.55"/>')
        for t in _ticks(*x_domain):
            parts.append(_label(plot_x + sx(t), plot_y + plot_h + 16, _fmt(t),
                                fill=C_MUTED, size=F_SM, mono=True))
        for t in _ticks(*y_domain):
            parts.append(_label(plot_x - 8, plot_y + sy(t) + 4, _fmt(t),
                                anchor="end", fill=C_MUTED, size=F_SM, mono=True))

    parts.append(f'<line x1="{plot_x:.1f}" y1="{plot_y + plot_h:.1f}" x2="{plot_x + plot_w:.1f}" '
                 f'y2="{plot_y + plot_h:.1f}" stroke="{C_MUTED}" stroke-width="1"/>')
    parts.append(f'<line x1="{plot_x:.1f}" y1="{plot_y:.1f}" x2="{plot_x:.1f}" '
                 f'y2="{plot_y + plot_h:.1f}" stroke="{C_MUTED}" stroke-width="1"/>')
    if x_label:
        parts.append(_label(plot_x + plot_w / 2, plot_y + plot_h + 34, x_label,
                            fill=C_TEXT, size=F_SM, weight="600"))
    if y_label:
        parts.append(
            f'<text x="14" y="{plot_y + plot_h / 2:.1f}" text-anchor="middle" fill="{C_TEXT}" '
            f'font-size="{F_SM}" font-family="{F_SANS}" font-weight="600" '
            f'transform="rotate(-90 14 {plot_y + plot_h / 2:.1f})">{_esc(y_label)}</text>'
        )

    for x_val, y_val, label, color in data:
        cx = plot_x + sx(x_val)
        cy = plot_y + sy(y_val)
        r = radius_fn(x_val, y_val) if radius_fn else radius
        tip = f"{label}：({_fmt(x_val)}, {_fmt(y_val)})" if label else f"({_fmt(x_val)}, {_fmt(y_val)})"
        parts.append(
            f'<g role="img" aria-label="{_esc(tip)}" data-tip="{_esc(tip)}">'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{_esc(color)}" '
            f'opacity="0.82" stroke="var(--panel)" stroke-width="1"><title>{_esc(tip)}</title></circle>'
            f'</g>'
        )
        if show_point_labels and label:
            parts.append(_label(cx, cy - r - 5, label, fill=C_TEXT, size=F_SM))
    if extra_svg:
        parts.append(extra_svg)
    return "\n".join(parts)


def action_bars(
    data: Sequence[tuple[str, Sequence[tuple[str, float, str]]]],
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    max_value: Optional[float] = None,
    label_width: float = 92,
) -> str:
    """分组动作条（如进攻动作类型占比）。

    data: [(group_label, [(action_label, value, color), ...]), ...]
    """
    if not data:
        return ""
    all_vals = [v for _, acts in data for _, v, _ in acts]
    max_v = max_value if max_value is not None else max(all_vals, default=0)
    if max_v == 0:
        max_v = 1
    plot_x = x + label_width
    plot_w = max(width - label_width - 56, 10)
    scale = _linear((0, max_v), (0, plot_w))
    n_actions = max((len(a) for _, a in data), default=1)
    slot = height / max(len(data), 1)
    bar_h = min(18, slot / max(n_actions, 1) * 0.72)

    parts = []
    for gi, (group, actions) in enumerate(data):
        group_top = y + gi * slot
        parts.append(_label(x + label_width - 8, group_top + bar_h / 2 + 4, group,
                            anchor="end", fill=C_TEXT, size=F_BASE, weight="600"))
        for ai, (act, value, color) in enumerate(actions):
            by = group_top + ai * (bar_h + 3)
            bw = max(scale(value), 0)
            tip = f"{group} · {act}：{_fmt(value)}"
            parts.append(
                f'<g role="img" aria-label="{_esc(tip)}" data-tip="{_esc(tip)}">'
                f'<rect x="{plot_x:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bar_h:.1f}" '
                f'fill="{_esc(color)}" rx="2"><title>{_esc(tip)}</title></rect>'
                f'</g>'
            )
            parts.append(_label(plot_x + 5, by + bar_h / 2 + 3, act,
                                anchor="start", fill="var(--panel)", size=F_SM))
            parts.append(_label(plot_x + bw + 6, by + bar_h / 2 + 3, _fmt(value),
                                anchor="start", fill=C_MUTED, size=F_SM, mono=True))
    return "\n".join(parts)


def categorical_palette(n: int) -> list[str]:
    """取 n 个分类色（循环 CATEGORICAL）。"""
    pal = list(_theme.CATEGORICAL)
    return [pal[i % len(pal)] for i in range(max(n, 0))]


__all__ = [
    "rank_bars", "diverging_bars", "stacked_bars", "lollipop", "scatter",
    "action_bars", "categorical_palette",
]
