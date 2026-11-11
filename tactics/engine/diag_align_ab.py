#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对齐正确性 A/B 对照：正确 H 是否让画面比「故意偏移」更一致。

单看「对齐后 |Δ| < 未对齐 |Δ|」会被**重采样模糊**污染（任何 warp 都会模糊高梯度区）。
正确做法是控制对照：对同一 H，分别施加 0 / ±d 像素偏移，比较残差曲线。
若 0 偏移是极小值 ⇒ 对齐在这些像素上确实成立。

用法: python engine/diag_align_ab.py --window w1 --pairs 0 41 164 371 --d 8
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

sys.path.insert(0, str(Path(__file__).resolve().parent))
from global_align import SC, detect, frame_paths, match, to_gray_small

MS = Path(str(tactics_data_file("reports/milestone_05/measure")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", required=True)
    ap.add_argument("--pairs", nargs="+", type=int, default=[0, 41, 164, 371])
    ap.add_argument("--d", type=int, default=8)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    fs = frame_paths(a.window)
    offs = [-a.d, -a.d // 2, 0, a.d // 2, a.d]
    tiles = []
    print(f"{'pair':>6}" + "".join(f"{('Δ'+str(o)):>10}" for o in offs) + "   最小处")
    for i in a.pairs:
        da, db = detect(to_gray_small(fs[i])[0]), detect(to_gray_small(fs[i + 1])[0])
        H, nin = match(da, db)
        if H is None:
            print(f"{i:>6}  匹配失败")
            continue
        ia = cv2.imread(str(fs[i]), cv2.IMREAD_GRAYSCALE)
        ib = cv2.imread(str(fs[i + 1]), cv2.IMREAD_GRAYSCALE)
        g = np.hypot(cv2.Sobel(ia, cv2.CV_32F, 1, 0, 3), cv2.Sobel(ia, cv2.CV_32F, 0, 1, 3))
        mask = g > 40
        Hf = np.diag([1 / SC, 1 / SC, 1.0]) @ H @ np.diag([SC, SC, 1.0])
        res = []
        for o in offs:
            T = np.array([[1, 0, o], [0, 1, o], [0, 0, 1]], float)
            wib = cv2.warpPerspective(ib, T @ Hf, (ia.shape[1], ia.shape[0]))
            res.append(float(np.mean(np.abs(ia.astype(np.float32) - wib.astype(np.float32))[mask])))
        best = offs[int(np.argmin(res))]
        print(f"{i:>6}" + "".join(f"{v:>10.2f}" for v in res) + f"   {best:+d}")
        # 视觉对照：0 与 +d 两档的差异图
        T = np.array([[1, 0, a.d], [0, 1, a.d], [0, 0, 1]], float)
        w0 = cv2.warpPerspective(ib, Hf, (ia.shape[1], ia.shape[0]))
        w1 = cv2.warpPerspective(ib, T @ Hf, (ia.shape[1], ia.shape[0]))
        rgb = np.zeros((ia.shape[0], ia.shape[1], 3), np.uint8)
        rgb[:, :, 2] = ia
        rgb[:, :, 1] = w0
        rgb2 = np.zeros_like(rgb)
        rgb2[:, :, 2] = ia
        rgb2[:, :, 1] = w1
        tiles.append(np.concatenate([rgb, rgb2], axis=1))
    if tiles and a.pairs:
        out = a.out or str(MS / f"ab_{a.window}.jpg")
        cv2.imwrite(out, np.concatenate(tiles, axis=0)[::2, ::2], [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(f"[out] {out}  （每行两格：左=零偏移 右=+{a.d}px 偏移）")


if __name__ == "__main__":
    main()
