#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给帧画坐标网格（用于人工锚定场地标定点）。

用法:
  python engine/geom_frame_grid.py --window w1 --frame f00001.jpg --step 100
  python engine/geom_frame_grid.py --window w1 --frame f00001.jpg --out /tmp/g.jpg --grid-crop x1 y1 x2 y2

设计意图：读图者（多模态）需要把"看到的地标"翻译成像素坐标，必须有编号网格。
网格：每 step px 一条线，主线（每 4*step）加粗并标像素值。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
from pathlib import Path

import cv2

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", required=True)
    ap.add_argument("--frame", required=True)
    ap.add_argument("--step", type=int, default=100)
    ap.add_argument("--major", type=int, default=4, help="每 n 条画粗线并标数值")
    ap.add_argument("--out", default=None)
    ap.add_argument("--grid-crop", nargs=4, type=int, default=None,
                    help="只在此区域画密网格 x1 y1 x2 y2")
    ap.add_argument("--scale", type=float, default=1.0, help="输出缩放")
    a = ap.parse_args()

    p = AW / a.window / a.frame
    img = cv2.imread(str(p))
    if img is None:
        raise SystemExit(f"读不到 {p}")
    H, W = img.shape[:2]
    ov = img.copy()
    step = a.step

    if a.grid_crop:
        x1, y1, x2, y2 = a.grid_crop
    else:
        x1, y1, x2, y2 = 0, 0, W, H

    for x in range(0, W + 1, step):
        if not (x1 <= x <= x2):
            continue
        major = (x // step) % a.major == 0
        col = (0, 0, 255) if major else (0, 200, 255)
        cv2.line(img, (x, y1), (x, y2), col, 2 if major else 1)
        if major:
            cv2.putText(img, str(x), (x + 3, y1 + 18), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 0, 255), 1, cv2.LINE_AA)
            cv2.putText(img, str(x), (x + 3, y2 - 6), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 0, 255), 1, cv2.LINE_AA)
    for y in range(0, H + 1, step):
        if not (y1 <= y <= y2):
            continue
        major = (y // step) % a.major == 0
        col = (0, 0, 255) if major else (0, 200, 255)
        cv2.line(img, (x1, y), (x2, y), col, 2 if major else 1)
        if major:
            cv2.putText(img, str(y), (x1 + 3, y - 4), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 0, 255), 1, cv2.LINE_AA)
            cv2.putText(img, str(y), (x2 - 62, y - 4), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 0, 255), 1, cv2.LINE_AA)

    out = a.out or str(AW / f"grid_{a.window}_{Path(a.frame).stem}.jpg")
    if a.scale != 1.0:
        img = cv2.resize(img, None, fx=a.scale, fy=a.scale, interpolation=cv2.INTER_AREA)
    cv2.imwrite(out, img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"[out] {out}  ({img.shape[1]}x{img.shape[0]})  源 {W}x{H}")


if __name__ == "__main__":
    main()
