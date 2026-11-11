#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_zoom_tracks.py — 放大渲染指定 (clip, frame, track_id) 的裁剪格，供确定性判读。

用法
    python engine/_zoom_tracks.py --clip sas_hou --frame f00001.jpg --tracks 3,9,10,11,12
    python engine/_zoom_tracks.py --clip w1 --frame f00421.jpg --tracks 2768,3019 --cell 300
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
AW = ROOT / "action_work"
OUT = AW / "validate" / "pollution"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--frame", required=True)
    ap.add_argument("--tracks", required=True)
    ap.add_argument("--src", default=str(AW / "validate" / "player_pollution.json"))
    ap.add_argument("--cell", type=int, default=300)
    ap.add_argument("--expand", type=float, default=1.1)
    ap.add_argument("--tag", default="zoom")
    a = ap.parse_args()
    want = {int(t) for t in a.tracks.split(",")}
    rows = [r for r in json.loads(Path(a.src).read_text())[a.clip]["rows"]
            if r["file"] == a.frame and r["track_id"] in want]
    img = cv2.imread(str(AW / a.clip / a.frame))
    H, W = img.shape[:2]
    cells = []
    for r in sorted(rows, key=lambda z: z["track_id"]):
        x1, y1, x2, y2 = [int(v) for v in r["bbox"]]
        h = max(8, y2 - y1)
        pd = int(h * a.expand)
        ex1, ey1 = max(0, x1 - pd), max(0, y1 - pd)
        ex2, ey2 = min(W, x2 + pd), min(H, y2 + pd)
        crop = img[ey1:ey2, ex1:ex2].copy()
        sc = a.cell / max(crop.shape[:2])
        crop = cv2.resize(crop, (max(1, int(crop.shape[1] * sc)), max(1, int(crop.shape[0] * sc))),
                          interpolation=cv2.INTER_AREA)
        canvas = np.zeros((a.cell, a.cell, 3), np.uint8)
        oy, ox = (a.cell - crop.shape[0]) // 2, (a.cell - crop.shape[1]) // 2
        canvas[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = crop
        bx1, by1 = int((x1 - ex1) * sc) + ox, int((y1 - ey1) * sc) + oy
        bx2, by2 = int((x2 - ex1) * sc) + ox, int((y2 - ey1) * sc) + oy
        cv2.rectangle(canvas, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
        cv2.rectangle(canvas, (0, 0), (a.cell - 1, 40), (0, 0, 0), -1)
        cv2.putText(canvas, f"t{r['track_id']}  h={int(r['h'])}  foot_y={y2}", (5, 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1, cv2.LINE_AA)
        cv2.putText(canvas, f"cx={int(r['cx'])} cy={int(r['cy'])} keep={r['keep']}", (5, 31),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.46, (0, 255, 255), 1, cv2.LINE_AA)
        cells.append(canvas)
    cols = 5
    while len(cells) % cols:
        cells.append(np.zeros((a.cell, a.cell, 3), np.uint8))
    rows_img = [np.hstack(cells[i:i + cols]) for i in range(0, len(cells), cols)]
    g = np.vstack(rows_img)
    o = OUT / f"{a.tag}_{a.clip}_{Path(a.frame).stem}.jpg"
    cv2.imwrite(str(o), g, [cv2.IMWRITE_JPEG_QUALITY, 93])
    print(f"[out] {o}  框={len(rows)}")


if __name__ == "__main__":
    main()
