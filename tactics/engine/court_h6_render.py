#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.28 场地模型：从 6 参数单应 (Y=const 平行 ⇒ 单向透视) 渲染整场 + 关键自证。
Hm = [[a, b, c],
      [d, e, f],
      [0, h, 1]] ;  u=(aX+bY+c)/(hY+1), v=(dX+eY+f)/(hY+1)
用法: court_h6_render.py --abc "a,b,c,d,e,f,h" --tag name
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import glob
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"

COURT_L, COURT_W = 28.6512, 15.2400
KEY_W, KEY_D = 4.8768, 5.7912
KEY_Y0 = (COURT_W - KEY_W) / 2.0
BASKET = (1.6002, COURT_W / 2)
ARC_R, FT_R, RA_R = 7.239, 1.8288, 1.2192
CORNER_Y = 0.9144
_TH = np.arcsin(min(1.0, (COURT_W / 2 - CORNER_Y) / ARC_R))
ARC_X0 = BASKET[0] + ARC_R * np.cos(_TH)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--abc", required=True, help="a,b,c,d,e,f,h")
    ap.add_argument("--tag", default="h6")
    a = ap.parse_args()
    A, B, C, D, E, F, Hh = [float(v) for v in a.abc.split(",")]
    Hm = np.array([[A, B, C], [D, E, F], [0.0, Hh, 1.0]], float)

    fs = sorted(glob.glob(str(SEGD / a.seg / "frames" / "f*.jpg")))
    img = cv2.imread(fs[a.idx]); H, W = img.shape[:2]

    def P(pts):
        pts = np.asarray(pts, np.float32).reshape(-1, 2)
        return cv2.perspectiveTransform(pts[None], Hm)[0]

    # self-checks
    c = P([[KEY_D, COURT_W / 2]])[0]
    bmid = P([[0, COURT_W / 2]])[0]
    pf = P([[0, 0], [COURT_L, 0]])
    sf = (pf[1][1] - pf[0][1]) / (pf[1][0] - pf[0][0])
    d_m = float(np.linalg.norm(P([[0, 1]])[0] - P([[0, 0]])[0]))
    d_l = float(np.linalg.norm(P([[1, COURT_W / 2]])[0] - P([[0, COURT_W / 2]])[0]))
    print(f"=== h6 {a.seg} f{a.idx}  {a.abc} ===")
    print(f"  ft_center=({c[0]:.0f},{c[1]:.0f})  baseline@mid=({bmid[0]:.0f},{bmid[1]:.0f})  far_slope={sf:.4f}")
    print(f"  1m: 宽(Y)≈{d_m:.1f}px  长(X)≈{d_l:.1f}px")

    vis = img.copy()
    for xm in np.arange(0, COURT_L + 0.01, 1.0):
        p = P([[xm, 0], [xm, COURT_W]]); cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), (205, 150, 95), 1)
    for ym in np.arange(0, COURT_W + 0.01, 1.0):
        p = P([[0, ym], [COURT_L, ym]]); cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), (205, 150, 95), 1)
    cp = P([[0, 0], [COURT_L, 0], [COURT_L, COURT_W], [0, COURT_W]])
    cv2.polylines(vis, [np.int32(cp)], True, (0, 215, 255), 3)
    ph = P([[COURT_L / 2, 0], [COURT_L / 2, COURT_W]]); cv2.line(vis, tuple(np.int32(ph[0])), tuple(np.int32(ph[1])), (0, 255, 120), 2)
    key = P([[0, KEY_Y0], [KEY_D, KEY_Y0], [KEY_D, KEY_Y0 + KEY_W], [0, KEY_Y0 + KEY_W]])
    cv2.polylines(vis, [np.int32(key)], True, (255, 255, 255), 2)
    for ycor in (CORNER_Y, COURT_W - CORNER_Y):
        s = P([[0, ycor], [ARC_X0, ycor]]); cv2.line(vis, tuple(np.int32(s[0])), tuple(np.int32(s[1])), (255, 80, 0), 3)
    t = np.linspace(-_TH, _TH, 160)
    arc = np.stack([BASKET[0] + ARC_R * np.cos(t), BASKET[1] + ARC_R * np.sin(t)], 1)
    cv2.polylines(vis, [np.int32(P(arc))], False, (255, 80, 0), 3)
    tt = np.linspace(0, 2 * np.pi, 160)
    ftc = np.stack([KEY_D + FT_R * np.cos(tt), COURT_W / 2 + FT_R * np.sin(tt)], 1)
    cv2.polylines(vis, [np.int32(P(ftc))], True, (255, 0, 255), 2)
    ra = np.stack([BASKET[0] + RA_R * np.cos(np.linspace(-np.pi / 2, np.pi / 2, 60)),
                   BASKET[1] + RA_R * np.sin(np.linspace(-np.pi / 2, np.pi / 2, 60))], 1)
    cv2.polylines(vis, [np.int32(P(ra))], False, (255, 255, 0), 2)
    cv2.circle(vis, tuple(np.int32(P([list(BASKET)])[0])), 8, (0, 0, 255), -1)
    op = OUT / f"_h6_{a.seg}_f{a.idx}_{a.tag}.png"
    cv2.imwrite(str(op), vis); print("->", op)
    for (y0, y1, x0, x1, tag) in [(150, 650, 100, 700, "L"), (150, 650, 640, 1280, "R")]:
        crop = vis[y0:y1, x0:x1].copy()
        for y in range((y0 // 50 + 1) * 50, y1, 50):
            cv2.line(crop, (0, y - y0), (crop.shape[1], y - y0), (0, 0, 255), 1)
            cv2.putText(crop, str(y), (2, y - y0 + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
        for x in range((x0 // 100 + 1) * 100, x1, 100):
            cv2.line(crop, (x - x0, 0), (x - x0, crop.shape[0]), (0, 255, 0), 1)
            cv2.putText(crop, str(x), (x - x0 + 2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
        cv2.imwrite(str(OUT / f"_h6_{a.tag}_{tag}.png"), crop)
    json.dump({"abc": [A, B, C, D, E, F, Hh], "ft_center": c.tolist(), "base_mid": bmid.tolist()},
              open(str(OUT / f"_h6_{a.tag}.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
