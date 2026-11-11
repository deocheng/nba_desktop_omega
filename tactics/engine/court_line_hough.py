#!/usr/bin/env python3
"""court_line_hough.py — 在"白线掩膜"上做 Hough 直线检测，聚焦与远端边线近似平行的长直线族。
用途: 客观找出画面里所有"平行于边线"的直白线（远端边线/远端底角三分线/近端边线/底角三分线/限制区边线）。
用法: python3 court_line_hough.py --seg ep24_s1 --idx 70 [--slope 0.074 --slope-tol 0.12 --minlen 90]
产出: _hl_{seg}_f{idx}.png (原始帧上画出保留线段+编号+斜率/截距)  + 打印聚类表
"""
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

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--v", type=int, default=150)
    ap.add_argument("--s", type=int, default=75)
    ap.add_argument("--slope", type=float, default=0.074)
    ap.add_argument("--slope-tol", type=float, default=0.12)
    ap.add_argument("--minlen", type=float, default=90)
    ap.add_argument("--maxgap", type=float, default=25)
    ap.add_argument("--open-w", type=int, default=0, help="水平形态学开运算核宽(抑制文字/块)")
    a = ap.parse_args()

    files = sorted((SEGD / a.seg / "frames").glob("*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    wm = ((hsv[..., 2] > a.v) & (hsv[..., 1] < a.s)).astype(np.uint8) * 255
    if a.open_w > 1:
        wm = cv2.morphologyEx(wm, cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (a.open_w, 1)))

    # 用 HoughLines (无限直线, 投票) 更稳; 归一到 x=640 处的 y 做聚类
    lines = cv2.HoughLines(wm, 1, np.pi / 720, threshold=110)
    vis = cv2.addWeighted(img, 0.45, np.full_like(img, 255), 0.55, 0)
    refx = 640.0

    recs = []
    if lines is not None and len(lines):
        for rho, theta in np.asarray(lines).reshape(-1, 2):
            ct, st = np.cos(theta), np.sin(theta)
            if abs(st) < 1e-6:
                continue
            m = -ct / st                      # dy/dx
            if abs(m - a.slope) > a.slope_tol:
                continue
            yref = (rho - refx * ct) / st      # y at x=refx
            recs.append((yref, m))

    recs.sort()
    print(f"kept {len(recs)} hough-lines (slope {a.slope}±{a.slope_tol}); y@x={refx:.0f}")

    # 用 4px 直方图找峰（同一条线上的大量近似重复会被归并成一个峰）
    if recs:
        ys = np.array([r[0] for r in recs])
        ms = np.array([r[1] for r in recs])
        lo, hi = float(ys.min()), float(ys.max())
        nb = int((hi - lo) / 4.0) + 1
        hist, edges = np.histogram(ys, bins=nb, range=(lo, hi + 1))
        print(f"bin=4px  bincount={nb}")
        order = np.argsort(-hist)
        print(f"{'#':>3} {'y@640':>8} {'n':>5} {'meanM':>7}")
        shown = 0
        used = np.zeros(nb, bool)
        for bi in order:
            if hist[bi] < 25 or used[bi]:
                continue
            c = edges[bi] + 2
            sel = np.abs(ys - c) < 6
            used |= np.abs(edges[:-1] + 2 - c) < 12
            print(f"{shown:>3} {ys[sel].mean():>8.1f} {int(sel.sum()):>5} {ms[sel].mean():>7.3f}")
            m = float(ms[sel].mean())
            b = float(ys[sel].mean()) - m * refx
            cv2.line(vis, (0, int(b)), (W - 1, int(m * (W - 1) + b)), (0, 0, 255), 2)
            cv2.putText(vis, f"#{shown}", (int(refx) + 10, int(ys[sel].mean()) - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
            shown += 1
            if shown >= 20:
                break

    cv2.line(vis, (0, int(137.6)), (W - 1, int(0.0740 * (W - 1) + 137.6)), (255, 0, 255), 2)
    cv2.putText(vis, "FAR sideline(laocheng)", (300, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(OUT / f"_hl_{a.seg}_f{a.idx}.png"), vis)
    print(f"wrote _hl_{a.seg}_f{a.idx}.png")


if __name__ == "__main__":
    main()
