#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.23c 原生分辨率象限裁剪（Read 工具宽 >640 会压缩，故切 640 宽）。
用法: court_quad_crop.py --seg ep24_s1 --idx 70 [--lines "a:b,a:b"] [--grid]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--lines", default="")
    ap.add_argument("--grid", type=int, default=0)
    ap.add_argument("--img", default="")
    ap.add_argument("--tag", default="q")
    a = ap.parse_args()

    if a.img:
        img = cv2.imread(str(a.img))
    else:
        files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
        img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    vis = img.copy()

    if a.grid:
        for y in range(0, H, a.grid):
            cv2.line(vis, (0, y), (W, y), (0, 0, 255), 1)
            cv2.putText(vis, str(y), (3, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
            cv2.putText(vis, str(y), (3, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
        for x in range(0, W, a.grid):
            cv2.line(vis, (x, 0), (x, H), (0, 200, 0), 1)
            cv2.putText(vis, str(x), (x + 2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
            cv2.putText(vis, str(x), (x + 2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 0), 1)

    if a.lines:
        cols = [(255, 0, 0), (0, 200, 255), (255, 0, 255), (0, 120, 255), (180, 0, 255), (0, 255, 0)]
        for i, spec in enumerate(a.lines.split(",")):
            aa, bb = [float(v) for v in spec.split(":")]
            cv2.line(vis, (0, int(round(bb))), (W - 1, int(round(aa * (W - 1) + bb))), (0, 0, 0), 7)
            cv2.line(vis, (0, int(round(bb))), (W - 1, int(round(aa * (W - 1) + bb))), cols[i % len(cols)], 3)

    # 陡线 x = m*y + c (a=x-per-y, b=intercept)
    # 4 象限 640x360
    quads = [("TL", 0, 0), ("TR", 640, 0), ("BL", 0, 360), ("BR", 640, 360)]
    for name, x0, y0 in quads:
        crop = vis[y0:y0 + 360, x0:x0 + 640].copy()
        op = OUT / f"_see_{a.tag}_{name}_f{a.idx}.png"
        cv2.imwrite(str(op), crop)
        print(f"-> {op}")


if __name__ == "__main__":
    main()
