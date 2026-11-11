#!/usr/bin/env python3
"""全局（背景）运动估计 —— 相位相关。用于检验"随镜头平移的静止假阳性"机制。
输出每对相邻帧的 (dx,dy) 与归一化响应峰；并给出中位平移量级。
用法: global_motion.py <window> [--n 60] [--scale 0.5]
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
ap.add_argument("window"); ap.add_argument("--n", type=int, default=60)
ap.add_argument("--scale", type=float, default=0.5)
ap.add_argument("--y0", type=float, default=0.0, help="只取 y0 以下区域做相关（0=全帧）")
a = ap.parse_args()
tr = json.loads((AW / f"{a.window}_poss" / "ball_tracks.json").read_text())
fdir = AW / a.window
files = [f["file"] for f in tr]
idx = np.linspace(0, len(files) - 2, min(a.n, len(files) - 1)).astype(int)
res = []
prev = None
for i in idx:
    p = fdir / files[i]; q = fdir / files[i + 1]
    A = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE); B = cv2.imread(str(q), cv2.IMREAD_GRAYSCALE)
    if A is None or B is None: continue
    if a.scale != 1.0:
        A = cv2.resize(A, None, fx=a.scale, fy=a.scale, interpolation=cv2.INTER_AREA)
        B = cv2.resize(B, None, fx=a.scale, fy=a.scale, interpolation=cv2.INTER_AREA)
    if a.y0 > 0:
        y = int(A.shape[0] * a.y0); A = A[y:]; B = B[y:]
    win = cv2.createHanningWindow((A.shape[1], A.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(np.float32(A), np.float32(B), win)
    res.append((files[i], dx / a.scale, dy / a.scale, resp))
mag = np.array([np.hypot(r[1], r[2]) for r in res])
resp = np.array([r[3] for r in res])
print(f"[{a.window}] 帧对 n={len(res)}  y0={a.y0}")
print(f"  平移量 |d| med={np.median(mag):.1f}px p90={np.percentile(mag,90):.1f}px max={mag.max():.1f}px")
print(f"  相位相关峰值 med={np.median(resp):.3f} p10={np.percentile(resp,10):.3f}")
for r in res[:8]:
    print(f"    {r[0]} dx={r[1]:7.1f} dy={r[2]:7.1f} resp={r[3]:.3f}")
np.save(f"/tmp/gm_{a.window}_{a.y0}.npy", np.array([[r[1], r[2], r[3]] for r in res]))
