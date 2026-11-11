#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.27e 真实紫色油漆区掩膜形状 + 行/列边界，判断油漆区左/右/上/下真实走向。"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import glob
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"

seg, idx = "ep24_s1", 70
fs = sorted(glob.glob(str(SEGD / seg / "frames" / "f*.jpg")))
img = cv2.imread(fs[idx])
H, W = img.shape[:2]
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
raw = cv2.inRange(hsv, np.array([110, 60, 70]), np.array([170, 255, 255]))
m = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((31, 31), np.uint8))
n, lab, st, _ = cv2.connectedComponentsWithStats(m)
b = 1 + int(np.argmax(st[1:, 4]))
mask = np.where(lab == b, 255, 0).astype(np.uint8)
print("largest CC bbox:", st[b].tolist(), "area:", int(st[b, 4]))
ys, xs = np.where(mask > 0)
print("mask x range", xs.min(), xs.max(), " y range", ys.min(), ys.max())

vis = img.copy()
vis[mask > 0] = (0.6 * vis[mask > 0] + 0.4 * np.array([0, 255, 0])).astype(np.uint8)
cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
cv2.drawContours(vis, cs, -1, (0, 255, 255), 2)
hull = cv2.convexHull(np.vstack(cs))
cv2.polylines(vis, [hull], True, (255, 0, 255), 2)


def vline(im, mm, cc, col, th=3):
    cv2.line(im, (int(cc), 0), (int(mm * (H - 1) + cc), H - 1), col, th)


vline(vis, -0.0710, 242.9, (0, 0, 255))    # B red
vline(vis, -1.0124, 598.3, (255, 0, 255))  # C magenta
cv2.imwrite(str(OUT / "_chk_purplemask.png"), vis)

# per-row left/right edge of the mask
print("\nrow  lx   rx   (purple mask)")
for y in range(200, 500, 20):
    row = np.where(mask[y] > 0)[0]
    if len(row):
        print(f"{y:4d} {row.min():4d} {row.max():4d}")
    else:
        print(f"{y:4d}   --   --")

print("\ncol  ty   by   (purple mask)")
for x in range(200, 600, 20):
    col = np.where(mask[:, x] > 0)[0]
    if len(col):
        print(f"{x:4d} {col.min():4d} {col.max():4d}")
    else:
        print(f"{x:4d}   --   --")


def fitline(pts):
    pts = np.asarray(pts, float)
    if len(pts) < 2:
        return None
    A = np.vstack([pts[:, 0], np.ones(len(pts))]).T
    sol, *_ = np.linalg.lstsq(A, pts[:, 1], rcond=None)
    return float(sol[0]), float(sol[1])


# left edge rows 300-385 ; right edge rows 375-435 ; top cols 315-575 ; bottom cols 245-525
rows_l = [(y, np.where(mask[y] > 0)[0].min()) for y in range(300, 386) if mask[y].any()]
rows_r = [(y, np.where(mask[y] > 0)[0].max()) for y in range(375, 436) if mask[y].any()]
cols_t = [(x, np.where(mask[:, x] > 0)[0].min()) for x in range(315, 576) if mask[:, x].any()]
cols_b = [(x, np.where(mask[:, x] > 0)[0].max()) for x in range(245, 526) if mask[:, x].any()]
# left/right: x = m*y + c ; top/bottom: y = a*x + b
fl = fitline([(y, x) for y, x in rows_l]); print("\nleft  x=m*y+c :", fl, "n=", len(rows_l))
fr = fitline([(y, x) for y, x in rows_r]); print("right x=m*y+c :", fr, "n=", len(rows_r))
ft = fitline(cols_t); print("top   y=a*x+b :", ft, "n=", len(cols_t))
fb = fitline(cols_b); print("bot   y=a*x+b :", fb, "n=", len(cols_b))


def inter_vh(m, c, a, b):  # x=m*y+c  and  y=a*x+b
    y = (a * c + b) / (1 - a * m)
    return (m * y + c, y)


if all(v is not None for v in (fl, fr, ft, fb)):
    TL = inter_vh(*fl, *ft); TR = inter_vh(*fr, *ft)
    BR = inter_vh(*fr, *fb); BL = inter_vh(*fl, *fb)
    print("\ncorners TL TR BR BL:")
    for nm, p in [("TL", TL), ("TR", TR), ("BR", BR), ("BL", BL)]:
        print(f"  {nm} = ({p[0]:.1f}, {p[1]:.1f})")

for y0, y1, x0, x1, tag, sc in [(200, 520, 150, 660, "pm_2x", 1)]:
    crop = vis[y0:y1, x0:x1].copy()
    if sc != 1:
        crop = cv2.resize(crop, None, fx=sc, fy=sc, interpolation=cv2.INTER_NEAREST)
    for y in range((y0 // 50 + 1) * 50, y1, 50):
        yy = (y - y0) * sc
        cv2.line(crop, (0, yy), (crop.shape[1], yy), (0, 0, 255), 1)
        cv2.putText(crop, str(y), (2, yy + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    for x in range((x0 // 50 + 1) * 50, x1, 50):
        xx = (x - x0) * sc
        cv2.line(crop, (xx, 0), (xx, crop.shape[0]), (0, 255, 0), 1)
        cv2.putText(crop, str(x), (xx + 2, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.imwrite(str(OUT / f"_chk_{tag}.png"), crop)
    print("->", tag, crop.shape)
