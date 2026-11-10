#!/usr/bin/env python3
"""viz.theme — 全项目单一色板与 CSS 变量来源（纯标准库、零第三方依赖）。

本模块是全仓**唯一**的设计令牌来源。任何报告/图表/前端页面都不得再自行
定义 :root 变量或色值常量——那正是本项目要消灭的「三套互不相认的视觉语言」。

分区：
- SPORTS      : 胜负/正负语义（胜=绿、负=红，国际通用）。
- FINANCE     : 中文语境「涨红跌绿」（与 SPORTS 刻意相反）。
- DIVERGING   : 发散（+/- 双向）编码色。
- CATEGORICAL : 分类数据配色（色觉友好，10 色循环）。
- TEAM_COLORS : NBA 30 队主色，仅用于 UI 框架；数据编码色保持恒定以便跨队对比。
- SPACING / TYPO / RADIUS / SHADOW : 间距、排版、圆角、阴影刻度。
- CSS_VARS_*  : :root 变量字符串，由上述色板生成，供所有报告复用（单一来源）。

契约（frontend/tests/viz_contract.test.js 锁定，勿随意改动）：
- CSS_VARS_DARK 的 --bg 必须为 #0b1220
- FINANCE.up 必须为 #dc2626（涨=红）、FINANCE.down 必须为 #16a34a（跌=绿）
- TEAM_COLORS 必须恰好 30 队
"""
from __future__ import annotations

# ---- 语义色板 --------------------------------------------------------------
SPORTS = {
    "positive": "#16a34a",
    "negative": "#dc2626",
    "win": "#16a34a",
    "loss": "#dc2626",
    "neutral": "#64748b",
    "made": "#2563eb",
    "missed": "#94a3b8",
    "clutch": "#f97316",
    "accent": "#38bdf8",
}

# 中文财经语境：涨=红、跌=绿（与 SPORTS 相反，勿混用）
FINANCE = {
    "up": "#dc2626",
    "down": "#16a34a",
    "flat": "#64748b",
    "positive": "#dc2626",
    "negative": "#16a34a",
}

# 发散编码（负 → 中 → 正），用于 +/− 双向图表
DIVERGING = {
    "negative": "#dc2626",
    "mid": "#94a3b8",
    "positive": "#16a34a",
}

# 分类数据配色：色觉友好（Okabe-Ito 派生），10 色循环。
# 用途：多系列柱/折线/散点着色；语义有别于 SPORTS（不承载胜负含义）。
CATEGORICAL = (
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc949", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
)

# NBA 30 队主色（近似官方值）
TEAM_COLORS = {
    "ATL": "#E03A3E", "BOS": "#007A33", "BKN": "#000000",
    "CHA": "#1D1160", "CHI": "#CE1141", "CLE": "#860038",
    "DAL": "#00538C", "DEN": "#0E2240", "DET": "#C8102E",
    "GSW": "#1D428A", "HOU": "#CE1141", "IND": "#FDBB30",
    "LAC": "#C8102E", "LAL": "#552583", "MEM": "#5D76A9",
    "MIA": "#98002E", "MIL": "#00471B", "MIN": "#0C2340",
    "NOP": "#0C2340", "NYK": "#006BB6", "OKC": "#007AC1",
    "ORL": "#0077C0", "PHI": "#006BB6", "PHX": "#1D1160",
    "POR": "#E03A3E", "SAC": "#5A2D81", "SAS": "#C4CED4",
    "TOR": "#CE1141", "UTA": "#002B5C", "WAS": "#002B5C",
}

class _Frozen(dict):
    """不可变字典：防止调用方在运行时改写色板（色板必须是只读真相）。"""

    def _immutable(self, *a, **k):
        raise TypeError("色板是只读真相，不允许运行时改写")

    __setitem__ = _immutable
    __delitem__ = _immutable
    pop = _immutable
    popitem = _immutable
    clear = _immutable
    update = _immutable
    setdefault = _immutable


# ---- 中性色阶（背景层级 / 边框 / 文本）--------------------------------------
# 单独成表的原因：迁移期的报告生成器需要 --viz-* 前缀的兼容令牌块，
# 若把色值抄进迁移工具，就会出现「两份色值靠人工同步」——正是本项目要
# 消灭的「多套互不相认的视觉语言」。此处是唯一真相，工具只负责消费。
NEUTRALS_DARK = _Frozen({
    "bg": "#0b1220",
    "panel": "#131c2e",
    "surface": "#131c2e",
    "fg": "#e6edf7",
    "muted": "#8aa0bd",
    "faint": "#5d6b7a",
    "border": "#22304a",
})

NEUTRALS_LIGHT = _Frozen({
    "bg": "#f7f9fc",
    "panel": "#ffffff",
    "surface": "#ffffff",
    "fg": "#0f172a",
    "muted": "#5b6b82",
    "faint": "#8a98ab",
    "border": "#d8e0ec",
})

# 语义状态色（与 SPORTS 一致：胜/正=绿、负=红）
STATE = _Frozen({
    "positive": "#16a34a",
    "negative": "#dc2626",
    "warn": "#f6ad55",
})


# ---- 间距刻度（4px 基数）--------------------------------------------------
SPACING = {
    "xs": "4px",
    "sm": "8px",
    "md": "16px",
    "lg": "24px",
    "xl": "32px",
    "xxl": "48px",
}

# ---- 排版刻度 --------------------------------------------------------------
TYPO = {
    "font-sans": "system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    "font-mono": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    "font-size-xs": "11px",
    "font-size-sm": "12px",
    "font-size-base": "14px",
    "font-size-lg": "16px",
    "font-size-xl": "20px",
    "font-size-2xl": "26px",
    "font-weight-medium": "500",
    "font-weight-semibold": "600",
    "font-weight-bold": "700",
    "line-height-tight": "1.25",
    "line-height-normal": "1.55",
}

# ---- 圆角 / 阴影刻度 --------------------------------------------------------
RADIUS = {
    "sm": "4px",
    "md": "8px",
    "lg": "12px",
    "xl": "16px",
    "full": "9999px",
}

SHADOW = {
    "sm": "0 1px 2px rgba(0, 0, 0, 0.28)",
    "md": "0 4px 12px rgba(0, 0, 0, 0.34)",
    "lg": "0 10px 30px rgba(0, 0, 0, 0.42)",
}


def hex(value):
    """把颜色规范为 #rrggbb。

    支持 '#rgb' / '#rrggbb' / (r,g,b) 三元组 / 色板键名
    （SPORTS、FINANCE、DIVERGING 的语义键，TEAM_COLORS 的球队缩写，
    或 CATEGORICAL 中的具体色值，大小写不敏感）。
    """
    if isinstance(value, (tuple, list)) and len(value) == 3:
        return "#" + "".join(f"{max(0, min(255, int(c))):02x}" for c in value)
    if isinstance(value, str):
        v = value.strip()
        if v.startswith("#"):
            if len(v) == 4:
                return "#" + "".join(c * 2 for c in v[1:]).lower()
            if len(v) == 7:
                return v.lower()
        team = v.upper()
        if team in TEAM_COLORS:
            return TEAM_COLORS[team].lower()
        for palette in (SPORTS, FINANCE, DIVERGING):
            if v in palette:
                return palette[v].lower()
            if v.lower() in palette:
                return palette[v.lower()].lower()
        if v in CATEGORICAL:
            return v.lower()
    raise ValueError(f"无法解析颜色: {value!r}")


def _css_vars(n: dict, scheme: str) -> str:
    """由色板生成 :root 变量块，避免各报告硬编码颜色。"""
    lines = [
        ":root {",
        f"  --bg: {n['bg']};",
        f"  --panel: {n['panel']};",
        f"  --fg: {n['fg']};",
        f"  --muted: {n['muted']};",
        f"  --border: {n['border']};",
        f"  --accent: {SPORTS['accent']};",
        f"  --sports-win: {SPORTS['win']};",
        f"  --sports-loss: {SPORTS['loss']};",
        f"  --sports-positive: {SPORTS['positive']};",
        f"  --sports-negative: {SPORTS['negative']};",
        f"  --finance-up: {FINANCE['up']};",
        f"  --finance-down: {FINANCE['down']};",
        f"  --team-okc: {TEAM_COLORS['OKC']};",
        # ---- 语义别名（图表原语统一走这些别名，避免各图表硬编码色名）----
        f"  --text: {n['fg']};",
        f"  --text-muted: {n['muted']};",
        f"  --surface: {n['surface']};",
        f"  --diverging-neg: {DIVERGING['negative']};",
        f"  --diverging-mid: {DIVERGING['mid']};",
        f"  --diverging-pos: {DIVERGING['positive']};",
    ]
    for key, val in SPACING.items():
        lines.append(f"  --space-{key}: {val};")
    for key, val in TYPO.items():
        lines.append(f"  --{key}: {val};")
    for key, val in RADIUS.items():
        lines.append(f"  --radius-{key}: {val};")
    for key, val in SHADOW.items():
        lines.append(f"  --shadow-{key}: {val};")
    lines.extend([
        "  --radius: 10px;",
        "  --gap: 16px;",
        f"  color-scheme: {scheme};",
        "}",
        "",
    ])
    return "\n".join(lines)


CSS_VARS_DARK = _css_vars(NEUTRALS_DARK, "dark")
CSS_VARS_LIGHT = _css_vars(NEUTRALS_LIGHT, "light")


def compat_vars(scheme: str = "dark", prefix: str = "viz") -> str:
    """生成 **--<prefix>-* 前缀**的 :root 令牌块（单行紧凑格式）。

    为什么需要前缀版本：
    旧报告生成器普遍自带 :root（定义了 --bg / --panel / --txt 等名字）。
    若把它们的取值直接换成 var(--bg)，会产出 `--bg: var(--bg)` 这种
    **自引用**，CSS 变量随即失效。改用独立前缀后语义正确：
    旧 :root 变成 `--bg: var(--viz-bg)`。

    为什么要从本模块生成而不是在迁移工具里手写一份：
    手写副本等于制造「两份色值靠人工同步」——那正是本项目要消灭的问题。
    本函数让色值真相只存在于 theme.py 一处。

    用法：
        from viz.theme import compat_vars
        css = compat_vars("dark")     # 注入到报告的 <style> 里
    """
    if scheme not in ("dark", "light"):
        raise ValueError(f"scheme 只能是 dark/light，收到 {scheme!r}")
    n = NEUTRALS_DARK if scheme == "dark" else NEUTRALS_LIGHT
    p = f"--{prefix}"
    decls = [
        f"{p}-bg:{n['bg']}",
        f"{p}-panel:{n['panel']}",
        f"{p}-surface:{n['surface']}",
        f"{p}-fg:{n['fg']}",
        f"{p}-muted:{n['muted']}",
        f"{p}-faint:{n['faint']}",
        f"{p}-border:{n['border']}",
        f"{p}-accent:{SPORTS['accent']}",
        f"{p}-positive:{STATE['positive']}",
        f"{p}-negative:{STATE['negative']}",
        f"{p}-warn:{STATE['warn']}",
        f"{p}-font-sans:{TYPO['font-sans']}",
        f"{p}-font-mono:{TYPO['font-mono']}",
    ]
    # 分类色（数据编码用）：--viz-cat-1..10 循环取 CATEGORICAL
    for i, c in enumerate(CATEGORICAL, 1):
        decls.append(f"{p}-cat-{i}:{c}")
    return ":root{" + ";".join(decls) + ";color-scheme:" + scheme + ";}"


__all__ = [
    "SPORTS", "FINANCE", "DIVERGING", "CATEGORICAL", "TEAM_COLORS",
    "SPACING", "TYPO", "RADIUS", "SHADOW",
    "NEUTRALS_DARK", "NEUTRALS_LIGHT", "STATE",
    "CSS_VARS_DARK", "CSS_VARS_LIGHT", "compat_vars", "hex",
]
