#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.23b 把累积掩膜的 上/下/左 边界点云 + RANSAC 线 直接画出来，肉眼判身份。
用法: court_accum_bounds_vis.py --seg ep24_s1 --idx 70 --freq _tmp_freq_ep24_s1_w0_93.npy
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))
import court_infer_lines as CI  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--freq", default="_tmp_freq_ep24_s1_w0_93.npy")
    ap.add_argument("--th", type=float, default=0.7)
    a = ap.parse_args()

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    freq = np.load(str(OUT / a.freq))
    acc = (freq >= a.th).astype(np.uint8)

    top, bot, left = [], [], []
    for x in range(0, W, 3):
        col = np.where(acc[:, x] > 0)[0]
        if len(col) >= 10:
            top.append((x, int(col.min())))
            bot.append((x, int(col.max())))
    for y in range(0, H, 2):
        row = np.where(acc[y, :] > 0)[0]
        if len(row):
            left.append((int(row.min()), y))

    vis = img.copy()
    # 掩膜半透明叠加(黄绿)
    ov = vis.copy()
    ov[acc > 0] = (0, 200, 120)
    vis = cv2.addWeighted(ov, 0.30, vis, 0.70, 0)
    # 点云
    for (x, y) in top:
        cv2.circle(vis, (x, y), 2, (0, 0, 255), -1)
    for (x, y) in bot:
        cv2.circle(vis, (x, y), 2, (255, 0, 0), -1)
    for (x, y) in left:
        cv2.circle(vis, (x, y), 2, (0, 255, 0), -1)

    r_top = CI.ransac_line(top)
    r_bot = CI.ransac_line(bot)
    r_lef = CI.ransac_steep(left)
    info = {}
    for name, r, col in [("top(red)", r_top, (0, 0, 255)),
                         ("bot(blue)", r_bot, (255, 0, 0))]:
        if r:
            aa, bb, n = r
            cv2.line(vis, (0, int(bb)), (W - 1, int(aa * (W - 1) + bb)), col, 3)
            info[name] = {"slope": round(aa, 4), "b": round(bb, 1), "n_inlier": n,
                          "y@W/2": round(aa * (W / 2) + bb, 1)}
    if r_lef:
        m, c, n = r_lef
        cv2.line(vis, (int(c), 0), (int(m * (H - 1) + c), H - 1), (0, 255, 0), 3)
        info["left(green)"] = {"slope_x_per_y": round(m, 4), "c": round(c, 1), "n_inlier": n,
                               "x@H/2": round(m * (H / 2) + c, 1)}

    info["n_top"] = len(top); info["n_bot"] = len(bot); info["n_left"] = len(left)
    # 上/下边界相距
    if r_top and r_bot:
        yt = r_top[0] * (W / 2) + r_top[1]
        yb = r_bot[0] * (W / 2) + r_bot[1]
        info["gap@W/2"] = round(float(yb - yt), 1)

    for i, (k, v) in enumerate(info.items()):
        s = f"{k}: {v}"
        cv2.putText(vis, s, (10, 30 + i * 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4)
        cv2.putText(vis, s, (10, 30 + i * 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

    op = OUT / f"_see_accumbounds_f{a.idx}.png"
    cv2.imwrite(str(op), vis)
    print(json.dumps(info, ensure_ascii=False, indent=1))
    print(f"-> {op}")


if __name__ == "__main__":
    main()
