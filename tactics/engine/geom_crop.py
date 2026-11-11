#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""裁剪帧的指定区域并放大（用于精读场地线、锚定标定点）。

用法:
  python engine/geom_crop.py --window w1 --frame f00001.jpg --box 0 0 960 540 --out /tmp/c1.jpg
  python engine/geom_crop.py --window w1 --frame f00001.jpg --box 300 500 900 900 --zoom 1.6 --grid 50
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
    ap.add_argument("--box", nargs=4, type=int, required=True, help="x1 y1 x2 y2")
    ap.add_argument("--zoom", type=float, default=1.0)
    ap.add_argument("--grid", type=int, default=0, help="在该区域内画 grid px 密网格")
    ap.add_argument("--out", default="/tmp/crop.jpg")
    a = ap.parse_args()

    img = cv2.imread(str(AW / a.window / a.frame))
    if img is None:
        raise SystemExit("读不到帧")
    x1, y1, x2, y2 = a.box
    c = img[y1:y2, x1:x2].copy()

    if a.grid:
        for x in range(0, c.shape[1], a.grid):
            major = (x % (a.grid * 4) == 0)
            cv2.line(c, (x, 0), (x, c.shape[0]), (0, 0, 255) if major else (0, 220, 255),
                     2 if major else 1)
            if major:
                cv2.putText(c, str(x + x1), (x + 2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                            (0, 0, 255), 1, cv2.LINE_AA)
                cv2.putText(c, str(x + x1), (x + 2, c.shape[0] - 4), cv2.FONT_HERSHEY_SIMPLEX,
                            0.4, (0, 0, 255), 1, cv2.LINE_AA)
        for y in range(0, c.shape[0], a.grid):
            major = (y % (a.grid * 4) == 0)
            cv2.line(c, (0, y), (c.shape[1], y), (0, 0, 255) if major else (0, 220, 255),
                     2 if major else 1)
            if major:
                cv2.putText(c, str(y + y1), (2, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                            (0, 0, 255), 1, cv2.LINE_AA)
                cv2.putText(c, str(y + y1), (c.shape[1] - 52, y - 3), cv2.FONT_HERSHEY_SIMPLEX,
                            0.4, (0, 0, 255), 1, cv2.LINE_AA)

    if a.zoom != 1.0:
        c = cv2.resize(c, None, fx=a.zoom, fy=a.zoom, interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(a.out, c, [cv2.IMWRITE_JPEG_QUALITY, 94])
    print(f"[out] {a.out}  {c.shape[1]}x{c.shape[0]}  源区域 {a.box}")


if __name__ == "__main__":
    main()
