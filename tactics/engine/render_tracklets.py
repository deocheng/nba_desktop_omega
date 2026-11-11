#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.52 视觉自证: 把球 tracklet 折线画到帧上, 检验轨迹形状是否像真实球运动。

出数字前必须复述画面(纪律)。每条 tracklet 取其**首帧**整图(1080p 缩放), 叠加:
  - 该 tracklet 的球心折线(实测点, 不插值)
  - 起点/终点标记 + 平均直径 + 长度(帧)
选最长的 N 条排成 montage。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
CLIP = sys.argv[1] if len(sys.argv) > 1 else "sas_det"
TOPN = int(sys.argv[2]) if len(sys.argv) > 2 else 6
SRC = AW / CLIP / f"{CLIP}_ball_tracklets.json" if not (AW / "validate" / f"{CLIP}_ball_tracklets.json").exists() \
    else AW / "validate" / f"{CLIP}_ball_tracklets.json"
OUT = AW / "validate" / f"a4_52_{CLIP}_ball_tracklets.png"

tl = json.loads(SRC.read_text())["tracklets"]
tl.sort(key=lambda t: -t["n"])
sel = tl[:TOPN]
FR = AW / CLIP

COLS = 2
CW, CH = 640, 380
rows = (len(sel) + COLS - 1) // COLS
sheet = np.full((rows * CH + 40, COLS * CW + 20, 3), 30, np.uint8)

for i, t in enumerate(sel):
    f0 = t["frames"][0]
    img = cv2.imread(str(FR / f"f{f0:05d}.jpg"))
    if img is None:
        continue
    r, c = divmod(i, COLS)
    pts = [(int(round(x)), int(round(y))) for x, y in t["pts"]]
    d = int(round(t["mean_diag"]))
    for j in range(1, len(pts)):
        cv2.line(img, pts[j - 1], pts[j], (0, 255, 255), 2)
    for j, p in enumerate(pts):
        col = (0, 255, 0) if j == 0 else ((0, 0, 255) if j == len(pts) - 1 else (255, 255, 0))
        cv2.circle(img, p, 4 if j in (0, len(pts) - 1) else 3, col, -1)
    cv2.circle(img, pts[0], max(6, d // 2), (0, 255, 0), 2)
    img = cv2.resize(img, (CW, CH))
    cv2.putText(img, f"tid#{i} start=f{f0:05d} n={t['n']} diag={d}px prob={t['mean_prob']:.2f}",
                (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
    y0, x0 = r * CH + 30, c * CW + 10
    sheet[y0:y0 + CH, x0:x0 + CW] = img

cv2.putText(sheet, "ball tracklets (measured points only, NO interpolation): green=start circle=ball size, red=end",
            (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
OUT.parent.mkdir(exist_ok=True)
cv2.imwrite(str(OUT), sheet)
print(f"saved {OUT}")
for i, t in enumerate(sel):
    print(f"  #{i} start=f{t['frames'][0]:05d} n={t['n']} frames={t['frames'][:6]}{'...' if t['n']>6 else ''} "
          f"diag={t['mean_diag']} prob={t['mean_prob']}")
