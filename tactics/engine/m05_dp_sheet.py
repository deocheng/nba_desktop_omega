#!/usr/bin/env python3
"""DP 选定路径的目视验收接触表：只画 DP 选中的框，看它到底是不是球。
左上: frame conf  左下: T1=DP 选了原始 top1 / alt=选了非 top1
用法: m05_dp_sheet.py <window> <out.jpg> [--n 30] [--cols 6] [--cell 250] [--half 52]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))

ap = argparse.ArgumentParser()
ap.add_argument("window"); ap.add_argument("out")
ap.add_argument("--n", type=int, default=30); ap.add_argument("--cols", type=int, default=6)
ap.add_argument("--cell", type=int, default=250); ap.add_argument("--half", type=int, default=52)
a = ap.parse_args()
d = json.loads((AW / f"ball_dp_{a.window}.json").read_text())
rf = json.loads((AW / f"{a.window}_rfdetr.json").read_text())
fdir = AW / a.window
sel = [e for e in d["path"] if e["bbox"]]
print(f"DP 覆盖 {len(sel)}/{len(d['path'])}")
idx = np.linspace(0, len(sel) - 1, min(a.n, len(sel))).astype(int)
tiles = []
for j in idx:
    e = sel[j]
    img = cv2.imread(str(fdir / e["file"]))
    if img is None: continue
    bx1, by1, bx2, by2 = e["bbox"]; cx, cy = (bx1+bx2)/2, (by1+by2)/2
    h = a.half; x1, y1 = int(cx-h), int(cy-h)
    pad = np.zeros((2*h, 2*h, 3), np.uint8)
    sx1, sy1 = max(0,x1), max(0,y1)
    sx2, sy2 = min(img.shape[1], x1+2*h), min(img.shape[0], y1+2*h)
    if sx2>sx1 and sy2>sy1: pad[sy1-y1:sy2-y1, sx1-x1:sx2-x1] = img[sy1:sy2, sx1:sx2]
    t = cv2.resize(pad, (a.cell, a.cell), interpolation=cv2.INTER_CUBIC)
    k = a.cell/(2*h)
    cv2.rectangle(t, (int((bx1-x1)*k), int((by1-y1)*k)), (int((bx2-x1)*k), int((by2-y1)*k)), (0,255,0), 2)
    cv2.putText(t, f"{e['file'][1:6]} {e['conf']:.2f}", (3,16), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (0,255,255), 1)
    cs = rf.get(e["file"]) or []
    top = max(cs, key=lambda x: x["conf"]) if cs else None
    same = top is not None and abs(top["bbox"][0]-bx1) < 1.0
    cv2.putText(t, "T1" if same else "alt", (3, a.cell-8), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (255,255,0) if same else (0,140,255), 2)
    tiles.append(t)
rows=[]
for i in range(0, len(tiles), a.cols):
    r = tiles[i:i+a.cols]
    while len(r) < a.cols: r.append(np.zeros_like(tiles[0]))
    rows.append(np.hstack(r))
cv2.imwrite(a.out, np.vstack(rows)); print("[图]", a.out)
