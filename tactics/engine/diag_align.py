#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断：逐帧对的单应是否可信。

输出三个量（全分辨率像素）：
  · 每对位移 |t|（H 的平移分量）—— 若远大于已知的镜头平移量级，就是关联错了
  · inlier 数
  · 配对光度残差：把帧 i+1 用 H 对齐到帧 i 后，在高梯度像素上的中位 |Δ|
    vs 不对齐的中位 |Δ|  ⇒ 「对齐是否真的让画面更一致」
用法: python engine/diag_align.py --window w1
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

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", required=True)
    ap.add_argument("--n", type=int, default=25, help="抽样多少对")
    a = ap.parse_args()
    fs = frame_paths(a.window)
    idx = np.linspace(0, len(fs) - 2, a.n).astype(int)
    prev_det = None
    print(f"{'pair':>9}{'|t| px':>9}{'rot°':>7}{'scale':>7}{'inl':>6}"
          f"{'配对对齐中位|Δ|':>16}{'未对齐中位|Δ|':>15}")
    for i in idx:
        da = detect(to_gray_small(fs[i])[0])
        db = detect(to_gray_small(fs[i + 1])[0])
        H, nin = match(da, db)
        ia = cv2.imread(str(fs[i]), cv2.IMREAD_GRAYSCALE)
        ib = cv2.imread(str(fs[i + 1]), cv2.IMREAD_GRAYSCALE)
        g = np.hypot(cv2.Sobel(ia, cv2.CV_32F, 1, 0, 3), cv2.Sobel(ia, cv2.CV_32F, 0, 1, 3))
        mask = g > 30
        if H is None:
            print(f"{i:>9}{'-':>9}{'-':>7}{'-':>7}{0:>6}{'-':>16}{'-':>15}")
            continue
        Hf = np.diag([1 / SC, 1 / SC, 1.0]) @ H @ np.diag([SC, SC, 1.0])
        t = Hf[:2, 2]
        rot = np.degrees(np.arctan2(Hf[1, 0], Hf[0, 0]))
        scl = float(np.sqrt(abs(np.linalg.det(Hf[:2, :2]))))
        wib = cv2.warpPerspective(ib, Hf, (ia.shape[1], ia.shape[0]))
        d_al = np.median(np.abs(ia.astype(np.float32) - wib.astype(np.float32))[mask])
        d_raw = np.median(np.abs(ia.astype(np.float32) - ib.astype(np.float32))[mask])
        print(f"{i:>9}{np.hypot(*t):>9.1f}{rot:>7.2f}{scl:>7.4f}{nin:>6}"
              f"{d_al:>16.1f}{d_raw:>15.1f}")


if __name__ == "__main__":
    main()
