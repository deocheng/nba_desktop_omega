#!/usr/bin/env python3
"""任意检测 JSON 的配对目视接触表（同一批帧，上下两行对比两种配置）。
用法: m05_sheet_any.py <window> <out.jpg> <jsonA> [jsonB] [--n 18] [--cols 6] [--cell 240] [--half 50]
A 在上行、B 在下行；只画各自 top-1 球框。
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
ap.add_argument("window"); ap.add_argument("out"); ap.add_argument("jsonA")
ap.add_argument("jsonB", nargs="?", default=None)
ap.add_argument("--n", type=int, default=18); ap.add_argument("--cols", type=int, default=6)
ap.add_argument("--cell", type=int, default=240); ap.add_argument("--half", type=int, default=50)
a = ap.parse_args()
A = json.loads(Path(a.jsonA).read_text())
B = json.loads(Path(a.jsonB).read_text()) if a.jsonB else None
fdir = AW / a.window

def cell_img(fn, entry, tag, col):
    img = cv2.imread(str(fdir / fn))
    if img is None or not entry:
        return np.zeros((a.cell, a.cell, 3), np.uint8)
    b = entry[0]["bbox"] if isinstance(entry, list) else entry["bbox"]
    conf = entry[0]["conf"] if isinstance(entry, list) else entry.get("conf")
    bx1, by1, bx2, by2 = b; cx, cy = (bx1+bx2)/2, (by1+by2)/2
    h = a.half; x1, y1 = int(cx-h), int(cy-h)
    pad = np.zeros((2*h, 2*h, 3), np.uint8)
    sx1, sy1 = max(0, x1), max(0, y1)
    sx2, sy2 = min(img.shape[1], x1+2*h), min(img.shape[0], y1+2*h)
    if sx2 > sx1 and sy2 > sy1:
        pad[sy1-y1:sy2-y1, sx1-x1:sx2-x1] = img[sy1:sy2, sx1:sx2]
    t = cv2.resize(pad, (a.cell, a.cell), interpolation=cv2.INTER_CUBIC)
    k = a.cell/(2*h)
    cv2.rectangle(t, (int((bx1-x1)*k), int((by1-y1)*k)), (int((bx2-x1)*k), int((by2-y1)*k)), col, 2)
    cv2.putText(t, f"{tag} {fn[1:6]} {conf:.2f}", (3, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (0, 255, 255), 1)
    return t

keys = [k for k in sorted(A) if A[k]]
if B:
    keys2 = [k for k in sorted(B) if B[k]]
    keys = [k for k in keys if k in set(keys2)][:a.n]
idx = np.linspace(0, len(keys)-1, min(a.n, len(keys))).astype(int)
keys = [keys[i] for i in idx]
rows = []
rowA = [cell_img(k, A[k], "A", (0,255,0)) for k in keys]
rows.append(rowA)
if B:
    rows.append([cell_img(k, B[k], "B", (255,160,0)) for k in keys])
out_rows = []
for r in rows:
    rr = list(r)
    while len(rr) % a.cols: rr.append(np.zeros_like(rr[0]))
    out_rows.append(np.vstack([np.hstack(rr[i:i+a.cols]) for i in range(0, len(rr), a.cols)]))
cv2.imwrite(a.out, np.vstack(out_rows)); print(f"[图] {a.out}  frames={len(keys)}")
