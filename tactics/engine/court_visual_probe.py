#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.23 视觉基准图：给原始帧加像素刻度 + 横向条带放大图。
老程要求「基于视觉判断」⇒ 先给出可读坐标的原始图，再据目视定边线。
用法: court_visual_probe.py --seg ep24_s1 --idx 70
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
    ap.add_argument("--lines", default="", help="逗号分隔的 a,b 直线 y=a*x+b，画到图上")
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]

    vis = img.copy()
    for y in range(0, H, 50):
        cv2.line(vis, (0, y), (W, y), (0, 0, 255), 1)
        cv2.putText(vis, f"y{y}", (4, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
        cv2.putText(vis, f"y{y}", (4, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    for x in range(0, W, 100):
        cv2.line(vis, (x, 0), (x, H), (0, 200, 0), 1)
        cv2.putText(vis, f"x{x}", (x + 2, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
        cv2.putText(vis, f"x{x}", (x + 2, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 0), 1)

    if a.lines:
        cols = [(255, 60, 0), (0, 215, 255), (255, 0, 255), (0, 140, 255), (180, 0, 255)]
        for i, spec in enumerate(a.lines.split(",")):
            aa, bb = [float(v) for v in spec.split(":")]
            p1 = (0, int(round(bb)))
            p2 = (W - 1, int(round(aa * (W - 1) + bb)))
            cv2.line(vis, p1, p2, (0, 0, 0), 6)
            cv2.line(vis, p1, p2, cols[i % len(cols)], 3)
            cv2.putText(vis, f"L{i} a={aa:.4f} b={bb:.1f}", (10, 40 + i * 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
            cv2.putText(vis, f"L{i} a={aa:.4f} b={bb:.1f}", (10, 40 + i * 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, cols[i % len(cols)], 2)

    op = OUT / f"_see_ruler_f{a.idx}.png"
    cv2.imwrite(str(op), vis)
    print(f"-> {op}")

    # 横向条带放大（看清真实白线）
    bands = [("top", 60, 280), ("low", 400, 620), ("bot", 540, 720)]
    for name, y0, y1 in bands:
        y0, y1 = max(0, y0), min(H, y1)
        crop = vis[y0:y1, :].copy()
        z = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        for y in range(y0, y1 + 1, 20):
            yy = int((y - y0) * 2.0)
            if yy >= z.shape[0]:
                break
            cv2.line(z, (0, yy), (z.shape[1], yy), (0, 0, 255), 1)
            cv2.putText(z, str(y), (2, yy + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
            cv2.putText(z, str(y), (2, yy + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        cv2.imwrite(str(OUT / f"_see_band_{name}_f{a.idx}.png"), z)
        print(f"-> _see_band_{name}_f{a.idx}.png")


if __name__ == "__main__":
    main()
