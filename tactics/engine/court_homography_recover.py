#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.14 场地矩形恢复（正解）：用「已知尺寸的油漆区」做单应标定，投影出整个球场矩形。

老程：「**场地是规整的矩形，你的识别是有问题的**」

为什么之前错（两轮被证伪的路）：
  - A5.13「虚拟边线」：拟合**颜色掩膜的锯齿下沿**（一维）⇒ 掩膜本身就不是球场（720 个轮廓点、凸包 IoU 仅 0.69）。
  - A5.14-a「轮廓拟合四边形」：拿**掩膜**去凑矩形 ⇒ 只能得到"包住掩膜的四边形"，把观众席也包进来（f145 退化成整个画面）。
根因：**球场是规整矩形这件事，只能靠"认出球场上的已知结构"来用，不能靠修补色块。**

本脚本（正解）：
  1. 抠出**油漆区**（the paint/key）—— 一个**已知尺寸的规整矩形**：
       NBA 标准：宽 16 ft = **4.877 m**（沿场地宽度），深 19 ft = **5.791 m**（自底线向内）
       且**在场地宽度方向居中** ⇒ 场地两条边线在油漆区两侧各 5.18 m
  2. 取其 4 个角（凸包 + 迭代 4 边拟合，抗球员遮挡）
  3. 4 角 ↔ 已知世界坐标 ⇒ **单应 H**（8 DOF，4 点唯一确定）
  4. 用 H 把**整个球场矩形**（28.65×15.24 m）投到图像 ⇒ 得到球场四边形，
     **被观众挡住的部分由几何自动补齐**
  5. 验证：投影球场 与 观察到的地板 的 IoU（应明显高于掩膜自身的凸包 IoU）

朝向判定（本场 ep24_s1）：油漆区内侧有**罚球圈弧**（弧心在下方那条边）⇒ **下边 = 罚球线侧 (x=5.791)**、
  上边 = **底线侧 (x=0)**；画面左上可见篮架，与"底线在油漆区上边之外"一致。
  ⚠️ 左右不需要判：油漆区在场地宽度方向**居中** ⇒ 两种左右分配投影出的两条边线相同。

用法: court_homography_recover.py --seg ep24_s1 --idx 70
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
from court_filter import PAINT_HI, PAINT_LO, court_mask  # noqa: E402

# ---- NBA 标准尺寸（米）----
COURT_L, COURT_W = 28.6512, 15.2400     # 94 ft × 50 ft
KEY_W, KEY_D = 4.8768, 5.7912           # 16 ft × 19 ft（油漆区 宽 × 深）
KEY_Y0 = (COURT_W - KEY_W) / 2.0        # 5.1816（居中）


def paint_mask(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    p = cv2.inRange(hsv, PAINT_LO, PAINT_HI)
    p = cv2.morphologyEx(p, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    p = cv2.morphologyEx(p, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(p)
    if n <= 1:
        return None
    b = 1 + int(np.argmax(st[1:, 4]))
    return np.where(lab == b, 255, 0).astype(np.uint8)


def _edge_line(p1, p2):
    d = np.asarray(p2, float) - np.asarray(p1, float)
    n = np.linalg.norm(d)
    return None if n < 1e-6 else (np.asarray(p1, float), d / n)


def _intersec(L1, L2):
    (c1, d1), (c2, d2) = L1, L2
    M = np.column_stack([d1, -d2])
    if abs(float(np.linalg.det(M))) < 1e-6:
        return None
    t = np.linalg.solve(M, np.asarray(c2, float) - np.asarray(c1, float))
    return np.asarray(c1, float) + t[0] * d1


def fit_quad(m, iters=60, min_pts=2):
    """掩膜 -> 凸四边形（抗遮挡的迭代 4 边拟合）。"""
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    P = cv2.convexHull(c).reshape(-1, 2).astype(float)
    if len(P) < 8:
        return None
    box = cv2.boxPoints(cv2.minAreaRect(c)).astype(float)
    cc = box.mean(0)
    box = box[np.argsort(np.arctan2(box[:, 1] - cc[1], box[:, 0] - cc[0]))]
    for _ in range(iters):
        edges = []
        for k in range(4):
            L = _edge_line(box[k], box[(k + 1) % 4])
            if L is None:
                return box
            edges.append(L)
        groups = [[] for _ in range(4)]
        for p in P:
            ds = []
            for (e0, d) in edges:
                v = np.asarray(p, float) - e0
                ds.append(float(np.linalg.norm(v - np.dot(v, d) * d)))
            groups[int(np.argmin(ds))].append(p)
        if any(len(g) < min_pts for g in groups):
            break
        ne = []
        for g in groups:
            A = np.asarray(g, float)
            mu = A.mean(0)
            _, _, vt = np.linalg.svd(A - mu, full_matrices=False)
            ne.append((mu, vt[0]))
        cs = []
        for k in range(4):
            pt = _intersec(ne[k], ne[(k + 1) % 4])
            if pt is None:
                return box
            cs.append(pt)
        cand = np.asarray(cs, float)
        # 排序保持环序
        c2 = cand.mean(0)
        cand = cand[np.argsort(np.arctan2(cand[:, 1] - c2[1], cand[:, 0] - c2[0]))]
        if np.linalg.norm(cand - box).max() < 0.5:
            box = cand
            break
        box = cand
    return box


def assign_world(quad):
    """把 4 个图像角按「上边=底线侧 / 下边=罚球线侧」对到世界坐标。

    返回 (world4x2, img4x2, note)。左右不判（油漆区居中 ⇒ 结果等价）。
    """
    q = np.asarray(quad, float)
    idx = np.argsort(q[:, 1])                 # 按 y 升序：前两个=上边，后两个=下边
    up = q[idx[:2]];   up = up[np.argsort(up[:, 0])]
    dn = q[idx[2:]];   dn = dn[np.argsort(dn[:, 0])]
    img = np.array([up[0], up[1], dn[1], dn[0]], float)
    world = np.array([[0.0, KEY_Y0], [0.0, KEY_Y0 + KEY_W],
                      [KEY_D, KEY_Y0 + KEY_W], [KEY_D, KEY_Y0]], float)
    return world, img, "上边=底线侧(x=0)  下边=罚球线侧(x=5.79m)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--key-y", type=float, default=None,
                    help="手动覆盖：油漆区上边对应的世界 x（默认 0=底线侧）")
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    pm = paint_mask(img)
    if pm is None:
        print("未检出油漆区"); return
    q = fit_quad(pm)
    if q is None:
        print("油漆区四边形拟合失败"); return
    print(f"=== A5.14 单应标定 {a.seg} f{a.idx} ===")
    print("油漆区 4 角(图像):", [[int(v) for v in p] for p in q])

    world, imgp, note = assign_world(q)
    print("朝向:", note)
    Hm = cv2.getPerspectiveTransform(world.astype(np.float32), imgp.astype(np.float32))

    # 反投影检查：油漆区角点应回到原处
    back = cv2.perspectiveTransform(world.astype(np.float32)[None], Hm)[0]
    print("自检 油漆区重投影最大误差 =", float(np.abs(back - imgp).max()), "px")

    # 场地 4 角 + 全部关键线
    cw = np.array([[0, 0], [COURT_L, 0], [COURT_L, COURT_W], [0, COURT_W]], np.float32)
    cproj = cv2.perspectiveTransform(cw[None], Hm)[0]
    print("球场 4 角(图像, 裁剪前):", [[int(v) for v in p] for p in cproj])
    for i, (x, y) in enumerate(zip(cproj[:, 0], cproj[:, 1])):
        print(f"  角{i}: ({x:.0f},{y:.0f}) {'← 画面内' if 0<=x<W and 0<=y<H else '← 画面外'}")

    # 掩膜 / 投影球场的 IoU
    def mask_of(poly):
        m = np.zeros((H, W), np.uint8)
        cv2.fillPoly(m, [poly.astype(np.int32)], 255)
        return m
    mm = court_mask(img)
    if mm is not None and mm[0] is not None:
        mm = mm[0]
        cq = mask_of(cproj)
        inter = ((cq > 0) & (mm > 0)).sum()
        print(f"IoU(投影球场, 地板掩膜) = {inter/max(((cq>0)|(mm>0)).sum(),1):.3f}")

    # 出图
    vis = img.copy()
    cq = mask_of(cproj)
    ov = vis.copy()
    ov[cq > 0] = (0.5 * ov[cq > 0] + 0.5 * np.array([0, 190, 255])).astype(np.uint8)
    vis = cv2.addWeighted(ov, 0.4, vis, 0.6, 0)
    cv2.polylines(vis, [cproj.astype(np.int32)], True, (0, 230, 255), 3)
    cv2.polylines(vis, [q.astype(np.int32)], True, (0, 0, 255), 3)
    # 油漆区世界尺寸网格：每 1 m 一条，用于自证透视正确
    for xm in np.arange(0, COURT_L + 0.01, 1.0):
        p = cv2.perspectiveTransform(np.array([[[xm, 0]], [[xm, COURT_W]]], np.float32), Hm)
        cv2.line(vis, tuple(np.int32(p[0][0])), tuple(np.int32(p[1][0])), (255, 120, 0), 1)
    for ym in np.arange(0, COURT_W + 0.01, 1.0):
        p = cv2.perspectiveTransform(np.array([[[0, ym]], [[COURT_L, ym]]], np.float32), Hm)
        cv2.line(vis, tuple(np.int32(p[0][0])), tuple(np.int32(p[1][0])), (255, 120, 0), 1)
    cv2.putText(vis, "red=key(4.88x5.79m)  yellow=court(28.65x15.24m)  orange=1m grid",
                (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.66, (0, 0, 0), 4)
    cv2.putText(vis, "red=key(4.88x5.79m)  yellow=court(28.65x15.24m)  orange=1m grid",
                (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.66, (0, 230, 255), 2)
    # ---- 投影球场关键结构做自证（罚球圈 / 三分线 / 篮筐 / 合理冲撞区）----
    def proj(pts_xy):
        p = cv2.perspectiveTransform(np.asarray([pts_xy], np.float32), Hm)[0]
        return p

    def circle(cx, cy, r, n=180, a0=0.0, a1=np.pi):
        t = np.linspace(a0, a1, n)
        return np.stack([cx + r * np.cos(t), cy + r * np.sin(t)], 1)

    BSK = (1.575, COURT_W / 2)                      # 篮筐中心(远端)
    FT_R = 1.8288                                    # 罚球圈半径 6ft
    ARC_R = 7.239                                    # 三分弧半径 23.75ft
    RA_R = 1.2192                                    # 合理冲撞区 4ft
    fcircle = circle(KEY_D, COURT_W / 2, FT_R, 181)  # 罚球圈(整圆)
    arc = circle(BSK[0], BSK[1], ARC_R, 181, -np.pi / 2, np.pi / 2)  # 半场三分弧
    ra = circle(BSK[0], BSK[1], RA_R, 91, -np.pi / 2, np.pi / 2)
    for pts, col, nm in [(fcircle, (255, 0, 255), "罚球圈"),
                         (arc, (0, 255, 0), "三分弧"),
                         (ra, (255, 255, 0), "合理冲撞区")]:
        cv2.polylines(vis, [proj(pts).astype(np.int32)], False, col, 2)
    cv2.circle(vis, tuple(np.int32(proj(np.array([[BSK[0], BSK[1]]]))[0])), 8, (0, 0, 255), -1)

    op = OUT / f"{a.seg}_f{a.idx}_homog.png"
    cv2.imwrite(str(op), vis)
    print(f"-> {op}")


if __name__ == "__main__":
    main()
