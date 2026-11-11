#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.27d 原始帧左端 2x 放大（无线条），找真实底线/三分线。"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import glob
from pathlib import Path

import cv2

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"


def zoom(seg, idx, y0, y1, x0, x1, tag, scale=2):
    fs = sorted(glob.glob(str(SEGD / seg / "frames" / "f*.jpg")))
    im = cv2.imread(fs[idx])
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
    cv2.imwrite(str(OUT / f"_see_{tag}.png"), crop)
    print("->", tag, crop.shape)


zoom("ep24_s1", 70, 150, 460, 100, 360, "rawz_bl_2x")
zoom("ep24_s1", 70, 120, 320, 300, 640, "rawz_top_2x")
zoom("ep24_s1", 70, 260, 480, 220, 640, "rawz_ft_2x")
zoom("ep24_s1", 70, 240, 470, 180, 460, "rawz_key_2x")
