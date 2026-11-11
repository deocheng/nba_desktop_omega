#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.27c 底线候选 A/B/C 一次性叠加在原始帧上 + 检测油漆区，原生裁剪目视。
A red / B yellow / C magenta ; far sideline green ; paint quad cyan。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import glob
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))
import court_model_v8 as V  # noqa: E402

seg, idx = "ep24_s1", 70
fs = sorted(glob.glob(str(SEGD / seg / "frames" / "f*.jpg")))
img = cv2.imread(fs[idx])
H, W = img.shape[:2]
base = img.copy()


def vline(im, m, c, col, th=4):
    cv2.line(im, (int(c), 0), (int(m * (H - 1) + c), H - 1), (0, 0, 0), th + 4)
    cv2.line(im, (int(c), 0), (int(m * (H - 1) + c), H - 1), col, th)


def hline(im, a, b, col, th=4):
    cv2.line(im, (0, int(b)), (W - 1, int(round(a * (W - 1) + b))), (0, 0, 0), th + 4)
    cv2.line(im, (0, int(b)), (W - 1, int(round(a * (W - 1) + b))), col, th)


vline(base, -0.8570, 454.8, (0, 0, 255))     # A red
vline(base, -0.0710, 242.9, (0, 255, 255))   # B yellow
vline(base, -1.0124, 598.3, (255, 0, 255))   # C magenta
hline(base, 0.0740, 137.6, (0, 255, 0))      # far sideline green
q, mm = V.paint_quad(img)
if q is not None:
    cv2.polylines(base, [np.int32(np.asarray(q))], True, (255, 255, 0), 2)
    print("paint quad:", np.int32(q).tolist())
cv2.imwrite(str(OUT / "_chk_base_ABC.png"), base)


def gridcrop(im, y0, y1, x0, x1, tag):
    crop = im[y0:y1, x0:x1].copy()
    for y in range((y0 // 50 + 1) * 50, y1, 50):
        cv2.line(crop, (0, y - y0), (crop.shape[1], y - y0), (0, 0, 255), 1)
        cv2.putText(crop, str(y), (2, y - y0 + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    for x in range((x0 // 50 + 1) * 50, x1, 50):
        cv2.line(crop, (x - x0, 0), (x - x0, crop.shape[0]), (0, 255, 0), 1)
        cv2.putText(crop, str(x), (x - x0 + 2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.imwrite(str(OUT / f"_chk_{tag}.png"), crop)
    print("->", tag, crop.shape)


def zoomcrop(im, y0, y1, x0, x1, tag, scale=2):
    crop = im[y0:y1, x0:x1].copy()
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    for y in range((y0 // 50 + 1) * 50, y1, 50):
        yy = (y - y0) * scale
        cv2.line(crop, (0, yy), (crop.shape[1], yy), (0, 0, 255), 1)
        cv2.putText(crop, str(y), (2, yy + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
    for x in range((x0 // 50 + 1) * 50, x1, 50):
        xx = (x - x0) * scale
        cv2.line(crop, (xx, 0), (xx, crop.shape[0]), (0, 255, 0), 1)
        cv2.putText(crop, str(x), (xx + 2, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
    cv2.imwrite(str(OUT / f"_chk_{tag}.png"), crop)
    print("->", tag, crop.shape)


gridcrop(base, 100, 500, 100, 540, "base_ABC_L")
gridcrop(base, 380, 700, 0, 560, "base_ABC_dn")
zoomcrop(base, 120, 440, 150, 450, "base_ABC_zoom")
