#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.13e 近端边线拟合方法对照。

已知（Hough 取证）：f70 地板下沿**从左到右下移约 100px**（x=0→y≈600, x=1280→y≈700），
  真实斜率≈0.078–0.12；而 v1/v2 的 RANSAC 只给出 0.0152（偏平 5×）。
根因：中间 x∈[160,800] 的大量列 low≈607 主导了内点，右段真实下移点被当离群点丢弃
  ⇒ 「多数压制少数」。

本探针并排比较 4 种拟合：
  A) RANSAC over all          （v1/v2 用的，已知偏平）
  B) 分箱中位 (nb 箱, 中位)    （打破中间平坦段对右段的压制）
  C) 分箱高分位 (nb 箱, p80)   （抗「被观众啃掉」造成的偏小噪声）
  D) 全点最小二乘              （对照，最易被污染）
用法: court_baseline_fit_probe.py --seg ep24_s1 --idx 70 [--nb 16]
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

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))
from court_filter import court_mask  # noqa: E402

COLORS = {"A_RANSACall": (0, 0, 255), "B_binmed": (0, 220, 0),
          "C_binp80": (255, 128, 0), "D_lsq": (200, 0, 200)}


def col_low(m, min_pix=25):
    H, W = m.shape
    colpix = (m > 0).sum(axis=0)
    ys = np.where(m > 0)
    low = np.full(W, -1, np.int32)
    o = np.argsort(ys[1], kind="stable")
    xs, yy = ys[1][o], ys[0][o]
    s = 0
    for x in range(W):
        e = np.searchsorted(xs, x, side="right")
        if e - s >= min_pix:
            low[x] = int(yy[s:e].max())
        s = e
    return low


def fit_ransac_all(pts, tol=12.0, iters=4000, seed=0):
    rng = np.random.default_rng(seed)
    P = np.asarray(pts, float)
    if len(P) < 8:
        return None
    best = (None, -1)
    for _ in range(iters):
        i, j = rng.choice(len(P), 2, replace=False)
        (x1, y1), (x2, y2) = P[i], P[j]
        if abs(x2 - x1) < 40:
            continue
        a = (y2 - y1) / (x2 - x1)
        if abs(a) > 0.5:
            continue
        b = y1 - a * x1
        n = int((np.abs(a * P[:, 0] + b - P[:, 1]) < tol).sum())
        if n > best[1]:
            best = ((a, b), n)
    if best[0] is None:
        return None
    a, b = best[0]
    inl = np.abs(a * P[:, 0] + b - P[:, 1]) < tol
    a2, b2 = np.polyfit(P[inl, 0], P[inl, 1], 1)
    return float(a2), float(b2), best[1] / len(P)


def fit_binned(low, nb, q):
    W = len(low)
    xs = np.where(low >= 0)[0]
    if len(xs) < 40:
        return None
    edges = np.linspace(0, W, nb + 1).astype(int)
    px, py, pw = [], [], []
    for i in range(nb):
        sel = xs[(xs >= edges[i]) & (xs < edges[i + 1])]
        if len(sel) < 8:
            continue
        yv = low[sel]
        px.append(0.5 * (edges[i] + edges[i + 1]))
        py.append(np.percentile(yv, q))
        pw.append(len(sel))
    if len(px) < 4:
        return None
    px, py, pw = np.array(px, float), np.array(py, float), np.array(pw, float)
    A = np.vstack([px, np.ones_like(px)]).T * pw[:, None]
    y = py * pw
    sol, *_ = np.linalg.lstsq(A, y, rcond=None)
    return float(sol[0]), float(sol[1]), len(px)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--nb", type=int, default=16)
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    r = court_mask(img)
    if r is None or r[0] is None:
        print("court_mask 不可用"); return
    m = r[0]
    low = col_low(m)
    xs = np.where(low >= 0)[0]
    pts = [(float(x), float(low[x])) for x in xs]
    print(f"=== {a.seg} f{a.idx} 拟合对照（有效列 {len(pts)}/{W}，面积 {m.mean()/255:.3f}）===")

    fits = {}
    z = fit_ransac_all(pts)
    if z:
        fits["A_RANSACall"] = (z[0], z[1], f"内点{z[2]*100:.0f}%")
    z = fit_binned(low, a.nb, 50)
    if z:
        fits["B_binmed"] = (z[0], z[1], f"{z[2]}箱")
    z = fit_binned(low, a.nb, 80)
    if z:
        fits["C_binp80"] = (z[0], z[1], f"{z[2]}箱")
    P = np.asarray(pts, float)
    a2, b2 = np.polyfit(P[:, 0], P[:, 1], 1)
    fits["D_lsq"] = (float(a2), float(b2), "全点")

    vis = img.copy()
    for k, (A, B, note) in fits.items():
        c = COLORS[k]
        cv2.line(vis, (0, int(round(B))), (W - 1, int(round(A * (W - 1) + B))), c, 3)
        yl = int(round(A * 200 + B))
        cv2.putText(vis, f"{k} a={A:.4f} {note}", (6, max(20, yl - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
        cv2.putText(vis, f"{k} a={A:.4f} {note}", (6, max(20, yl - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, c, 2)
        print(f"  {k}: y = {A:.5f}x + {B:.1f}   -> x=0:{B:.0f}  x=640:{A*640+B:.0f}  x=1279:{A*1279+B:.0f}   [{note}]")
    for x in xs:
        cv2.circle(vis, (int(x), int(low[x])), 1, (255, 255, 255), -1)
    op = OUT / f"{a.seg}_f{a.idx}_fitcmp.png"
    cv2.imwrite(str(op), vis)
    print(f"-> {op}")


if __name__ == "__main__":
    main()
