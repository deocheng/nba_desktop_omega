#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""放大 + 带**原图坐标**标尺的裁剪工具 —— 供人工读点（人工锚点流程的入口）。

为什么要这个：任何"人工锚点"流程的前提是**人能读出准确像素坐标**。
缩略图上估读的误差可达 ±30px，直接毁掉单应初值。本工具把区域放大后在
边缘画出**原图绝对坐标**刻度（不是裁剪后的局部坐标），所以读出来的数字可直接用。

用法:
  python engine/zoom_grid.py --img x.jpg --box 0 0 960 540 --scale 2 --step 50
  # 多点批量：--box "0 0 960 540" --box "960 0 1920 540"
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

MS = Path(str(tactics_data_file("reports/milestone_05/measure")))


def annotate(img, box, scale, step):
    x0, y0, x1, y1 = box
    x0 = max(0, x0); y0 = max(0, y0)
    x1 = min(img.shape[1], x1); y1 = min(img.shape[0], y1)
    crop = img[y0:y1, x0:x1].copy()
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    # 原图坐标网格
    for x in range(int(np.ceil(x0 / step) * step), x1 + 1, step):
        px = int((x - x0) * scale)
        if 0 <= px < crop.shape[1]:
            cv2.line(crop, (px, 0), (px, crop.shape[0]), (0, 140, 255), 1)
            cv2.putText(crop, str(x), (px + 3, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (0, 200, 255), 1, cv2.LINE_AA)
    for y in range(int(np.ceil(y0 / step) * step), y1 + 1, step):
        py = int((y - y0) * scale)
        if 0 <= py < crop.shape[0]:
            cv2.line(crop, (0, py), (crop.shape[1], py), (0, 140, 255), 1)
            cv2.putText(crop, str(y), (3, py + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (0, 200, 255), 1, cv2.LINE_AA)
    cv2.rectangle(crop, (0, 0), (crop.shape[1] - 1, crop.shape[0] - 1), (255, 255, 255), 2)
    return crop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--box", action="append", required=True, nargs=4, type=int)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--step", type=int, default=50)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    img = cv2.imread(a.img)
    if img is None:
        raise SystemExit("读不到图像")
    tiles = [annotate(img, tuple(b), a.scale, a.step) for b in a.box]
    h = max(t.shape[0] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 8, cv2.BORDER_CONSTANT,
                                value=(30, 30, 30)) for t in tiles]
    out = a.out or str(MS / f"zoomgrid_{Path(a.img).stem}.jpg")
    cv2.imwrite(out, np.concatenate(tiles, axis=1), [cv2.IMWRITE_JPEG_QUALITY, 94])
    print(f"[out] {out}")


if __name__ == "__main__":
    main()
