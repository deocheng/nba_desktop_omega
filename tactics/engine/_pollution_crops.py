#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_pollution_crops.py — 把标注集里的**每一个框**裁成带上下文的格子，供逐框判读 on/off-court。

判读依据（为什么裁剪比整图好用）
--------------------------------
「在场 / 在场外」的决定性线索是**这个人脚下的地面**：球场球员的足点落在木色/涂装/黑漆
的**平滑大面积地面**上；观众/替补的足点落在**座椅、台阶、其它人的身体或栏杆**上。
把框按 1.4×h 外扩后裁剪，脚下地面与左右邻居同时在画面里 ⇒ 单格即可判读。

格子角标：
    行1  <clip> <frame>  #i
    行2  h=<框高> y=<框中心y>  d=<足点到画面底边距离>
    行3  foot=(fx,fy)  （青点标出足点）

用法
    python engine/_pollution_crops.py --sheet 8      # 每张拼图 8 列
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
DIR = AW / "validate" / "pollution"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=str(DIR / "index.json"))
    ap.add_argument("--cols", type=int, default=8)
    ap.add_argument("--cell", type=int, default=210)
    ap.add_argument("--expand", type=float, default=1.4)
    a = ap.parse_args()

    idx = json.loads(Path(a.index).read_text())
    items = []
    for key, fr in idx.items():
        img = cv2.imread(str(AW / fr["clip"] / fr["file"]))
        if img is None:
            continue
        H, W = img.shape[:2]
        for b in fr["boxes"]:
            items.append((key, fr, img, b, W, H))

    cols = a.cols
    cell = a.cell
    cells = []
    for key, fr, img, b, W, H in items:
        x1, y1, x2, y2 = b["bbox"]
        h = max(8, y2 - y1)
        pd = int(h * a.expand)
        ex1, ey1 = max(0, x1 - pd), max(0, y1 - pd)
        ex2, ey2 = min(W, x2 + pd), min(H, y2 + pd)
        crop = img[ey1:ey2, ex1:ex2].copy()
        if crop.size == 0:
            continue
        sc = cell / max(crop.shape[:2])
        crop = cv2.resize(crop, (max(1, int(crop.shape[1] * sc)), max(1, int(crop.shape[0] * sc))),
                          interpolation=cv2.INTER_AREA)
        canvas = np.zeros((cell, cell, 3), np.uint8)
        oy = (cell - crop.shape[0]) // 2
        ox = (cell - crop.shape[1]) // 2
        canvas[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = crop
        # 画框（映射到裁剪后坐标）
        bx1 = int((x1 - ex1) * sc) + ox
        by1 = int((y1 - ey1) * sc) + oy
        bx2 = int((x2 - ex1) * sc) + ox
        by2 = int((y2 - ey1) * sc) + oy
        cv2.rectangle(canvas, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
        fx, fy = (x1 + x2) // 2, y2
        cv2.circle(canvas, (int((fx - ex1) * sc) + ox, int((fy - ey1) * sc) + oy), 4, (255, 255, 0), -1)
        cv2.rectangle(canvas, (0, 0), (cell - 1, 46), (0, 0, 0), -1)
        cv2.putText(canvas, f"{fr['clip']} {fr['file'][1:6]} #{b['i']}", (4, 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.46, (255, 255, 0), 1, cv2.LINE_AA)
        cv2.putText(canvas, f"h={h} y={b['cy']} x={b['cx']}", (4, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(canvas, f"fy={fy} conf={b['conf']:.2f}", (4, 44),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA)
        cells.append(canvas)

    per = a.cols * 4
    n = 0
    for s in range(0, len(cells), per):
        chunk = cells[s:s + per]
        while len(chunk) % cols:
            chunk.append(np.zeros((cell, cell, 3), np.uint8))
        rows = [np.hstack(chunk[i:i + cols]) for i in range(0, len(chunk), cols)]
        g = np.vstack(rows)
        o = DIR / f"crops_{s // per:02d}.jpg"
        cv2.imwrite(str(o), g, [cv2.IMWRITE_JPEG_QUALITY, 92])
        print(f"[out] {o}  cells={len(chunk)}")
        n += 1
    print(f"共 {len(cells)} 框 / {n} 张")


if __name__ == "__main__":
    main()
