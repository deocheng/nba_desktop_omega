#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用磁盘已抽好的帧图（每0.1s一张）拼候选窗概览，不碰原视频。
帧映射：t = t0 + idx*0.1（实测已验证）。
用法: seg_overview.py <seg> <idx0> <idx1> <out.jpg> [每N张取1]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import os
import sys

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

SEG_DIR = str(tactics_data_file("action_work/tactic_notes_batch_full/segments"))


def main():
    seg = sys.argv[1]
    i0, i1 = int(sys.argv[2]), int(sys.argv[3])
    out = sys.argv[4]
    step = int(sys.argv[5]) if len(sys.argv) > 5 else 5
    ts = {f["idx"]: f["t"] for f in __import__("json").load(open(f"{SEG_DIR}/{seg}/frames.json"))}
    picks = list(range(i0, i1, step))
    if not picks:
        picks = [i0]
    tiles = []
    for i in picks:
        p = f"{SEG_DIR}/{seg}/frames/f{i+1:05d}.jpg"
        im = cv2.imread(p)
        if im is None:
            print("MISS", p)
            continue
        im = cv2.resize(im, (im.shape[1] // 2, im.shape[0] // 2))
        t = ts.get(i, None)
        cv2.rectangle(im, (0, 0), (im.shape[1], 20), (0, 0, 0), -1)
        cv2.putText(im, f"idx{i} t={t:.1f}s", (3, 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)
        tiles.append(im)
    W = max(t.shape[1] for t in tiles)
    rows = []
    for i in range(0, len(tiles), 2):
        grp = tiles[i:i + 2]
        rows.append(np.hstack([cv2.copyMakeBorder(t, 0, 0, 0, W - t.shape[1],
                              cv2.BORDER_CONSTANT, value=(0, 0, 0)) for t in grp]))
    mw = max(r.shape[1] for r in rows)
    rows = [cv2.copyMakeBorder(r, 0, 0, 0, mw - r.shape[1],
                 cv2.BORDER_CONSTANT, value=(0, 0, 0)) for r in rows]
    sheet = np.vstack(rows)
    d = os.path.dirname(out)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    cv2.imwrite(out, sheet, [cv2.IMWRITE_JPEG_QUALITY, 87])
    print(f"{seg} idx{i0}-{i1} step{step} tiles={len(tiles)}  t={ts.get(picks[0])}~{ts.get(picks[-1])}s")
    print("wrote", out, sheet.shape)


if __name__ == "__main__":
    main()
