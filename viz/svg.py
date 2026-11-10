#!/usr/bin/env python3
"""viz.svg — 统一输出带无障碍标注的 SVG 片段（纯标准库、零 CDN）。

所有片段根元素均带 role="img" 与 aria-label；几何元素带 <title>/data-tip，
可被 viz.base 的原生 tooltip JS 直接消费。
"""
from __future__ import annotations

import html


def _esc(v):
    return html.escape(str(v), quote=True)


def svg_frame(width, height, title, desc, content=""):
    """完整 <svg> 容器：width/height/title/desc（+ 可选内部 content 片段）。"""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(title)}">'
        f'<title>{_esc(title)}</title><desc>{_esc(desc)}</desc>'
        f'{content}</svg>'
    )


def axes(x_label, y_label, width=520, height=260, pad=44):
    """笛卡尔坐标轴 + 轴标签（带 aria-label 的 <g>）。"""
    return (
        f'<g role="img" aria-label="坐标轴：横轴 {_esc(x_label)}，纵轴 {_esc(y_label)}">'
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" class="viz-axis"/>'
        f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height - pad}" class="viz-axis"/>'
        f'<text x="{width / 2}" y="{height - 10}" text-anchor="middle" class="viz-axis-label">{_esc(x_label)}</text>'
        f'<text x="12" y="{pad / 2}" text-anchor="start" class="viz-axis-label">{_esc(y_label)}</text>'
        f'</g>'
    )


def legend(items, x=360, y=24):
    """图例。items: [(label, color), ...]。"""
    rows = "".join(
        f'<rect x="{x}" y="{y + i * 22}" width="12" height="12" rx="2" fill="{_esc(color)}"/>'
        f'<text x="{x + 18}" y="{y + i * 22 + 10}" class="viz-legend-label">{_esc(label)}</text>'
        for i, (label, color) in enumerate(items)
    )
    labels = "、".join(str(label) for label, _ in items)
    return f'<g role="img" aria-label="图例：{_esc(labels)}">{rows}</g>'


def scale_linear(domain, range):
    """线性比例尺，返回可调用的插值函数（类似 d3.scaleLinear）。

    domain/range 均为 (min, max)；返回函数附带 .domain / .range 属性。
    """
    d0, d1 = float(domain[0]), float(domain[1])
    r0, r1 = float(range[0]), float(range[1])

    def scale(x):
        if d1 == d0:
            return r0
        t = (float(x) - d0) / (d1 - d0)
        return r0 + t * (r1 - r0)

    scale.domain = (d0, d1)
    scale.range = (r0, r1)
    return scale


def bubble(cx, cy, r, color, label=""):
    """单个气泡：<circle> + <title>，包在带 aria/data-tip 的 <g> 中。"""
    text = _esc(label or "气泡")
    return (
        f'<g role="img" aria-label="{text}" data-tip="{text}">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{_esc(color)}" opacity="0.85" '
        f'stroke="#ffffff" stroke-opacity="0.35"><title>{text}</title></circle>'
        f'</g>'
    )


__all__ = ["svg_frame", "axes", "legend", "scale_linear", "bubble"]
