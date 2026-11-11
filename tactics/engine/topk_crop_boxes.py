#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.11b 把指定帧的指定编号框裁出来放大，拼成一张核对图。

用法: topk_crop_boxes.py --seg ep24_s1 --idx 70 --nos 3,4,13,8,9,22
"""
from __future__ import annotations

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

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
NUM = ROOT / "action_work" / "track_judge" / "num"
CH = 300


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", required=True)
    ap.add_argument("--idx", type=int, required=True)
    ap.add_argument("--nos", required=True)
    ap.add_argument("--pad", type=float, default=0.45)
    a = ap.parse_args()

    items = {it["no"]: it for it in json.load(open(NUM / f"{a.seg}_f{a.idx}.json"))}
    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]

    tiles = []
    for ns in a.nos.split(","):
        n = int(ns.strip())
        it = items.get(n)
        if it is None:
            continue
        x1, y1, x2, y2 = [int(v) for v in it["box"]]
        w, h = x2 - x1, y2 - y1
        px, py = int(w * a.pad), int(h * a.pad)
        cx1, cy1 = max(0, x1 - px), max(0, y1 - py)
        cx2, cy2 = min(W, x2 + px), min(H, y2 + py)
        crop = img[cy1:cy2, cx1:cx2].copy()
        mag = CH / crop.shape[0]
        crop = cv2.resize(crop, (max(20, int(crop.shape[1] * mag)), CH), interpolation=cv2.INTER_CUBIC)
        # 描红真实框
        rx1 = int((x1 - cx1) * mag); ry1 = int((y1 - cy1) * mag)
        rx2 = int((x2 - cx1) * mag); ry2 = int((y2 - cy1) * mag)
        cv2.rectangle(crop, (rx1, ry1), (rx2, ry2), (0, 0, 255), 3)
        bar = np.full((52, crop.shape[1], 3), 245, np.uint8)
        flag = "留" if it["topk"] else "丢"
        cv2.putText(bar, f"#{n} {flag} m={it['m']:.2f} {w}x{h}px 脚y={it['foot_y']}",
                    (8, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (20, 20, 20), 2)
        tiles.append(np.vstack([bar, crop]))

    if not tiles:
        print("无匹配"); return
    hmax = max(t.shape[0] for t in tiles)
    tiles = [np.vstack([t, np.full((hmax - t.shape[0], t.shape[1], 3), 255, np.uint8)])
             if t.shape[0] < hmax else t for t in tiles]
    sep = np.full((hmax, 8, 3), 255, np.uint8)
    row = tiles[0]
    for t in tiles[1:]:
        row = np.hstack([row, sep, t])
    op = NUM / f"{a.seg}_f{a.idx}_crops.png"
    cv2.imwrite(str(op), row)
    print("->", op, row.shape)


if __name__ == "__main__":
    main()
