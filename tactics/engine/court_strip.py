#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.23f 任意矩形条带原生裁剪（宽<=640 才不被 Read 压缩）。
用法: court_strip.py --img <path|FRAME> --specs "y0:y1:x0:x1,..." [--grid 20] [--lines "..."]
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
    ap.add_argument("--img", default="FRAME")
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--specs", required=True, help="y0:y1:x0:x1, 逗号分隔多组")
    ap.add_argument("--grid", type=int, default=0)
    ap.add_argument("--lines", default="", help="水平线 a:b (y=a*x+b)")
    ap.add_argument("--vlines", default="", help="陡线 x=m*y+c")
    ap.add_argument("--tag", default="strip")
    a = ap.parse_args()

    if a.img == "FRAME":
        files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
        img = cv2.imread(str(files[a.idx]))
    else:
        img = cv2.imread(str(a.img))
    H, W = img.shape[:2]
    vis = img.copy()

    if a.lines:
        cols = [(255, 0, 0), (0, 200, 255), (255, 0, 255), (0, 120, 255), (180, 0, 255), (0, 255, 0)]
        for i, spec in enumerate(a.lines.split(",")):
            aa, bb = [float(v) for v in spec.split(":")]
            cv2.line(vis, (0, int(bb)), (W - 1, int(round(aa * (W - 1) + bb))), (0, 0, 0), 7)
            cv2.line(vis, (0, int(bb)), (W - 1, int(round(aa * (W - 1) + bb))), cols[i % len(cols)], 3)
    if a.vlines:
        for i, spec in enumerate(a.vlines.split(",")):
            m, c = [float(v) for v in spec.split(":")]
            cv2.line(vis, (int(c), 0), (int(m * (H - 1) + c), H - 1), (0, 0, 0), 7)
            cv2.line(vis, (int(c), 0), (int(m * (H - 1) + c), H - 1), (0, 255, 0), 3)

    for k, spec in enumerate(a.specs.split(",")):
        y0, y1, x0, x1 = [int(v) for v in spec.split(":")]
        y0, y1 = max(0, y0), min(H, y1)
        x0, x1 = max(0, x0), min(W, x1)
        crop = vis[y0:y1, x0:x1].copy()
        if a.grid:
            for y in range(((y0 + a.grid - 1) // a.grid) * a.grid, y1, a.grid):
                yy = y - y0
                cv2.line(crop, (0, yy), (crop.shape[1], yy), (0, 0, 255), 1)
                cv2.putText(crop, str(y), (2, yy + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3)
                cv2.putText(crop, str(y), (2, yy + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 255), 1)
            for x in range(((x0 + 100 - 1) // 100) * 100, x1, 100):
                xx = x - x0
                cv2.line(crop, (xx, 0), (xx, crop.shape[0]), (0, 200, 0), 1)
                cv2.putText(crop, str(x), (xx + 2, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3)
                cv2.putText(crop, str(x), (xx + 2, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 220, 0), 1)
        op = OUT / f"_see_{a.tag}_{k}_y{y0}-{y1}_x{x0}-{x1}.png"
        cv2.imwrite(str(op), crop)
        print(f"-> {op}")


if __name__ == "__main__":
    main()
