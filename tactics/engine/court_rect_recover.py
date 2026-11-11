#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.14 场地矩形恢复：用「球场是规整矩形」这个硬几何先验替代歪扭的颜色掩膜。

老程：「**场地是规整的矩形，你的识别是有问题的**」

诊断（`_dbg` 实测）：`court_mask` 的轮廓有 **400–720 个顶点**（矩形只有 4 个），
  f70 凸包 IoU 仅 **0.692** ⇒ 掩膜 **31% 是"被观众啃掉的凹陷"**，边缘全是锯齿。
  ⇒ A5.13 我拟合「这团锯齿**的下沿」（一维）方向就是错的；应该**二维**恢复矩形的 4 条直线边。

原理：
  - 透视投影把**矩形**映为**凸四边形**（每条边仍是直线）。
  - 反过来，**任意凸四边形**都可视为某个矩形的透视投影（射影变换由 4 对点唯一确定）。
  ⇒ 只要把地板观测拟合为一个**凸四边形**，就同时满足"规整矩形"先验，并自动补齐被遮挡部分。

算法（迭代 4 边拟合，每边用 TLS/PCA 主方向）：
  1. mask 最大连通域 → 凸包点集 P
  2. 用 minAreaRect 的 4 角初始化
  3. 迭代：每个凸包点分配到距离最近的边 → 该边用其点集重拟合直线 → 相邻边求交得新角点
  4. 退化保护（点太少 / 相邻边平行 / 交点越界）时回退 minAreaRect

用法:
  court_rect_recover.py --seg ep24_s1 --idx 70            # 单帧对比图
  court_rect_recover.py --seg ep24_s1 --all               # 全段：IoU 统计 + 门1 影响
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


def line_from_pts(p1, p2):
    """返回 (point_on_line, unit_dir)。"""
    d = np.asarray(p2, float) - np.asarray(p1, float)
    n = np.linalg.norm(d)
    if n < 1e-6:
        return None
    return np.asarray(p1, float), d / n


def fit_edge(P):
    """点集 P -> 直线 (中心, 单位方向)，用 PCA 主方向（总体最小二乘）。"""
    A = np.asarray(P, float)
    c = A.mean(0)
    _, _, vt = np.linalg.svd(A - c, full_matrices=False)
    return c, vt[0]


def intersec(L1, L2):
    """两直线求交；平行返回 None。"""
    (c1, d1), (c2, d2) = L1, L2
    M = np.column_stack([d1, -d2])
    det = float(np.linalg.det(M))
    if abs(det) < 1e-6:
        return None
    t = np.linalg.solve(M, np.asarray(c2, float) - np.asarray(c1, float))
    return c1 + t[0] * d1


def order_quad(pts):
    """按质心的极角排序，保证四边形顶点顺序一致（顺时针/逆时针）。"""
    p = np.asarray(pts, float)
    c = p.mean(0)
    ang = np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0])
    return p[np.argsort(ang)]


def fit_quad(m, iters=40, min_pts=2):
    """从掩膜拟合透视四边形，返回 (4x2 角点, info)。"""
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None, {"ok": False, "why": "无轮廓"}
    c = max(cnts, key=cv2.contourArea)
    P = cv2.convexHull(c).reshape(-1, 2).astype(float)
    if len(P) < 8:
        return None, {"ok": False, "why": f"凸包点过少 {len(P)}"}
    rect = cv2.minAreaRect(c)
    box = cv2.boxPoints(rect).astype(float)
    box = order_quad(box)
    last = None
    for _ in range(iters):
        edges = []
        ok = True
        for k in range(4):
            L = line_from_pts(box[k], box[(k + 1) % 4])
            if L is None:
                ok = False
                break
            edges.append(L)
        if not ok:
            break
        # 分配：每个凸包点到最近边
        groups = [[] for _ in range(4)]
        for p in P:
            ds = []
            for (cc, dd) in edges:
                v = np.asarray(p, float) - cc
                proj = np.dot(v, dd)
                ds.append(float(np.linalg.norm(v - proj * dd)))
            groups[int(np.argmin(ds))].append(p)
        if any(len(g) < min_pts for g in groups):
            break
        new_edges = [fit_edge(g) for g in groups]
        corners = []
        ok = True
        for k in range(4):
            pt = intersec(new_edges[k], new_edges[(k + 1) % 4])
            if pt is None:
                ok = False
                break
            corners.append(pt)
        if not ok:
            break
        cand = order_quad(np.array(corners))
        # 保护：四边形面积不得爆掉（超过画面 3 倍或过小）
        area = float(cv2.contourArea(cand.astype(np.float32)))
        H, W = m.shape[:2]
        if not (0.02 * H * W < area < 5.0 * H * W):
            break
        if last is not None and np.linalg.norm(cand - last).max() < 0.5:
            box = cand
            break
        box = cand
        last = cand
    return box, {"ok": True, "hull_pts": len(P)}


def mask_of_poly(shape, poly):
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [poly.astype(np.int32)], 255)
    return m


def iou(x, y):
    return float(((x > 0) & (y > 0)).sum()) / max(((x > 0) | (y > 0)).sum(), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--conf", type=float, default=0.25)
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    frames = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    cache = json.load(open(ROOT / "action_work" / f"_detcache_{a.seg}_1280.json"))

    if a.all:
        raise NotImplementedError("见 court_rect_scan.py")
    img = cv2.imread(str(frames[a.idx]))
    H, W = img.shape[:2]
    r = court_mask(img)
    if r is None or r[0] is None:
        print("court_mask 不可用"); return
    m = r[0]
    q, info = fit_quad(m)
    if q is None:
        print("拟合失败", info); return
    qm = mask_of_poly((H, W), q)
    print(f"=== A5.14 场地矩形恢复 {a.seg} f{a.idx} ===")
    print(f"凸包点 {info['hull_pts']}  掩膜面积 {m.mean()/255:.3f}  四边形面积 {qm.mean()/255:.3f}")
    print(f"IoU(四边形, 掩膜) = {iou(qm, m):.3f}")
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cnts, key=cv2.contourArea)
    hull = cv2.convexHull(c)
    hm = np.zeros_like(m); cv2.fillPoly(hm, [hull], 255)
    print(f"IoU(凸包,   掩膜) = {iou(hm, m):.3f}   （对照）")
    print("四边形角点:", [[int(v) for v in p] for p in q])

    vis = img.copy()
    ov = vis.copy()
    ov[qm > 0] = (0.45 * ov[qm > 0] + 0.55 * np.array([255, 200, 0])).astype(np.uint8)
    vis = cv2.addWeighted(ov, 0.42, vis, 0.58, 0)
    cv2.polylines(vis, [q.astype(np.int32)], True, (0, 255, 255), 3)
    cv2.polylines(vis, [hull], True, (255, 0, 255), 1)
    for k, p in enumerate(q):
        cv2.circle(vis, (int(p[0]), int(p[1])), 7, (0, 0, 255), -1)
        cv2.putText(vis, f"c{k}", (int(p[0]) + 8, int(p[1]) - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 4)
        cv2.putText(vis, f"c{k}", (int(p[0]) + 8, int(p[1]) - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.putText(vis, "yellow=recovered court quad  magenta=convex hull of mask",
                (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
    cv2.putText(vis, "yellow=recovered court quad  magenta=convex hull of mask",
                (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    op = OUT / f"{a.seg}_f{a.idx}_rect.png"
    cv2.imwrite(str(op), vis)
    print(f"-> {op}")


if __name__ == "__main__":
    main()
