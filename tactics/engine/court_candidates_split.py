#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.26 候选线 A/B/C 分离对照图：同一条带重复 3 次，每次只画一条候选线。
避免多线叠加导致"到底哪条对"分不清。
用法: court_candidates_split.py --seg ep24_s1 --idx 70
      --specs "150:260:640:1280"   (y0:y1:x0:x1)
      --lines "0.074:137.6,0.0:185.0,-0.0081:192.2"
      --labels "A:slope+0.074,B:flat,C:slope-0.008"
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
    ap.add_argument("--specs", default="150:260:640:1280")
    ap.add_argument("--lines", default="0.074:137.6,0.0:185.0,-0.0081:192.2")
    ap.add_argument("--labels", default="A,B,C")
    ap.add_argument("--grid", type=int, default=25)
    ap.add_argument("--tag", default="cand_split")
    ap.add_argument("--vlines", default="", help="竖线 x=m*y+c，逗号分隔（与 --lines 二选一）")
    a = ap.parse_args()

    if a.img == "FRAME":
        files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
        img = cv2.imread(str(files[a.idx]))
    else:
        img = cv2.imread(str(a.img))
    H, W = img.shape[:2]
    y0, y1, x0, x1 = [int(v) for v in a.specs.split(":")]
    y0, y1 = max(0, y0), min(H, y1)
    x0, x1 = max(0, x0), min(W, x1)
    cw, ch = x1 - x0, y1 - y0
    HDR = 34

    specs = a.lines.split(",")
    labels = a.labels.split(";") if ";" in a.labels else a.labels.split(",")
    use_v = bool(a.vlines)
    if use_v:
        specs = a.vlines.split(",")
    canvas = np.zeros((len(specs) * (ch + HDR), cw, 3), np.uint8)
    cols = [(0, 0, 255), (0, 200, 255), (255, 0, 255)]  # BGR: red / orange / magenta

    for k, spec in enumerate(specs):
        aa, bb = [float(v) for v in spec.split(":")]
        crop = img[y0:y1, x0:x1].copy()
        # 网格（绝对坐标标注）
        if a.grid:
            for y in range(((y0 + a.grid - 1) // a.grid) * a.grid, y1, a.grid):
                yy = y - y0
                cv2.line(crop, (0, yy), (cw, yy), (0, 0, 140), 1)
                cv2.putText(crop, str(y), (3, yy + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3)
                cv2.putText(crop, str(y), (3, yy + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 120, 255), 1)
            for x in range(((x0 + 100 - 1) // 100) * 100, x1, 100):
                xx = x - x0
                cv2.line(crop, (xx, 0), (xx, ch), (0, 120, 0), 1)
                cv2.putText(crop, str(x), (xx + 3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3)
                cv2.putText(crop, str(x), (xx + 3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 220, 0), 1)
        # 直线 → 局部裁剪坐标
        if use_v:   # 竖线 x = a*y + b
            p0 = (int(round(aa * y0 + bb)) - x0, 0)
            p1 = (int(round(aa * y1 + bb)) - x0, ch)
        else:       # 水平 y = a*x + b
            p0 = (0 - x0, int(round(aa * x0 + bb)) - y0)
            p1 = ((W - 1) - x0, int(round(aa * (W - 1) + bb)) - y0)
        cv2.line(crop, p0, p1, (0, 0, 0), 7)
        cv2.line(crop, p0, p1, cols[k % 3], 3)
        # 表头
        cv2.rectangle(canvas, (0, k * (ch + HDR)), (cw, k * (ch + HDR) + HDR), (40, 40, 40), -1)
        if use_v:
            txt = f"[{labels[k]}]  x = {aa:.4f} y + {bb:.1f}   (x@200={aa*200+bb:.0f}, x@500={aa*500+bb:.0f})"
        else:
            txt = f"[{labels[k]}]  y = {aa:.4f} x + {bb:.1f}   (y@640={aa*640+bb:.1f}, y@1280={aa*1280+bb:.1f})"
        cv2.putText(canvas, txt, (8, k * (ch + HDR) + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                    cols[k % 3], 2)
        canvas[k * (ch + HDR) + HDR: k * (ch + HDR) + HDR + ch, :] = crop

    op = OUT / f"{a.tag}_{a.specs.replace(':','-')}.png"
    cv2.imwrite(str(op), canvas)
    print(f"-> {op}  ({cw}x{canvas.shape[0]})")


if __name__ == "__main__":
    main()
