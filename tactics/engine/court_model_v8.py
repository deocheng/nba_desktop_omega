#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.27 场地模型 v8：远端边线锁定老程裁定线，近端同斜率平移（平行铁律）。

老程裁定（2026-10-01 13:40）：
  · 远端边线 = `FAR_right` 对照图里的**红线** = y = 0.0740x + 137.6（y@640=185）
  · 该斜率 +0.074 与**油漆区单应**给出的 +0.0739 一致 ⇒ 油漆区"方向"可信、"位置"偏 23px。
模型：远端线锁定；近端 = 同斜率、位置可调(--near-y640)；底线/罚球线取油漆区左右边。
坐标：X=长度(0=底线→右) / Y=宽度(0=远边线,15.24=近边线)，m。
用法:
  court_model_v8.py --seg ep24_s1 --idx 70 --far 0.0740:137.6 --near-y640 605
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
import court_infer_lines as CI  # noqa: E402
from court_homography_recover import fit_quad  # noqa: E402

COURT_L, COURT_W = 28.6512, 15.2400
KEY_W, KEY_D = 4.8768, 5.7912
KEY_Y0 = (COURT_W - KEY_W) / 2.0
BASKET = (1.6002, COURT_W / 2)
ARC_R, FT_R, RA_R = 7.239, 1.8288, 1.2192
CORNER_Y = 0.9144
_TH = np.arcsin(min(1.0, (COURT_W / 2 - CORNER_Y) / ARC_R))
ARC_X0 = BASKET[0] + ARC_R * np.cos(_TH)


def paint_quad(img):
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    raw = cv2.inRange(hsv, np.array([110, 60, 70]), np.array([170, 255, 255]))
    m = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((31, 31), np.uint8))
    keep = np.zeros_like(m)
    keep[int(0.25 * H):int(0.75 * H), int(0.06 * W):int(0.72 * W)] = 255
    m = cv2.bitwise_and(m, keep)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    if n <= 1:
        return None, None
    b = 1 + int(np.argmax(st[1:, 4]))
    mm = np.where(lab == b, 255, 0).astype(np.uint8)
    q = fit_quad(mm)
    return (None if q is None else np.asarray(q, float)), mm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--far", default="0.0740:137.6", help="远端边线 y=a*x+b (老程裁定)")
    ap.add_argument("--near-y640", type=float, default=605.0)
    ap.add_argument("--near-slope", type=float, default=None, help="默认与远端同斜率(平行)")
    ap.add_argument("--base-vline", default="", help="底线覆盖 x=m*y+c (如累积左边界 '-1.0124:598.3')")
    ap.add_argument("--ft-vline", default="", help="罚球线覆盖 x=m*y+c (油漆区右边缘拟合)")
    ap.add_argument("--base-h", type=float, default=720.0)
    ap.add_argument("--clean", action="store_true", help="只画关键线，无填充无网格")
    ap.add_argument("--out-tag", default="")
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]

    fa, fb = [float(v) for v in a.far.split(":")]
    m = fa if a.near_slope is None else a.near_slope
    yt = fa * (W / 2) + fb
    yb = a.near_y640
    sid_far = (0.0, fb, float(W - 1), fa * (W - 1) + fb)
    b_near = yb - m * (W / 2)
    sid_near = (0.0, b_near, float(W - 1), m * (W - 1) + b_near)

    q, mm = paint_quad(img)
    if q is None:
        print("油漆区未检出"); return
    order = np.argsort(q[:, 0])
    lft = q[order[:2]]; rgt = q[order[2:]]
    lft = lft[np.argsort(lft[:, 1])]; rgt = rgt[np.argsort(rgt[:, 1])]
    base_line = (float(lft[0][0]), float(lft[0][1]), float(lft[1][0]), float(lft[1][1]))
    ft_line = (float(rgt[0][0]), float(rgt[0][1]), float(rgt[1][0]), float(rgt[1][1]))
    if a.base_vline:
        bm, bc = [float(v) for v in a.base_vline.split(":")]
        base_line = (bc, 0.0, bm * (a.base_h - 1) + bc, a.base_h - 1)
    if a.ft_vline:
        fm, fc = [float(v) for v in a.ft_vline.split(":")]
        ft_line = (fc, 0.0, fm * (a.base_h - 1) + fc, a.base_h - 1)

    print(f"=== A5.27 场地模型 v8 {a.seg} f{a.idx}  {W}x{H} ===")
    print(f"  远端边线(锁定) y={fa:.4f}x+{fb:.1f}  y@640={yt:.1f}")
    print(f"  近端边线(平行) y={m:.4f}x+{b_near:.1f}  y@640={yb:.1f}")
    print(f"  油漆区左(底线)边 {np.int32(base_line).tolist()} | 右(罚球线)边 {np.int32(ft_line).tolist()}")

    c00 = CI.intersect(sid_far, base_line)
    c0W = CI.intersect(sid_near, base_line)
    cX0 = CI.intersect(sid_far, ft_line)
    cXW = CI.intersect(sid_near, ft_line)
    if any(v is None for v in (c00, c0W, cX0, cXW)):
        print("交点失败"); return
    img_c = np.array([c00, c0W, cXW, cX0], np.float32)
    world_c = np.array([[0.0, 0.0], [0.0, COURT_W], [KEY_D, COURT_W], [KEY_D, 0.0]], np.float32)
    Hm = cv2.getPerspectiveTransform(world_c, img_c)
    print(f"  锚点: 上∩底={np.int32(c00).tolist()} 下∩底={np.int32(c0W).tolist()} "
          f"上∩罚球线={np.int32(cX0).tolist()} 下∩罚球线={np.int32(cXW).tolist()}")

    def P(pts):
        pts = np.asarray(pts, np.float32).reshape(-1, 2)
        return cv2.perspectiveTransform(pts[None], Hm)[0]

    pf = P([[0, 0], [COURT_L, 0]]); pn = P([[0, COURT_W], [COURT_L, COURT_W]])
    spf = (pf[1][1] - pf[0][1]) / (pf[1][0] - pf[0][0])
    spn = (pn[1][1] - pn[0][1]) / (pn[1][0] - pn[0][0])
    d_m = float(np.linalg.norm(P([[0, 1]])[0] - P([[0, 0]])[0]))
    d_l = float(np.linalg.norm(P([[1, COURT_W / 2]])[0] - P([[0, COURT_W / 2]])[0]))
    print(f"  自证 投影两边线 slope={spf:.5f}/{spn:.5f} 差={abs(spf-spn):.5f} "
          f"({'平行✅' if abs(spf-spn)<1e-3 else '⚠️'})")
    print(f"  比例尺 宽(Y)1m≈{d_m:.1f}px 长(X)1m≈{d_l:.1f}px ; 球场投影4角 "
          f"{np.int32(P([[0,0],[COURT_L,0],[COURT_L,COURT_W],[0,COURT_W]])).tolist()}")

    vis = img.copy()
    cp = P([[0, 0], [COURT_L, 0], [COURT_L, COURT_W], [0, COURT_W]])
    mfill = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mfill, [np.int32(cp)], 255)
    ov = vis.copy(); ov[mfill > 0] = (0.84 * ov[mfill > 0] + 0.16 * np.array([0, 180, 255])).astype(np.uint8)
    if not a.clean:
        vis = ov
        for xm in np.arange(0, COURT_L + 0.01, 1.0):
            p = P([[xm, 0], [xm, COURT_W]])
            cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), (205, 150, 95), 1)
        for ym in np.arange(0, COURT_W + 0.01, 1.0):
            p = P([[0, ym], [COURT_L, ym]])
            cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), (205, 150, 95), 1)
    # 油漆区(投影) ↔ 检测紫漆 IoU 自证
    keypol = P([[0, KEY_Y0], [KEY_D, KEY_Y0], [KEY_D, KEY_Y0 + KEY_W], [0, KEY_Y0 + KEY_W]])
    mk = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mk, [np.int32(keypol)], 255)
    inter = int(((mk > 0) & (mm > 0)).sum())
    union = int(((mk > 0) | (mm > 0)).sum())
    print(f"  IoU(投影油漆区, 真实紫色掩膜) = {inter/max(union,1):.3f}")
    cv2.polylines(vis, [np.int32(cp)], True, (0, 215, 255), 3)
    cv2.line(vis, tuple(np.int32(P([[0, 0]])[0])), tuple(np.int32(P([[0, COURT_W]])[0])), (0, 215, 255), 5)
    ph = P([[COURT_L / 2, 0], [COURT_L / 2, COURT_W]])
    cv2.line(vis, tuple(np.int32(ph[0])), tuple(np.int32(ph[1])), (0, 255, 120), 2)
    key = P([[0, KEY_Y0], [KEY_D, KEY_Y0], [KEY_D, KEY_Y0 + KEY_W], [0, KEY_Y0 + KEY_W]])
    cv2.polylines(vis, [np.int32(key)], True, (255, 255, 255), 2)
    for ycor in (CORNER_Y, COURT_W - CORNER_Y):
        s = P([[0, ycor], [ARC_X0, ycor]])
        cv2.line(vis, tuple(np.int32(s[0])), tuple(np.int32(s[1])), (255, 80, 0), 3)
    t = np.linspace(-_TH, _TH, 120)
    arc = np.stack([BASKET[0] + ARC_R * np.cos(t), BASKET[1] + ARC_R * np.sin(t)], 1)
    cv2.polylines(vis, [np.int32(P(arc))], False, (255, 80, 0), 3)
    tt = np.linspace(0, 2 * np.pi, 120)
    ftc = np.stack([KEY_D + FT_R * np.cos(tt), COURT_W / 2 + FT_R * np.sin(tt)], 1)
    cv2.polylines(vis, [np.int32(P(ftc))], True, (255, 0, 255), 2)
    ra = np.stack([BASKET[0] + RA_R * np.cos(np.linspace(-np.pi / 2, np.pi / 2, 60)),
                   BASKET[1] + RA_R * np.sin(np.linspace(-np.pi / 2, np.pi / 2, 60))], 1)
    cv2.polylines(vis, [np.int32(P(ra))], False, (255, 255, 0), 2)
    cv2.circle(vis, tuple(np.int32(P([list(BASKET)])[0])), 8, (0, 0, 255), -1)
    cs, _ = cv2.findContours(mm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, cs, -1, (0, 255, 255), 1)

    txt = ["黄=场地/底线 蓝=三分线 品红=罚球圈 青=冲撞区 白=油漆区 绿=半场线 红=篮筐",
           f"远端锁定 y={fa:.4f}x+{fb:.1f} | 近端平行 y@640={yb:.0f} | 宽{d_m:.1f}px/m 长{d_l:.1f}px/m"]
    for i, s in enumerate(txt):
        cv2.putText(vis, s, (10, 26 + i * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (0, 0, 0), 4)
        cv2.putText(vis, s, (10, 26 + i * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (0, 255, 255), 2)
    op = OUT / f"{a.seg}_f{a.idx}_model_v8_ny{int(yb)}.png"
    cv2.imwrite(str(op), vis)
    print(f"-> {op}")
    json.dump({"far": [fa, fb], "near": [m, b_near], "near_y640": yb,
               "px_per_m_w": round(d_m, 2), "px_per_m_l": round(d_l, 2),
               "img_corners": np.int32(img_c).tolist()},
              open(str(OUT / f"{a.seg}_f{a.idx}_model_v8.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
