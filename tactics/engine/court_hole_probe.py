#!/usr/bin/env python3
"""court_hole_probe.py — 紫漆掩膜的"洞"= 漆面上的白色标线（罚球圈/限制区弧/罚球线…）。
对每个洞做椭圆/最小外接圆拟合，给出中心与半径，用于判定"紫漆内的白圆"到底是不是罚球圈。
产出 _hole_{seg}_f{idx}.png + 打印数值。
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
    ap.add_argument("--open", type=int, default=9, help="开运算核(小一点以保留洞)")
    a = ap.parse_args()

    files = sorted((SEGD / a.seg / "frames").glob("*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    raw = cv2.inRange(hsv, np.array([110, 60, 70]), np.array([170, 255, 255]))
    m = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((a.open, a.open), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    b = 1 + int(np.argmax(st[1:, 4]))
    pm = np.where(lab == b, 255, 0).astype(np.uint8)
    print("purple CC bbox:", st[b].tolist(), "area", int(st[b, 4]))

    cnts, hier = cv2.findContours(pm, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    vis = img.copy()
    cv2.drawContours(vis, [c for i, c in enumerate(cnts) if hier[0][i][3] == -1],
                     -1, (0, 215, 255), 2)

    holes = [(i, c) for i, c in enumerate(cnts) if hier[0][i][3] != -1]
    print(f"{len(holes)} holes:")
    holes.sort(key=lambda t: -cv2.contourArea(t[1]))
    for i, (idx0, c) in enumerate(holes):
        ar = cv2.contourArea(c)
        if ar < 200:
            continue
        pts = c.reshape(-1, 2).astype(np.float32)
        (cx, cy), (d1, d2), ang = cv2.fitEllipse(pts)
        (ccx, ccy), rr = cv2.minEnclosingCircle(pts)
        M = cv2.moments(c)
        gx, gy = M["m10"] / max(M["m00"], 1), M["m01"] / max(M["m00"], 1)
        print(f"  hole{i}: area={ar:7.0f} n={len(pts):4d} bbox={cv2.boundingRect(c)} "
              f"fitEll c=({cx:6.1f},{cy:6.1f}) axes=({d1:5.1f},{d2:5.1f}) ang={ang:5.1f} "
              f"circ c=({ccx:6.1f},{ccy:6.1f}) r={rr:5.1f} centroid=({gx:6.1f},{gy:6.1f})")
        cv2.drawContours(vis, [c], -1, (0, 0, 255), 2)
        cv2.ellipse(vis, ((cx, cy), (d1, d2), ang), (0, 255, 0), 2)
        cv2.circle(vis, (int(cx), int(cy)), 4, (255, 0, 255), -1)

    cv2.imwrite(str(OUT / f"_hole_{a.seg}_f{a.idx}.png"), vis)
    print(f"wrote _hole_{a.seg}_f{a.idx}.png")


if __name__ == "__main__":
    main()
