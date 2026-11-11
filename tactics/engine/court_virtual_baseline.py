#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.13 虚拟边线：把被前排观众挡住的那条球场边线补出来。

老程：「画面的下一方，球场的一条边线，被观众挡住了，你应该加一条虚拟边线」

现象（`gate1` 诊断）：掩膜在画面下方被"啃掉" —— ep24_s1 f70 的左边界
  y=560 → x=33，y=600 → x=48，**y=640 → x=320，y=680 → x=783**（急剧右移）
⇒ 站在底线/边线附近的人（发界外球的球员、场边助理裁判）脚点落在掩膜外，被门1 误杀。

原理：**球场上的直线在透视投影下仍是直线** ⇒ 图像里的底线是一条直线。
做法：
  1. 对每一列 x 求地板掩膜的**最低有效行** y_low(x)
  2. 用 **RANSAC 直线拟合**（抗观众"啃掉"造成的离群点）得到虚拟边线 y_line(x)
  3. 只在**原有掩膜下方**补全（y_low(x) < y ≤ y_line(x)），不左右扩张、不无限外推

用法: court_virtual_baseline.py --seg ep24_s1 --idx 70 [--tol 12] [--iters 3000]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))
from court_filter import _foot, court_mask  # noqa: E402


def col_low(m, min_pix=25):
    """每列 x 的地板最低有效行；该列掩膜像素过少则记为 -1（噪声列）。"""
    H, W = m.shape
    colpix = (m > 0).sum(axis=0)
    ys = np.where(m > 0)
    low = np.full(W, -1, dtype=np.int32)
    for x in range(W):
        if colpix[x] < min_pix:
            continue
        low[x] = int(ys[0][ys[1] == x].max())
    return low


def ransac_line(pts, iters=3000, tol=12.0, seed=0):
    """pts: [(x, y)]；返回 (a, b, inlier_mask)，y = a*x + b。"""
    rng = np.random.default_rng(seed)
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) < 8:
        return None, None, None
    best = (None, None, None, -1)
    for _ in range(iters):
        i, j = rng.choice(len(pts), 2, replace=False)
        (x1, y1), (x2, y2) = pts[i], pts[j]
        if abs(x2 - x1) < 30:
            continue
        a = (y2 - y1) / (x2 - x1)
        b = y1 - a * x1
        pred = a * pts[:, 0] + b
        inl = np.abs(pred - pts[:, 1]) < tol
        n = int(inl.sum())
        if n > best[3]:
            best = (a, b, inl, n)
    a, b, inl, n = best
    if a is None:
        return None, None, None
    # 用全部内点重新最小二乘
    P = pts[inl]
    a2, b2 = np.polyfit(P[:, 0], P[:, 1], 1)
    return float(a2), float(b2), inl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--tol", type=float, default=12.0)
    ap.add_argument("--iters", type=int, default=3000)
    ap.add_argument("--minpix", type=int, default=25)
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    d = SEGD / a.seg
    files = sorted((d / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    r = court_mask(img)
    if r is None or r[0] is None:
        print("court_mask 不可用"); return
    m = r[0]

    low = col_low(m, a.minpix)
    xs = np.where(low >= 0)[0]
    pts = [(float(x), float(low[x])) for x in xs]
    fit = ransac_line(pts, a.iters, a.tol)
    if fit[0] is None:
        print("拟合失败"); return
    A, B, inl = fit
    print(f"=== {a.seg} f{a.idx} 虚拟边线 ===")
    print(f"参与拟合列 {len(pts)}，内点 {int(inl.sum())} ({100*inl.mean():.1f}%)")
    print(f"虚拟边线: y = {A:.4f}*x + {B:.1f}   (斜率 {A:.4f} px/px)")

    # 补全：只在原掩膜下方补，且不超出画面
    m2 = m.copy()
    added = 0
    for x in xs:
        yl = int(round(A * x + B))
        yl = max(low[x], min(yl, H - 1))
        if yl > low[x]:
            seg = m2[low[x] + 1: yl + 1, x]
            added += int((seg == 0).sum())
            m2[low[x] + 1: yl + 1, x] = 255
    print(f"补全像素 {added}  掩膜面积 {m.mean()/255:.3f} -> {m2.mean()/255:.3f}")

    def oncourt(mm, box):
        fx, fy = _foot(box)
        return mm[fy, fx] > 0 if 0 <= fx < W and 0 <= fy < H else False

    jp = OUT / f"{a.seg}_f{a.idx}.json"
    if jp.exists():
        items = json.load(open(jp))
        V = {3: "观众", 8: "观众", 9: "观众", 13: "观众", 22: "★球员(红框)"}
        print(f"\n{'#':>4}{'运动量':>7}{'原门1':>7}{'加虚拟边线':>11}{'变化':>7}  裁定")
        n_rescue = 0
        for it in items:
            o1, o2 = oncourt(m, it["box"]), oncourt(m2, it["box"])
            if o2 and not o1:
                n_rescue += 1
            ch = ("救回" if (o2 and not o1) else "")
            if V.get(it["no"]):
                print(f"{it['no']:>4}{it['m']:>7.2f}{'是' if o1 else '否':>7}"
                      f"{'是' if o2 else '否':>11}{ch:>7}  {V[it['no']]}")
        print(f"\n共救回 {n_rescue} 个框（原本被误判到场外）")

    # 图：黄=虚拟边线，绿=补全后的场地
    vis = img.copy()
    ov = vis.copy()
    ov[m2 > 0] = (0.45 * ov[m2 > 0] + 0.55 * np.array([30, 190, 40])).astype(np.uint8)
    vis = cv2.addWeighted(ov, 0.5, vis, 0.5, 0)
    cv2.line(vis, (0, int(round(B))), (W - 1, int(round(A * (W - 1) + B))), (0, 230, 255), 4)
    cv2.putText(vis, f"virtual baseline: y={A:.4f}x{B:+.1f}", (12, 74),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5)
    cv2.putText(vis, f"virtual baseline: y={A:.4f}x{B:+.1f}", (12, 74),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 230, 255), 2)
    if jp.exists():
        for it in items:
            x1, y1, x2, y2 = [int(v) for v in it["box"]]
            on = oncourt(m2, it["box"])
            was = oncourt(m, it["box"])
            col = (0, 220, 0) if on else (0, 0, 225)
            cv2.rectangle(vis, (x1, y1), (x2, y2), col, 3 if on else 2)
            tag = f"#{it['no']}" + ("" if was else " [补]")
            cv2.putText(vis, tag, (x1, max(20, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 4)
            cv2.putText(vis, tag, (x1, max(20, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
    op = OUT / f"{a.seg}_f{a.idx}_vbaseline.png"
    cv2.imwrite(str(op), vis)
    print(f"\n-> {op}")


if __name__ == "__main__":
    main()
