#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.23e 累积频率热力图 + 逐列累积上/下沿数字（判断真实稳定地板边界）。
用法: court_freq_heat.py --seg ep24_s1 --freq _tmp_freq_ep24_s1_w0_93.npy
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--freq", default="_tmp_freq_ep24_s1_w0_93.npy")
    a = ap.parse_args()

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    freq = np.load(str(OUT / a.freq)).astype(np.float32)
    hm = np.clip(freq, 0, 1)
    hm = (hm * 255).astype(np.uint8)
    color = cv2.applyColorMap(hm, cv2.COLORMAP_JET)

    print(f"=== {a.seg} f{a.idx} 累积频率逐列上/下沿 ===")
    print(f"{'x':>5} {'accTop':>7} {'accBot':>7}  |  0.7阈值 top/bot")
    for th in [0.7]:
        for x in range(0, W, 80):
            col = np.where(freq[:, x] >= th)[0]
            f_all = np.where(freq[:, x] >= 0.5)[0]
            t = int(col.min()) if len(col) else -1
            b = int(col.max()) if len(col) else -1
            print(f"{x:>5} {t:>7} {b:>7}  |  {th}")
    # 阈值0.5/0.9 对比
    for th in (0.5, 0.9):
        ts, bs = [], []
        for x in range(0, W, 40):
            col = np.where(freq[:, x] >= th)[0]
            if len(col) >= 5:
                ts.append((x, int(col.min()))); bs.append((x, int(col.max())))
        if len(ts) >= 2:
            at, bt = np.polyfit([p[0] for p in ts], [p[1] for p in ts], 1)
            ab, bb = np.polyfit([p[0] for p in bs], [p[1] for p in bs], 1)
            print(f"  th={th}: top y={at:.4f}x+{bt:.1f}(@640={at*640+bt:.0f})  "
                  f"bot y={ab:.4f}x+{bb:.1f}(@640={ab*640+bb:.0f})")

    vis = cv2.addWeighted(img, 0.45, color, 0.55, 0)
    op = OUT / f"_see_freqheat_f{a.idx}.png"
    cv2.imwrite(str(op), vis)
    cv2.imwrite(str(OUT / f"_see_freqheatmid_f{a.idx}.png"), vis[280:520, :])
    print(f"-> {op}")


if __name__ == "__main__":
    main()
