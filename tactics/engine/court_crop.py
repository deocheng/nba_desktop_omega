#!/usr/bin/env python3
"""court_crop.py — 通用原生分辨率裁剪/放大工具（诊断用）。
用法:
  python3 court_crop.py IN OUT --box x0,y0,x1,y1 [--scale 2] [--grid 25] [--vlines "m:c,..."] [--hlines "m:c,..."]
每张图一次调用（勿在同条 Bash 里串联多个 $P）。
"""
import argparse
import os
import sys

import cv2
import numpy as np


def parse_pairs(s):
    out = []
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        a, b = tok.split(":")
        out.append((float(a), float(b)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--box", required=True, help="x0,y0,x1,y1")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--grid", type=float, default=0.0, help="网格间距(原始像素)")
    ap.add_argument("--vlines", default="", help="竖线 x=m*y+c 列表")
    ap.add_argument("--hlines", default="", help="横线 y=m*x+c 列表")
    ap.add_argument("--labels", default="", help="; 或 , 分隔的标签")
    a = ap.parse_args()

    img = cv2.imread(a.inp, cv2.IMREAD_COLOR)
    if img is None:
        print("ERR: cannot read", a.inp, file=sys.stderr)
        sys.exit(1)
    H, W = img.shape[:2]
    x0, y0, x1, y1 = [int(v) for v in a.box.split(",")]
    x0 = max(0, x0); y0 = max(0, y0); x1 = min(W, x1); y1 = min(H, y1)
    crop = img[y0:y1, x0:x1].copy()
    ch, cw = crop.shape[:2]

    # overlay lines (in original coords)
    if a.vlines:
        for i, (m, c) in enumerate(parse_pairs(a.vlines)):
            ys = np.array([y0, y1 - 1], float)
            xs = m * ys + c
            pts = np.stack([xs - x0, ys - y0], 1)
            col = [(0, 0, 255), (0, 255, 255), (255, 0, 255), (0, 255, 0)][i % 4]
            cv2.polylines(crop, [np.int32(pts)], False, col, 1)
    if a.hlines:
        for i, (m, c) in enumerate(parse_pairs(a.hlines)):
            xs = np.array([x0, x1 - 1], float)
            ys = m * xs + c
            pts = np.stack([xs - x0, ys - y0], 1)
            col = [(0, 0, 255), (0, 255, 255), (255, 0, 255), (0, 255, 0)][i % 4]
            cv2.polylines(crop, [np.int32(pts)], False, col, 1)

    if a.scale != 1.0:
        crop = cv2.resize(crop, (int(round(cw * a.scale)), int(round(ch * a.scale))),
                          interpolation=cv2.INTER_NEAREST if a.scale > 1 else cv2.INTER_AREA)
    ch2, cw2 = crop.shape[:2]

    if a.grid > 0:
        g = a.grid * a.scale
        for gx in np.arange(0, cw2, g):
            cv2.line(crop, (int(gx), 0), (int(gx), ch2), (0, 140, 0), 1)
        for gy in np.arange(0, ch2, g):
            cv2.line(crop, (0, int(gy)), (cw2, int(gy)), (0, 140, 0), 1)

    # corner coordinate label (original coords of the crop origin)
    cv2.putText(crop, f"({x0},{y0})-({x1},{y1}) x{a.scale}", (6, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(crop, f"({x0},{y0})-({x1},{y1}) x{a.scale}", (6, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)

    cv2.imwrite(a.out, crop)
    print(f"wrote {a.out}  srcbox=({x0},{y0},{x1},{y1}) -> {cw2}x{ch2} scale={a.scale}")


if __name__ == "__main__":
    main()
