#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""马赛克自相关检验：画面里有没有**重复内容**（=链式位移算多了直接证据）。

原理：正确的马赛克每个世界点只出现一次 ⇒ 横向自相关只有一个尖峰在 lag=0。
若链式累积把同一块内容放到两个不同位置，则会在某个 lag≫0 处出现**次峰**。

用法: python engine/mosaic_selfcorr.py --img measure/mosaic_w1_1_433.jpg
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

MS = Path(str(tactics_data_file("reports/milestone_05/measure")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--row0", type=int, default=250)
    ap.add_argument("--row1", type=int, default=1050)
    ap.add_argument("--lag-max", type=int, default=3200)
    ap.add_argument("--lag-step", type=int, default=20)
    a = ap.parse_args()
    g = cv2.imread(a.img, cv2.IMREAD_GRAYSCALE)
    if g is None:
        raise SystemExit("读不到图像")
    band = g[a.row0:a.row1].astype(np.float32)
    band = band[:, 40:-40]
    print(f"带区 {band.shape}  lag 扫描 0..{a.lag_max} 步长 {a.lag_step}")
    rows = []
    for lag in range(0, a.lag_max + 1, a.lag_step):
        if lag == 0:
            cc = 1.0
        else:
            X = band[:, :-lag]
            Y = band[:, lag:]
            Xc = X - X.mean()
            Yc = Y - Y.mean()
            d = np.sqrt((Xc ** 2).sum() * (Yc ** 2).sum())
            cc = float((Xc * Yc).sum() / d) if d > 0 else 0.0
        rows.append((lag, cc))
    cc = np.array([r[1] for r in rows])
    lag = np.array([r[0] for r in rows])
    print(f"  lag=0 : {cc[0]:.3f}")
    print(f"  lag>0 : 最大 {cc[1:].max():.3f} @ lag={lag[1:][cc[1:].argmax()]}"
          f"   中位 {np.median(cc[1:]):.3f}   p95 {np.percentile(cc[1:],95):.3f}")
    # 次峰显著性：最大次峰 vs 次峰的次大值（排同一个峰的邻域）
    idx = np.argsort(cc[1:])[::-1]
    top = [(lag[1:][i], cc[1:][i]) for i in idx[:8]]
    print("  前 8 个峰:", ", ".join(f"lag={int(l)}({c:.3f})" for l, c in top))
    peak = cc[1:].max()
    print(f"  ⇒ 若次峰 > 0.5 且明显高于中位 {np.median(cc[1:]):.3f}，则马赛克存在重复内容（链式位移偏大）")


if __name__ == "__main__":
    main()
