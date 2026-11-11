#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.17 虚拟场地渲染（老程确认黄线无误后定稿版）。

老程裁定(2026-10-01)：「ep24_s1_f70_homog_v3.png 黄线没问题，绿线不算准，绿色弧线是什么？」
  ⇒ 黄线(homography 完整虚拟场地) = 场地真值 ✅
  ⇒ 绿色弧线 = 三分弧（图里与 v3.near 撞色，已修正）
  ⇒ 绿线(v3.near) 不准 → 降级为参考色

本图：以 v3 边线锚定的单应(半场线 Xf=14.33m)为场地真值，画**完整且正确**的虚拟场地：
  黄=场地矩形(真值) · 蓝=三分线(弧+底角直线段) · 品红=罚球圈/罚球线 · 青=合理冲撞区
  红点=篮筐 · 灰虚线=v3累积推断边线(参考,不准) · 橙=1m网格 · 底部比例尺
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))
import court_homography_recover as HR  # noqa: E402
import court_infer_lines as CI  # noqa: E402

COURT_L, COURT_W = HR.COURT_L, HR.COURT_W
FT_FT = 0.3048
# NBA 关键几何（米）
BASKET = (1.6002, COURT_W / 2)     # 篮筐中心 5.25ft 于底线内侧
KEY_D = 5.7912                     # 油漆区深 19ft
KEY_W = 4.8768                     # 油漆区宽 16ft (居中)
FT_CIRCLE_R = 1.8288               # 罚球圈 6ft
ARC_R = 7.239                      # 三分弧 23.75ft
RA_R = 1.2192                      # 合理冲撞区 4ft
CORNER_3_Y = 0.9144                # 底角三分线距边线 3ft
# 三分弧与底角直线交点角
import math

_SIN = (COURT_W / 2 - CORNER_3_Y) / ARC_R
_TH = math.asin(min(1.0, _SIN))
ARC_X0 = BASKET[0] + ARC_R * math.cos(_TH)   # 弧与底角线交点 x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--freq", default="_tmp_freq_ep24_s1_w0_93.npy")
    ap.add_argument("--spaint", type=float, default=133.8)
    ap.add_argument("--xf", type=float, default=14.33)
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]

    poly_v3, lo_v3, info_v3 = CI.infer(img, a.seg, a.freq, s_paint_win=a.spaint)
    near, far, base = lo_v3["near"], lo_v3["far"], lo_v3["baseline"]
    right = (float(W - 1), 0.0, float(W - 1), float(H - 1))
    c_nb = CI.intersect(near, base); c_nr = CI.intersect(near, right)
    c_fb = CI.intersect(far, base);  c_fr = CI.intersect(far, right)
    img_corners = np.array([c_nb, c_nr, c_fb, c_fr], np.float32)
    world_corners = np.array([[0.0, 0.0], [0.0, COURT_W],
                              [a.xf, 0.0], [a.xf, COURT_W]], np.float32)
    Hm = cv2.getPerspectiveTransform(world_corners, img_corners)

    def P(pts):   # 世界(m) → 图像
        pts = np.asarray(pts, np.float32).reshape(-1, 2)
        return cv2.perspectiveTransform(pts[None], Hm)[0]

    vis = img.copy()
    # 1m 网格（淡橙，先画在最底层）
    for xm in np.arange(0, COURT_L + 0.01, 1.0):
        p = P([[xm, 0], [xm, COURT_W]])
        cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), (210, 150, 90), 1)
    for ym in np.arange(0, COURT_W + 0.01, 1.0):
        p = P([[0, ym], [COURT_L, ym]])
        cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), (210, 150, 90), 1)
    # 场地矩形（黄，真值）
    cproj = P([[0, 0], [COURT_L, 0], [COURT_L, COURT_W], [0, COURT_W]])
    cv2.polylines(vis, [cproj.astype(np.int32)], True, (0, 215, 255), 3)
    # 中圈线(半场线 x=COURT_L/2)、罚球线(x=KEY_D)
    for xw, col, th in [(COURT_L/2, (0, 190, 255), 2), (KEY_D, (0, 190, 255), 1)]:
        p = P([[xw, 0], [xw, COURT_W]])
        cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), col, th)
    # 油漆区
    key = P([[0, (COURT_W-KEY_W)/2], [KEY_D, (COURT_W-KEY_W)/2],
             [KEY_D, (COURT_W+KEY_W)/2], [0, (COURT_W+KEY_W)/2]])
    cv2.polylines(vis, [key.astype(np.int32)], True, (0, 190, 255), 2)
    # 三分线：两段底角直线 + 弧（蓝）
    for ycor in (CORNER_3_Y, COURT_W - CORNER_3_Y):
        seg = P([[0, ycor], [ARC_X0, ycor]])
        cv2.line(vis, tuple(np.int32(seg[0])), tuple(np.int32(seg[1])), (255, 60, 0), 3)
    t = np.linspace(-_TH, _TH, 120)
    arc = np.stack([BASKET[0] + ARC_R * np.cos(t), BASKET[1] + ARC_R * np.sin(t)], 1)
    cv2.polylines(vis, [P(arc).astype(np.int32)], False, (255, 60, 0), 3)
    # 罚球圈（品红，整圆）+ 合理冲撞区（青）
    tt = np.linspace(0, 2 * np.pi, 120)
    ft_circle = np.stack([KEY_D + FT_CIRCLE_R * np.cos(tt), COURT_W/2 + FT_CIRCLE_R * np.sin(tt)], 1)
    cv2.polylines(vis, [P(ft_circle).astype(np.int32)], True, (255, 0, 255), 2)
    ra = np.stack([BASKET[0] + RA_R * np.cos(np.linspace(-np.pi/2, np.pi/2, 60)),
                   BASKET[1] + RA_R * np.sin(np.linspace(-np.pi/2, np.pi/2, 60))], 1)
    cv2.polylines(vis, [P(ra).astype(np.int32)], False, (255, 255, 0), 2)
    # 篮筐（红点）
    bp = P([list(BASKET)])[0]
    cv2.circle(vis, tuple(np.int32(bp)), 8, (0, 0, 255), -1)
    # v3 参考边线（灰虚线）
    for seg4 in (near, far, base):
        x1, y1, x2, y2 = [int(v) for v in seg4]
        cv2.line(vis, (x1, y1), (x2, y2), (140, 140, 140), 1, cv2.LINE_AA)

    # 比例尺
    p0 = P([[0.0, 0.0]])[0]; p1 = P([[0.0, 1.0]])[0]
    d_m = float(np.linalg.norm(p1 - p0))
    q0 = P([[0.0, COURT_W/2]])[0]; q1 = P([[1.0, COURT_W/2]])[0]
    d_l = float(np.linalg.norm(q1 - q0))
    bx, by = 30, H - 40
    step = P([[0, 0]])[0]
    seg5 = P([[0.0, 0.0], [0.0, 5.0]])
    cv2.line(vis, tuple(np.int32(seg5[0])), tuple(np.int32(seg5[1])), (255, 255, 255), 6)
    cv2.line(vis, tuple(np.int32(seg5[0])), tuple(np.int32(seg5[1])), (0, 0, 0), 2)
    txt = [(f"1m≈{d_m:.0f}px(宽) {d_l:.0f}px(纵) | 1ft≈{d_m/0.3048:.0f}px | 5m 刻度见白条",
            (12, 28), (0, 215, 255)),
           ("黄=场地矩形(真值) 蓝=三分线(弧+底角) 品红=罚球圈 青=合理冲撞区 红点=篮筐 灰=v3参考",
            (12, 56), (0, 215, 255)),
           (f"Xf={a.xf:.2f}m(远端可见线)  W15.24m≈{15.24*d_m:.0f}px  L28.65m≈{28.65*d_l:.0f}px",
            (12, 84), (0, 215, 255))]
    for s, pos, col in txt:
        cv2.putText(vis, s, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
        cv2.putText(vis, s, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
    op = OUT / f"{a.seg}_f{a.idx}_court_virtual.png"
    cv2.imwrite(str(op), vis)
    print(f"=== A5.17 虚拟场地渲染 {a.seg} f{a.idx} ===")
    print(f"  比例尺: 1m≈{d_m:.1f}px(宽) / {d_l:.1f}px(纵); 1ft≈{d_m/0.3048:.1f}px")
    print(f"  篮筐图像位置={np.int32(bp).tolist()}; 三分弧半径(图像)≈{np.linalg.norm(P([[BASKET[0]+ARC_R,BASKET[1]]])[0]-bp):.0f}px")
    print(f"  -> {op}")
    json.dump({"seg": a.seg, "idx": a.idx, "xf_m": a.xf,
               "px_per_m_width": round(d_m, 1), "px_per_m_length": round(d_l, 1),
               "px_per_ft_width": round(d_m/0.3048, 1),
               "basket_px": np.int32(bp).tolist(),
               "v3": {k: info_v3.get(k) for k in ("containment", "coverage", "baseline_angle_deg", "ratio_dev_pct")}},
              open(str(OUT / f"{a.seg}_f{a.idx}_court_virtual.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
