"""NBACore v8 — Tactics Engine 坐标映射（唯一映射点，Layer 2）。

将 NBACore PBP 的 (x, y) 整数坐标映射到半场 SVG 像素 (px, py)。

源数据语义（经 DB 抽样确认，season 2025 br_crawler）：
    - x ∈ [-250, 250]：横向，±25 ft ×10，0 在中线。
    - y：距某一底线的距离（ft ×10）。实测 y ∈ [-52, 842]，属**全场帧**
      （NBA 全场约 94 ft ×10 = 940 单位，半场线在 y=470）。
    - 投篮真实坐标落在 [0, 940] 区间；非投篮事件 (0,0) 占位。

映射约定（确定性、无副作用）：
    - FOLD_FULL_COURT=True：先将全场 y 折叠到攻击半场（距最近底线）。
    - 半场 SVG viewBox = "0 0 500 470"，篮筐端恒在**底部**（FIXED 朝向）。
    - sx = SVG_W/2 + x            → x=0 映射到中心(250)
    - folded_y = min(y_clamped, FULL_COURT_Y - y_clamped)
    - sy = SVG_H - folded_y       → y=0(底线) → 底部(470)；y=470(半场顶) → 顶部(0)

注：架构共享知识 §8.1 原示例用 94 作半场折叠常量，系按「半场帧」假设；
经联库抽样（见上）确认源为**全场帧**，故此处折叠常量改为 FULL_COURT_Y=940
并做 clamp，属架构 §9 ④「联库抽样验证后调整」授权范围。映射结果 deterministic。
"""
from __future__ import annotations

# ── 半场 SVG 尺寸 ──
SVG_W: int = 500
SVG_H: int = 470

# 坐标单位 → 像素：1:1（500 宽 ↔ x∈[-250,250]）
PX_PER_UNIT: float = 1.0

# 源为全场帧：全场长度（ft×10）。半场线在 FULL_COURT_Y/2 = 470。
FULL_COURT_Y: float = 940.0
COURT_HALF_Y: float = FULL_COURT_Y / 2.0  # 470.0

# 是否折叠全场到半场（v1 恒 True；若源已为半场帧可置 False）
FOLD_FULL_COURT: bool = True

# ── 队色（与架构 §8.2 一致）──
HOME_COLOR: str = "#2563eb"  # 蓝（主队）
AWAY_COLOR: str = "#ef4444"  # 红（客队）

# 无历史位置球员的语义默认落点（本方半场底线附近，按队错位避免重叠）
DEFAULT_HOME_Y: float = 50.0
DEFAULT_AWAY_Y: float = 85.0


def _fold_half(y: float) -> float:
    """将全场 y 折叠到攻击半场 [0, COURT_HALF_Y]。

    先 clamp 到 [0, FULL_COURT_Y] 避免负/越界 y 破坏折叠；
    再取「距最近底线」的距离作为半场坐标。
    """
    yc = max(0.0, min(float(y), FULL_COURT_Y))
    if not FOLD_FULL_COURT:
        return yc
    return min(yc, FULL_COURT_Y - yc)


def map_xy_to_svg(x: float, y: float) -> "tuple[float, float]":
    """NBA (x, y) → 半场 SVG 像素 (px, py)。确定性、无副作用。"""
    sx = SVG_W / 2.0 + float(x) * PX_PER_UNIT
    sy = SVG_H - _fold_half(y)
    return (sx, sy)


def map_point(pt: "tuple[float, float]") -> "tuple[float, float]":
    """便捷：映射单点 (x, y)。"""
    return map_xy_to_svg(pt[0], pt[1])
