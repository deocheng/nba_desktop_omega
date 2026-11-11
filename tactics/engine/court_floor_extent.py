#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.23d 逐列量地板(木色∪紫漆∪白线)上下沿，打印数字，判断真实边线位置。
用法: court_floor_extent.py --seg ep24_s1 --idx 70
"""
from __future__ import annotations

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
WOOD_LO, WOOD_HI = (5, 30, 120), (40, 255, 255)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--y0", type=int, default=60)
    ap.add_argument("--y1", type=int, default=700)
    a = ap.parse_args()

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, WOOD_LO, WOOD_HI) > 0
    # 只保留较长连续段(>=12px)的像元，去掉零散误检
    m2 = np.zeros_like(m)
    for x in range(W):
        col = m[a.y0:a.y1, x]
        # 找连续 run
        idx = np.where(col)[0]
        if len(idx) == 0:
            continue
        runs = []
        s = idx[0]; p = idx[0]
        for v in idx[1:]:
            if v == p + 1:
                p = v
            else:
                runs.append((s, p)); s = v; p = v
        runs.append((s, p))
        for (s, p) in runs:
            if p - s + 1 >= 12:
                m2[a.y0 + s:a.y0 + p + 1, x] = True

    vis = img.copy()
    print(f"=== {a.seg} f{a.idx} 逐列地板上下沿 (y in [{a.y0},{a.y1}]) ===")
    print(f"{'x':>5} {'top':>6} {'bot':>6} {'h':>5}")
    tops, bots = [], []
    for x in range(0, W, 80):
        col = np.where(m2[:, x])[0]
        if len(col) < 5:
            print(f"{x:>5} {'--':>6} {'--':>6}")
            continue
        t, b = int(col.min()), int(col.max())
        tops.append((x, t)); bots.append((x, b))
        print(f"{x:>5} {t:>6} {b:>6} {b-t:>5}")
        cv2.circle(vis, (x, t), 5, (0, 0, 255), -1)
        cv2.circle(vis, (x, b), 5, (255, 0, 0), -1)
    if len(tops) >= 2:
        at, bt = np.polyfit([p[0] for p in tops], [p[1] for p in tops], 1)
        ab, bb = np.polyfit([p[0] for p in bots], [p[1] for p in bots], 1)
        print(f"  top 拟合: y={at:.4f}x+{bt:.1f}  (y@640={at*640+bt:.1f})")
        print(f"  bot 拟合: y={ab:.4f}x+{bb:.1f}  (y@640={ab*640+bb:.1f})")
        cv2.line(vis, (0, int(bt)), (W - 1, int(at * (W - 1) + bt)), (0, 0, 255), 3)
        cv2.line(vis, (0, int(bb)), (W - 1, int(ab * (W - 1) + bb)), (255, 0, 0), 3)
    ov = vis.copy(); ov[m2] = (0, 200, 100)
    vis = cv2.addWeighted(ov, 0.25, vis, 0.75, 0)
    op = OUT / f"_see_floorextent_f{a.idx}.png"
    cv2.imwrite(str(op), vis)
    print(f"-> {op}")


if __name__ == "__main__":
    main()
