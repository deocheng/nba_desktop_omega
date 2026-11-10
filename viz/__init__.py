#!/usr/bin/env python3
"""viz — 全项目唯一可视化内核（纯标准库、零 CDN、零第三方依赖）。

公共 API：
    theme : SPORTS / FINANCE / DIVERGING / CATEGORICAL / TEAM_COLORS /
            SPACING / TYPO / RADIUS / SHADOW / CSS_VARS_DARK / CSS_VARS_LIGHT /
            compat_vars() / hex()
    base  : page() / table() / card() / kpi() / kpi_row() / grid() / section() /
            badge() / note() / chart()
    svg   : svg_frame() / axes() / legend() / scale_linear() / bubble()
    charts: rank_bars() / diverging_bars() / stacked_bars() / lollipop() /
            scatter() / action_bars() / categorical_palette()
    meta  : build_meta() / git_sha() / git_branch() / git_dirty() / lineage()

设计约束（改动前请读）：
1. 本包是**唯一**色板与 CSS 变量来源。新增图表必须复用这里的语义变量，
   不得再自定义 :root 或写死 hex。
2. 所有输出片段必须自带无障碍标注（role="img" / aria-label / <title>）。
3. 颜色走 var(--xxx) 而非具体色值，才能同时适配 light / dark 两套主题。
4. 外部报告生成器若仍自带旧 :root（定义了 --bg/--panel/--txt 等名字），
   用 compat_vars() 取 **--viz-* 前缀** 的令牌块：直接换成 var(--bg) 会
   产出 `--bg: var(--bg)` 自引用，CSS 变量随即失效。
"""
from . import base, charts, meta, svg, theme
from .base import (
    badge,
    card,
    chart,
    grid,
    kpi,
    kpi_row,
    note,
    page,
    section,
    table,
)
from .charts import (
    action_bars,
    categorical_palette,
    diverging_bars,
    lollipop,
    rank_bars,
    scatter,
    stacked_bars,
)
from .meta import (
    build_meta,
    generation_timestamp,
    git_branch,
    git_dirty,
    git_sha,
    lineage,
)
from .svg import axes, bubble, legend, scale_linear, svg_frame
from .theme import (
    CATEGORICAL,
    CSS_VARS_DARK,
    CSS_VARS_LIGHT,
    DIVERGING,
    FINANCE,
    NEUTRALS_DARK,
    NEUTRALS_LIGHT,
    RADIUS,
    SHADOW,
    SPACING,
    SPORTS,
    STATE,
    TEAM_COLORS,
    TYPO,
    compat_vars,
    hex,
)

__all__ = [
    "theme", "svg", "base", "charts", "meta",
    "SPORTS", "FINANCE", "DIVERGING", "CATEGORICAL", "TEAM_COLORS",
    "SPACING", "TYPO", "RADIUS", "SHADOW",
    "NEUTRALS_DARK", "NEUTRALS_LIGHT", "STATE",
    "CSS_VARS_DARK", "CSS_VARS_LIGHT", "compat_vars", "hex",
    "page", "table", "card", "kpi", "kpi_row", "grid", "section",
    "badge", "note", "chart",
    "svg_frame", "axes", "legend", "scale_linear", "bubble",
    "rank_bars", "diverging_bars", "stacked_bars", "lollipop", "scatter",
    "action_bars", "categorical_palette",
    "build_meta", "git_sha", "git_branch", "git_dirty",
    "generation_timestamp", "lineage",
]
