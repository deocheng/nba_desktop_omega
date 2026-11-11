#!/usr/bin/env python3
"""court_arc_probe.py — 在给定 ROI 内分离"细白线"像素并做椭圆拟合（用于定位三分弧/罚球圈）。
用法: python3 court_arc_probe.py --seg ep24_s1 --idx 70 --roi x0,y0,x1,y1 [--minperim 60]
产出 _arc_{seg}_f{idx}.png + 打印 fitEllipse。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--roi", default="560,230,1250,580")
    ap.add_argument("--v", type=int, default=150)
    ap.add_argument("--s", type=int, default=75)
    ap.add_argument("--thin", type=int, default=13, help="水平开运算核宽")
    ap.add_argument("--minperim", type=float, default=120)
    a = ap.parse_args()

    files = sorted((SEGD / a.seg / "frames").glob("*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    wm = ((hsv[..., 2] > a.v) & (hsv[..., 1] < a.s)).astype(np.uint8) * 255
    wm = cv2.morphologyEx(wm, cv2.MORPH_OPEN,
                          cv2.getStructuringElement(cv2.MORPH_RECT, (a.thin, 1)))

    x0, y0, x1, y1 = [int(t) for t in a.roi.split(",")]
    roi = np.zeros_like(wm)
    roi[y0:y1, x0:x1] = wm[y0:y1, x0:x1]

    n, lab, st, cen = cv2.connectedComponentsWithStats(roi)
    pts = []
    print(f"ROI {a.roi}: {n-1} comps")
    for i in range(1, n):
        area = st[i, 4]
        bx, by, bw, bh = st[i, 0], st[i, 1], st[i, 2], st[i, 3]
        # 细长弧: 面积小但包围盒大
        fill = area / max(bw * bh, 1)
        if area < 40:
            continue
        keep = (fill < 0.22 and max(bw, bh) > a.minperim)
        print(f"  comp{i}: area={area:6d} bbox=({bx},{by},{bw},{bh}) fill={fill:.3f} {'KEEP' if keep else 'drop'}")
        if keep:
            ys, xs = np.where(lab == i)
            pts.append(np.stack([xs, ys], 1))
    vis = img.copy()
    if pts:
        P = np.vstack(pts).astype(np.float32)
        cv2.drawContours(vis, [P.reshape(-1, 1, 2).astype(np.int32)], -1, (0, 255, 0), 1)
        ell = cv2.fitEllipse(P)
        (cx, cy), (d1, d2), ang = ell
        print(f"fitEllipse: c=({cx:.1f},{cy:.1f}) axes=({d1:.1f},{d2:.1f}) ang={ang:.1f}  npix={len(P)}")
        cv2.ellipse(vis, ell, (0, 0, 255), 2)
        cv2.circle(vis, (int(cx), int(cy)), 5, (255, 0, 255), -1)
    cv2.imwrite(str(OUT / f"_arc_{a.seg}_f{a.idx}.png"), vis)
    print(f"wrote _arc_{a.seg}_f{a.idx}.png")


if __name__ == "__main__":
    main()
