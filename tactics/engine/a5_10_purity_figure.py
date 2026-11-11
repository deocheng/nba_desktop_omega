#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.10b 一张图讲清楚：纯净转播帧 vs 节目讲解帧（以及它如何污染检测）。"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
T = ROOT / "action_work" / "track_judge" / "topk"
OUT = T / "A5_10_pure_vs_program.png"

pairs = [
    ("cross_ep24_s1_f70.png", "纯净转播 (ep24_s1, 卡片帧 0%)"),
    ("cross_ep19_s0_f77.png", "节目讲解帧 (ep19_s0, 卡片帧 56%)"),
]
W = 900
panels = []
for fn, lab in pairs:
    im = cv2.imread(str(T / fn))
    if im is None:
        print("缺图", fn); continue
    im = cv2.resize(im, (W, int(W * im.shape[0] / im.shape[1])), interpolation=cv2.INTER_AREA)
    bar = np.full((70, W, 3), 245, np.uint8)
    cv2.putText(bar, lab, (16, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.35, (20, 20, 20), 3)
    panels.append(np.vstack([bar, im]))

if len(panels) == 2:
    h = min(p.shape[0] for p in panels)
    panels = [p[:h] for p in panels]
    sep = np.full((h, 14, 3), 255, np.uint8)
    sheet = np.hstack([panels[0], sep, panels[1]])
    head = np.full((96, sheet.shape[1], 3), 255, np.uint8)
    cv2.putText(head, "A5.10  177 个「实战片段」里 122 个(69%)混着节目讲解帧",
                (18, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.25, (0, 0, 200), 3)
    cv2.putText(head, "左: 真转播(检测框=场上球员)   右: 节目帧(检测框打在缩小画中画上, 每帧仍报 12 人)",
                (18, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (60, 60, 60), 2)
    sheet = np.vstack([head, sheet])
    cv2.imwrite(str(OUT), sheet)
    print("->", OUT)
