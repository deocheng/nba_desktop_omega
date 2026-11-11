#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NBA 球场**几何模型** + 针孔相机 —— 单帧球场配准（court registration）的基础件。

用户那句「唯一不变的就是边线、中线、三分线」在这里被编码成**一个常量表**：
涂装/地板色/广告/球衣都是变量，但 NBA 球场每条线的**米制坐标是规范常量**。
于是「认出球场」= 求一个相机位姿，使**模型线投影到图上恰好落在实测线像素上**。

坐标约定（全文件统一，勿混）
--------------------------
  · 世界坐标（米）：原点 = 球场中心地板；+x 沿长轴（指向"我们要看的那个篮筐"），
    +y 沿短轴，+z 竖直向上。地板平面 = z = 0。
  · 图像坐标：像素，(0,0) = 左上，x 右 y 下。
  · 相机：p_cam = R @ (p_world − C)；u = cx + f·x/z，v = cy + f·y/z。
    R = Rz(roll) @ Rx(pitch) @ Ry(yaw)，即先把世界绕 y 转 yaw、再绕 x 转 pitch、再绕 z 转 roll。

为什么不用 v1/v2 的消失点路线（`court_vp.py` / `court_vp2.py`）
------------------------------------------------------------
消失点要求**两条同族长线段**；本素材单帧只有 3 条 ≥150px 线段（远端边线被 ROI 切掉、
近端边线被观众压住、中圈 logo 的曲线描边干扰）。**模型拟合不要求任何线段足够长** ——
它用的是整张线像素图 + 全部规范几何，一行被挡住一半也照样是约束。
"""
from __future__ import annotations

import numpy as np

# ---------------- NBA 规范常量（米；94ft x 50ft） ----------------
FT = 0.3048
HALF_L = 94 * FT / 2          # 14.3256  半长
HALF_W = 50 * FT / 2          # 7.62     半宽
X_BASKET = HALF_L - 5.25 * FT  # 12.7254  篮筐中心（距底线 5.25ft）
X_BOARD = HALF_L - 4.0 * FT    # 13.1064  篮板正面（距底线 4ft）
Z_RIM = 10 * FT                # 3.048    篮筐高度
R_RIM = 0.2286                 # 篮圈半径（18in 内径）
Z_BB_LO, Z_BB_HI = 9.5 * FT, 13.0 * FT   # 2.8956 / 3.9624 篮板上下沿
BB_HALF_W = 3.0 * FT           # 0.9144   篮板半宽（6ft）
X_LANE = HALF_L - 19 * FT      # 8.5344   罚球线（距底线 19ft）
LANE_HW = 8 * FT               # 2.4384   油漆区半宽（16ft 宽）
R_FT = 6 * FT                  # 1.8288   罚球圈半径
R_3PT = 23.75 * FT             # 7.2390   三分弧半径
Y_3PT_CORNER = HALF_W - 3 * FT  # 6.7056   底角三分线（距边线 3ft）
R_CENTER = 6 * FT              # 1.8288   中圈半径


def arc(cx, cy, r, a0, a1, n=64, z=0.0):
    a = np.linspace(a0, a1, n)
    return np.stack([cx + r * np.cos(a), cy + r * np.sin(a),
                     np.full_like(a, z)], axis=1)


def seg(x1, y1, x2, y2, z=0.0, n=24):
    t = np.linspace(0, 1, n)[:, None]
    p0 = np.array([x1, y1, z]); p1 = np.array([x2, y2, z])
    return (p0[None, :] * (1 - t) + p1[None, :] * t)


def build_model():
    """→ list[(name, Nx3 世界坐标点集)]。全部按"画出来的线"采样，密度 ~0.08m。"""
    S = []
    n_arc = 120
    # 1) 边界四条
    S.append(("bound_near", seg(-HALF_L, -HALF_W, HALF_L, -HALF_W, n=140)))
    S.append(("bound_far",  seg(-HALF_L,  HALF_W, HALF_L,  HALF_W, n=140)))
    S.append(("base_L", seg(-HALF_L, -HALF_W, -HALF_L, HALF_W, n=48)))
    S.append(("base_R", seg( HALF_L, -HALF_W,  HALF_L, HALF_W, n=48)))
    # 2) 中线 + 中圈
    S.append(("midline", seg(0, -HALF_W, 0, HALF_W, n=48)))
    S.append(("circle_c", arc(0, 0, R_CENTER, 0, 2 * np.pi, n=n_arc)))
    # 3) 两个半场
    for s in (+1, -1):
        pre = "R" if s > 0 else "L"
        # 油漆区
        S.append((f"{pre}_lane_near", seg(s * HALF_L, -LANE_HW, s * X_LANE, -LANE_HW, n=40)))
        S.append((f"{pre}_lane_far",  seg(s * HALF_L,  LANE_HW, s * X_LANE,  LANE_HW, n=40)))
        S.append((f"{pre}_ft_line",   seg(s * X_LANE, -LANE_HW, s * X_LANE, LANE_HW, n=40)))
        # 罚球圈（两段半圆：靠篮筐侧实线/远离侧虚线，都会画）
        S.append((f"{pre}_ft_circle", arc(s * X_LANE, 0.0, R_FT, 0, 2 * np.pi, n=90)))
        # 三分弧：中心在篮筐，从一侧底角交点绕过弧顶到另一侧
        xj = X_BASKET - np.sqrt(R_3PT ** 2 - Y_3PT_CORNER ** 2)
        ang = np.arctan2(Y_3PT_CORNER, xj - X_BASKET)        # 约 +0.86 rad
        S.append((f"{pre}_3pt_arc", arc(s * X_BASKET, 0.0, R_3PT, ang, np.pi - ang, n=n_arc)))
        # 底角三分直线
        S.append((f"{pre}_3pt_cn", seg(s * HALF_L, -Y_3PT_CORNER, s * xj, -Y_3PT_CORNER, n=32)))
        S.append((f"{pre}_3pt_cf", seg(s * HALF_L,  Y_3PT_CORNER, s * xj,  Y_3PT_CORNER, n=32)))
        # 篮板（3D：两条竖边 + 上下沿，位于 z=2.90~3.96）
        S.append((f"{pre}_bb_top", seg(s * X_BOARD, -BB_HALF_W, s * X_BOARD, BB_HALF_W,
                                       z=Z_BB_HI, n=20)))
        S.append((f"{pre}_bb_bot", seg(s * X_BOARD, -BB_HALF_W, s * X_BOARD, BB_HALF_W,
                                       z=Z_BB_LO, n=20)))
        S.append((f"{pre}_bb_lft", seg(s * X_BOARD, -BB_HALF_W, s * X_BOARD, -BB_HALF_W,
                                       z=Z_BB_LO, n=8)))
        S.append((f"{pre}_bb_rgt", seg(s * X_BOARD,  BB_HALF_W, s * X_BOARD,  BB_HALF_W,
                                       z=Z_BB_LO, n=8)))
        # 篮圈（3D 圆）
        S.append((f"{pre}_rim", arc(s * X_BASKET, 0.0, R_RIM, 0, 2 * np.pi, n=48)))
    for k, (nm, P) in enumerate(S):
        if nm.endswith("rim"):
            S[k] = (nm, P + np.array([0, 0, Z_RIM]))
    return S


# ---------------- 相机 ----------------
# 相机的唯一实现是 `court_fit.LookCam`（look-at 参数化：C + 光轴落地交点 T + f + roll）。
# 本文件只负责**几何模型**。刻意不在这里再放一个 yaw/pitch/roll 版本 ——
# 两套相机约定并存是符号错误的经典来源（本项目已因此踩过坑）。
