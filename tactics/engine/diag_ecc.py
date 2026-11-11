#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐帧对相机运动：ORB 初值 + ECC 直接光度精修，检验能否消除「链式累积漂移」。

问题：ORB+RANSAC 的逐对尺度估计有 ~1% 系统性偏置，累积 434 帧后尺度漂到 1.55→0.55
（物理不可能）⇒ 链式累积不可用。
修法：ECC（Enhanced Correlation Coefficient）对**整幅灰度**做直接光度优化，
不依赖特征匹配，故无匹配偏置；ORB 结果只作初值。

判据：把同一段 N 对连乘，看累积尺度是否漂移；再抽若干对做 A/B 偏移对照。

用法:
  python engine/diag_ecc.py --window w1 --n 40
  python engine/diag_ecc.py --window w1 --n 40 --no-ecc
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

sys.path.insert(0, str(Path(__file__).resolve().parent))
from global_align import SC, detect, frame_paths, match, to_gray_small

MS = Path(str(tactics_data_file("reports/milestone_05/measure")))


def ecc_refine(ga, gb, W, iters=60, eps=1e-6):
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, iters, eps)
    try:
        cc, W = cv2.findTransformECC(ga, gb, W, cv2.MOTION_AFFINE, crit, None, 3)
        return W, float(cc)
    except cv2.error:
        return None, -1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", required=True)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--start", type=int, default=120, help="起始帧（避开开场快摇）")
    ap.add_argument("--no-ecc", action="store_true")
    a = ap.parse_args()
    fs = frame_paths(a.window)[a.start:a.start + a.n + 1]
    gs = [to_gray_small(p)[0] for p in fs]
    A_orb = np.eye(3); A_ecc = np.eye(3)
    rows = []
    t0 = time.time()
    for i in range(len(fs) - 1):
        da, db = detect(gs[i]), detect(gs[i + 1])
        H, nin = match(da, db)
        if H is None:
            rows.append((i, None, None))
            continue
        A_orb = H @ A_orb
        s_orb = float(np.sqrt(abs(np.linalg.det(H[:2, :2]))))
        # ECC 精修（仿射，全分辨率尺度）
        Hf = np.diag([1 / SC, 1 / SC, 1.0]) @ H @ np.diag([SC, SC, 1.0])
        W0 = Hf[:2, :].copy()
        W, cc = (None, -1) if a.no_ecc else ecc_refine(gs[i], gs[i + 1], W0)
        if W is None:
            W = Hf[:2, :]
        We = np.vstack([W, [0, 0, 1]])
        A_ecc = np.diag([SC, SC, 1.0]) @ We @ np.diag([1 / SC, 1 / SC, 1.0]) @ A_ecc
        s_ecc = float(np.sqrt(abs(np.linalg.det(We[:2, :2]))))
        tx = W[0, 2] / SC; ty = W[1, 2] / SC
        rows.append((i, s_orb, s_ecc, np.hypot(tx, ty), cc, nin))
    print(f"[{a.window}] 帧 {a.start}..{a.start+a.n}  用时 {time.time()-t0:.0f}s  "
          f"{'（禁用 ECC）' if a.no_ecc else ''}")
    print(f"{'i':>4}{'ORB尺度':>10}{'ECC尺度':>10}{'|t| px':>9}{'ECC cc':>9}{'inl':>7}")
    for r in rows[:: max(1, len(rows) // 14)]:
        if r[1] is None:
            continue
        print(f"{r[0]:>4}{r[1]:>10.5f}{r[2]:>10.5f}{r[3]:>9.1f}{r[4]:>9.3f}{r[5]:>7}")
    so = float(np.sqrt(abs(np.linalg.det(A_orb[:2, :2]))))
    se = float(np.sqrt(abs(np.linalg.det(A_ecc[:2, :2]))))
    to_ = np.hypot(A_orb[0, 2] / SC, A_orb[1, 2] / SC)
    te = np.hypot(A_ecc[0, 2] / SC, A_ecc[1, 2] / SC)
    print(f"\n★ 连乘 {a.n} 对的累积：")
    print(f"   ORB 仅   : 尺度 {so:.4f}   平移 {to_:.0f} px")
    print(f"   ORB+ECC  : 尺度 {se:.4f}   平移 {te:.0f} px")
    med_s = np.median([r[1] for r in rows if r[1] is not None])
    print(f"   逐对尺度中位：ORB {med_s:.5f}  ⇒ 理论上 {med_s:.5f}^{a.n} = {med_s**a.n:.3f}"
          f"（若显著偏离 1.0 即系统性偏置）")
    if not a.no_ecc:
        med_e = np.median([r[2] for r in rows if r[2] is not None])
        print(f"   逐对尺度中位：ECC {med_e:.5f}  ⇒ {med_e:.5f}^{a.n} = {med_e**a.n:.3f}")


if __name__ == "__main__":
    main()
