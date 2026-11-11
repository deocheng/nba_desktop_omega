#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.24 边线视角场地模型 v6（正确坐标系 + 稳健油漆区）。

坐标：X=沿长度(0=底线,→右), Y=沿宽度(0=远端边线, 15.24=近端边线)。单位 m。
锚点：油漆区 4 角（稳健检测）→ 单应 H；再用累积掩膜边线/白线做自证叠图。

用法: court_model_v6.py --seg ep24_s1 --idx 70 [--overlay-accum freq.npy]
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
from court_homography_recover import fit_quad  # noqa: E402

COURT_L, COURT_W = 28.6512, 15.2400
KEY_W, KEY_D = 4.8768, 5.7912
KEY_Y0 = (COURT_W - KEY_W) / 2.0          # 5.1816
BASKET = (1.6002, COURT_W / 2)
ARC_R, FT_R, RA_R = 7.239, 1.8288, 1.2192
CORNER_Y = 0.9144
_TH = np.arcsin(min(1.0, (COURT_W / 2 - CORNER_Y) / ARC_R))
ARC_X0 = BASKET[0] + ARC_R * np.cos(_TH)


def paint_quad(img):
    """稳健油漆区：紫色 → 大核开运算去球衣/观众 → 限制区域 → 最大连通域 → 凸四边形。"""
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    raw = cv2.inRange(hsv, np.array([110, 60, 70]), np.array([170, 255, 255]))
    m = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((31, 31), np.uint8))
    keep = np.zeros_like(m)
    y0, y1 = int(0.25 * H), int(0.75 * H)
    x0, x1 = int(0.06 * W), int(0.72 * W)
    keep[y0:y1, x0:x1] = 255
    m = cv2.bitwise_and(m, keep)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    if n <= 1:
        return None
    b = 1 + int(np.argmax(st[1:, 4]))
    mm = np.where(lab == b, 255, 0).astype(np.uint8)
    q = fit_quad(mm)
    return None if q is None else (np.asarray(q, float), mm)


def assign(img_quad):
    """图像4角 → 世界4角(X=0/KD, Y=KEY_Y0/KEY_Y0+KEY_W)。按 x 分左右，按 y 分远近。"""
    q = np.asarray(img_quad, float)
    order = np.argsort(q[:, 0])
    lft = q[order[:2]]; rgt = q[order[2:]]
    lft = lft[np.argsort(lft[:, 1])]      # (小y=远/KEY_Y0, 大y=近/KEY_Y0+KEY_W)
    rgt = rgt[np.argsort(rgt[:, 1])]
    img4 = np.array([lft[0], rgt[0], rgt[1], lft[1]], np.float32)
    world4 = np.array([[0.0, KEY_Y0], [KEY_D, KEY_Y0],
                       [KEY_D, KEY_Y0 + KEY_W], [0.0, KEY_Y0 + KEY_W]], np.float32)
    return world4, img4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--overlay-accum", default="_tmp_freq_ep24_s1_w0_93.npy")
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]

    pq = paint_quad(img)
    if pq is None:
        print("油漆区未检出"); return
    q, mm = pq
    world4, img4 = assign(q)
    Hm = cv2.getPerspectiveTransform(world4, img4)
    back = cv2.perspectiveTransform(world4[None], Hm)[0]
    print(f"=== A5.24 场地模型v6 {a.seg} f{a.idx}  {W}x{H} ===")
    print(f"  油漆区图像4角: {np.int32(img4).tolist()}")
    print(f"  重投影最大误差 = {np.abs(back-img4).max():.3f}px")

    def P(pts):
        pts = np.asarray(pts, np.float32).reshape(-1, 2)
        return cv2.perspectiveTransform(pts[None], Hm)[0]

    cp = P([[0, 0], [COURT_L, 0], [COURT_L, COURT_W], [0, COURT_W]])
    print(f"  球场4角投影: {np.int32(cp).tolist()}")
    # 边线在 x=W/2 的 y
    for nm, Y in (("远端边线(Y=0)", 0.0), ("近端边线(Y=15.24)", COURT_W)):
        y = P([[0, Y], [COURT_L, Y]])
        xm = W / 2
        # 线参数
        t = (xm - y[0][0]) / (y[1][0] - y[0][0])
        yy = y[0][1] + t * (y[1][1] - y[0][1])
        sl = (y[1][1] - y[0][1]) / (y[1][0] - y[0][0])
        print(f"  {nm}: y@W/2={yy:.1f}  slope={sl:.4f}")
    d_m = np.linalg.norm(P([[0, 1]])[0] - P([[0, 0]])[0])
    d_l = np.linalg.norm(P([[1, COURT_W / 2]])[0] - P([[0, COURT_W / 2]])[0])
    print(f"  比例尺: 宽(Y)1m≈{d_m:.1f}px  长(X)1m≈{d_l:.1f}px")

    # ---- 渲染 ----
    vis = img.copy()
    # 场地填充
    m = np.zeros((H, W), np.uint8)
    cv2.fillPoly(m, [np.int32(cp)], 255)
    ov = vis.copy(); ov[m > 0] = (0.80 * ov[m > 0] + 0.20 * np.array([0, 180, 255])).astype(np.uint8)
    vis = ov
    # 1m 网格
    for xm in np.arange(0, COURT_L + 0.01, 1.0):
        p = P([[xm, 0], [xm, COURT_W]])
        cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), (200, 150, 90), 1)
    for ym in np.arange(0, COURT_W + 0.01, 1.0):
        p = P([[0, ym], [COURT_L, ym]])
        cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), (200, 150, 90), 1)
    # 场地矩形(黄)
    cv2.polylines(vis, [np.int32(cp)], True, (0, 215, 255), 3)
    # 底线加粗(黄, X=0)
    cv2.line(vis, tuple(np.int32(P([[0, 0]])[0])), tuple(np.int32(P([[0, COURT_W]])[0])), (0, 215, 255), 5)
    # 半场线(青绿)
    ph = P([[COURT_L / 2, 0], [COURT_L / 2, COURT_W]])
    cv2.line(vis, tuple(np.int32(ph[0])), tuple(np.int32(ph[1])), (0, 255, 120), 2)
    # 油漆区边框(白)
    key = P([[0, KEY_Y0], [KEY_D, KEY_Y0], [KEY_D, KEY_Y0 + KEY_W], [0, KEY_Y0 + KEY_W]])
    cv2.polylines(vis, [np.int32(key)], True, (255, 255, 255), 2)
    # 三分线(蓝): 底角直线 + 弧
    for ycor in (CORNER_Y, COURT_W - CORNER_Y):
        s = P([[0, ycor], [ARC_X0, ycor]])
        cv2.line(vis, tuple(np.int32(s[0])), tuple(np.int32(s[1])), (255, 80, 0), 3)
    t = np.linspace(-_TH, _TH, 120)
    arc = np.stack([BASKET[0] + ARC_R * np.cos(t), BASKET[1] + ARC_R * np.sin(t)], 1)
    cv2.polylines(vis, [np.int32(P(arc))], False, (255, 80, 0), 3)
    # 罚球圈(品红)
    tt = np.linspace(0, 2 * np.pi, 120)
    ftc = np.stack([KEY_D + FT_R * np.cos(tt), COURT_W / 2 + FT_R * np.sin(tt)], 1)
    cv2.polylines(vis, [np.int32(P(ftc))], True, (255, 0, 255), 2)
    # 合理冲撞区(青)
    ra = np.stack([BASKET[0] + RA_R * np.cos(np.linspace(-np.pi / 2, np.pi / 2, 60)),
                   BASKET[1] + RA_R * np.sin(np.linspace(-np.pi / 2, np.pi / 2, 60))], 1)
    cv2.polylines(vis, [np.int32(P(ra))], False, (255, 255, 0), 2)
    # 篮筐(红)
    cv2.circle(vis, tuple(np.int32(P([list(BASKET)])[0])), 8, (0, 0, 255), -1)
    # 油漆区检测轮廓(黄细)
    cs, _ = cv2.findContours(mm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, cs, -1, (0, 255, 255), 1)

    txt = ["黄=场地/底线 蓝=三分线 品红=罚球圈 青=冲撞区 白=油漆区 绿=半场线 红=篮筐",
           f"油漆区4角建模 比例尺 宽{d_m:.0f}px/m 长{d_l:.0f}px/m"]
    for i, s in enumerate(txt):
        cv2.putText(vis, s, (10, 26 + i * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 0, 0), 4)
        cv2.putText(vis, s, (10, 26 + i * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 255), 2)
    op = OUT / f"{a.seg}_f{a.idx}_model_v6.png"
    cv2.imwrite(str(op), vis)
    print(f"-> {op}")
    json.dump({"world4": world4.tolist(), "img4": img4.tolist()},
              open(str(OUT / f"{a.seg}_f{a.idx}_model_v6.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
