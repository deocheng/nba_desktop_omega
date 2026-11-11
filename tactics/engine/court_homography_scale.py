#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.15+ 老程想法落地探针：已知场地真实尺寸 + 油漆区已知大小位置 → 单应恢复完整虚拟场地边线 + 数值比例尺。

复用：
  - court_homography_recover: paint_mask/fit_quad/assign_world（已知尺寸锚点）
  - court_infer_lines: v3 累积掩膜推断的 near/far/baseline 边线（跨窗口稳健，作交叉验证）
  - court_accum_mask: A 窗口 50 帧累积掩膜（比单帧 court_mask 更可靠的真值近似）

输出：
  - 比例尺数值（近底线处 px/m、px/ft；球场宽/长像素跨度）
  - 交叉验证：homography 投影球场 vs 累积掩膜 IoU、vs v3 多边形 IoU
  - 统一叠图：v3 边线(绿/青/品红) + homography 完整虚拟场地(黄) + 关键结构 + 1m 网格 + 比例尺标注
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
import court_homography_recover as HR  # noqa: E402
import court_infer_lines as CI  # noqa: E402

# NBA 标准尺寸（米）
COURT_L, COURT_W = HR.COURT_L, HR.COURT_W
KEY_W, KEY_D = HR.KEY_W, HR.KEY_D
KEY_Y0 = HR.KEY_Y0


def scale_at_baseline(H):
    """近底线处(x_world=0)：沿场地宽度方向取 1m，量像素跨度 → px/m。"""
    p0 = cv2.perspectiveTransform(np.array([[[0.0, 0.0]]], np.float32), H)[0][0]
    p1 = cv2.perspectiveTransform(np.array([[[0.0, 1.0]]], np.float32), H)[0][0]
    d_m = float(np.linalg.norm(p1 - p0))
    # 球场长度方向 1m（x:0→1）
    q0 = cv2.perspectiveTransform(np.array([[[0.0, COURT_W / 2]]], np.float32), H)[0][0]
    q1 = cv2.perspectiveTransform(np.array([[[1.0, COURT_W / 2]]], np.float32), H)[0][0]
    d_l = float(np.linalg.norm(q1 - q0))
    return d_m, d_l


def iou_poly_mask(poly, mask):
    H, W = mask.shape[:2]
    m = np.zeros((H, W), np.uint8)
    cv2.fillPoly(m, [poly.astype(np.int32)], 255)
    inter = int(((m > 0) & (mask > 0)).sum())
    union = int(((m > 0) | (mask > 0)).sum())
    return inter / max(union, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--freq", default="_tmp_freq_ep24_s1_w0_93.npy")
    ap.add_argument("--spaint", type=float, default=133.8)
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]

    # ---- ① 已知几何单应（测试两种纵深朝向，用累积掩膜 IoU 选正确朝向）----
    pm = HR.paint_mask(img)
    q = HR.fit_quad(pm)
    qa = np.asarray(q, float)
    idx = np.argsort(qa[:, 1])
    up = qa[idx[:2]]; up = up[np.argsort(up[:, 0])]
    dn = qa[idx[2:]]; dn = dn[np.argsort(dn[:, 0])]
    imgp = np.array([up[0], up[1], dn[1], dn[0]], float)  # 上左,上右,下右,下左
    # 两种纵深朝向：A=上方→x=0(底线侧); B=下方→x=0(底线侧)
    worldA = np.array([[0.0, KEY_Y0], [0.0, KEY_Y0 + KEY_W],
                       [KEY_D, KEY_Y0 + KEY_W], [KEY_D, KEY_Y0]], float)
    worldB = np.array([[KEY_D, KEY_Y0], [KEY_D, KEY_Y0 + KEY_W],
                       [0.0, KEY_Y0 + KEY_W], [0.0, KEY_Y0]], float)

    # v3 多边形（累积掩膜推断，独立 court 证据）
    poly_v3, lo_v3, info_v3 = CI.infer(img, a.seg, a.freq, s_paint_win=a.spaint)
    mv3 = None
    if poly_v3 is not None:
        mv3 = np.zeros((H, W), np.uint8)
        cv2.fillPoly(mv3, [poly_v3.astype(np.int32)], 255)

    fp = OUT / a.freq
    acc = None
    if fp.exists():
        freq = np.load(str(fp))
        acc = (freq >= CI.ACC_TH).astype(np.uint8)

    best = None
    for tag, world in (("A_up=baseline", worldA), ("B_dn=baseline", worldB)):
        Ht = cv2.getPerspectiveTransform(world.astype(np.float32), imgp.astype(np.float32))
        cproj_t = cv2.perspectiveTransform(
            np.array([[[0, 0], [COURT_L, 0], [COURT_L, COURT_W], [0, COURT_W]]], np.float32), Ht)[0]
        iou_a = iou_poly_mask(cproj_t, acc) if acc is not None else None
        iou_v = iou_poly_mask(cproj_t, mv3) if mv3 is not None else None
        print(f"  朝向 {tag}: IoU(累积掩膜)={iou_a:.3f}  IoU(v3)={iou_v:.3f}" if iou_a is not None
              else f"  朝向 {tag}: IoU(v3)={iou_v:.3f}")
        score = (iou_a if iou_a is not None else 0) + 0.5 * (iou_v if iou_v is not None else 0)
        if best is None or score > best[0]:
            best = (score, tag, Ht, cproj_t, iou_a, iou_v)
    _, note, Hm, cproj, iou_acc, iou_v3 = best
    back = cv2.perspectiveTransform(worldA.astype(np.float32)[None], Hm)[0]
    reproj = float(np.abs(back - imgp).max())

    # ---- ② 比例尺 ----
    d_m, d_l = scale_at_baseline(Hm)
    print(f"=== A5.15+ 已知几何单应 + 比例尺 {a.seg} f{a.idx} ===")
    print(f"  油漆区重投影最大误差 = {reproj:.4f} px")
    print(f"  比例尺(近底线, 沿宽度): 1 m ≈ {d_m:.1f} px | 1 ft ≈ {d_m/0.3048:.1f} px")
    print(f"  比例尺(近底线, 沿纵深): 1 m ≈ {d_l:.1f} px")
    print(f"  球场宽度 15.24m ≈ {15.24 * d_m:.0f} px ; 球场长度 28.65m ≈ {28.65 * d_l:.0f} px")

    # ---- ③ v3 / 累积掩膜交叉验证（已在朝向循环算好）----
    print(f"  选定朝向: {note}")
    print(f"  IoU(投影球场, 累积掩膜) = {iou_acc:.3f}  [面积IoU, 木地板含线外区域, 仅供粗参考]"
          if iou_acc is not None else "  累积掩膜缺失")
    print(f"  IoU(投影球场, v3多边形) = {iou_v3:.3f}")
    print(f"  v3: containment={info_v3.get('containment')} coverage={info_v3.get('coverage')} "
          f"baseline_angle={info_v3.get('baseline_angle_deg')} ratio_dev={info_v3.get('ratio_dev_pct')}%")

    # ---- ③b 边线距离交叉验证（建立对应：v3.near↔世界x=0, v3.baseline↔世界y=0）----
    def homog_edge(xw=None, yw=None):
        if xw is not None:
            p = cv2.perspectiveTransform(
                np.array([[[xw, 0], [xw, COURT_W]]], np.float32), Hm)[0]
        else:
            p = cv2.perspectiveTransform(
                np.array([[[0, yw], [COURT_L, yw]]], np.float32), Hm)[0]
        return p[0], p[1]

    def line_pts(seg4):
        x1, y1, x2, y2 = seg4
        t = np.linspace(0, 1, 60)
        return np.stack([x1 + (x2 - x1) * t, y1 + (y2 - y1) * t], 1)

    def median_dist(pts, a, b):
        a = np.asarray(a, float); b = np.asarray(b, float)
        d = b - a
        L = np.linalg.norm(d)
        if L < 1e-6:
            return float(np.abs(pts - a).max())
        u = d / L
        v = pts - a
        proj = np.clip(np.dot(v, u), 0, L)
        foot = a + proj[:, None] * u
        return float(np.median(np.linalg.norm(pts - foot, axis=1)))

    if lo_v3 is not None:
        h_near = homog_edge(xw=0.0)      # 近端底线
        h_base = homog_edge(yw=0.0)       # 左侧边线
        d_near = median_dist(line_pts(lo_v3["near"]), *h_near)
        d_base = median_dist(line_pts(lo_v3["baseline"]), *h_base)
        print(f"  边线距离(对应验证): v3.near↔世界x=0 = {d_near:.1f}px ; "
              f"v3.baseline↔世界y=0 = {d_base:.1f}px")
    else:
        d_near = d_base = None

    # ---- ④ 统一叠图 ----
    vis = img.copy()
    # homography 完整虚拟场地（黄）
    cv2.polylines(vis, [cproj.astype(np.int32)], True, (0, 215, 255), 3)
    # 半场线 / 两侧边线（淡黄）— 正确 shape (1,2,2)
    half = cv2.perspectiveTransform(
        np.array([[[COURT_L / 2, 0], [COURT_L / 2, COURT_W]]], np.float32), Hm)[0]
    left = cv2.perspectiveTransform(
        np.array([[[0, 0], [COURT_L, 0]]], np.float32), Hm)[0]
    right = cv2.perspectiveTransform(
        np.array([[[0, COURT_W], [COURT_L, COURT_W]]], np.float32), Hm)[0]
    cv2.line(vis, tuple(np.int32(half[0])), tuple(np.int32(half[1])), (0, 160, 220), 2)
    cv2.line(vis, tuple(np.int32(left[0])), tuple(np.int32(left[1])), (0, 160, 220), 2)
    cv2.line(vis, tuple(np.int32(right[0])), tuple(np.int32(right[1])), (0, 160, 220), 2)
    # 关键结构
    def proj(pts):
        return cv2.perspectiveTransform(np.asarray([pts], np.float32), Hm)[0]
    def circle(cx, cy, r, n=180, a0=0.0, a1=np.pi):
        t = np.linspace(a0, a1, n)
        return np.stack([cx + r * np.cos(t), cy + r * np.sin(t)], 1)
    BSK = (1.575, COURT_W / 2)
    for pts, col in [(circle(KEY_D, COURT_W / 2, 1.8288, 181), (255, 0, 255)),
                     (circle(BSK[0], BSK[1], 7.239, 181, -np.pi/2, np.pi/2), (0, 255, 0)),
                     (circle(BSK[0], BSK[1], 1.2192, 91, -np.pi/2, np.pi/2), (255, 255, 0))]:
        cv2.polylines(vis, [proj(pts).astype(np.int32)], False, col, 2)
    # 1m 网格
    for xm in np.arange(0, COURT_L + 0.01, 1.0):
        p = cv2.perspectiveTransform(np.array([[[xm, 0], [xm, COURT_W]]], np.float32), Hm)
        cv2.line(vis, tuple(np.int32(p[0][0])), tuple(np.int32(p[0][1])), (255, 120, 0), 1)
    for ym in np.arange(0, COURT_W + 0.01, 1.0):
        p = cv2.perspectiveTransform(np.array([[[0, ym], [COURT_L, ym]]], np.float32), Hm)
        cv2.line(vis, tuple(np.int32(p[0][0])), tuple(np.int32(p[0][1])), (255, 120, 0), 1)
    # v3 边线（绿/青/品红）
    if lo_v3 is not None:
        CI.draw_ext(vis, lo_v3["near"], (0, 255, 0))
        CI.draw_ext(vis, lo_v3["far"], (0, 255, 255))
        CI.draw_ext(vis, lo_v3["baseline"], (255, 0, 255))
    # 比例尺标注 + 图例
    txt = [(f"1m @near baseline ≈ {d_m:.0f}px  |  1ft ≈ {d_m/0.3048:.0f}px  | court W 15.24m≈{15.24*d_m:.0f}px",
           (12, 28), (0, 215, 255)),
          ("yellow=homography 完整虚拟场地  orange=1m网格  green/cyan/magenta=v3累积推断边线",
           (12, 56), (0, 215, 255)),
          (f"边线距离: near↔x0={d_near:.0f}px baseline↔y0={d_base:.0f}px  重投影err={reproj:.2f}px",
           (12, 84), (0, 215, 255))]
    for s, pos, col in txt:
        cv2.putText(vis, s, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 4)
        cv2.putText(vis, s, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.62, col, 2)
    op = OUT / f"{a.seg}_f{a.idx}_homog_scale.png"
    cv2.imwrite(str(op), vis)
    print(f"  -> {op}")

    json.dump({"seg": a.seg, "idx": a.idx, "reproj_err_px": round(reproj, 4),
               "px_per_m_near": round(d_m, 1), "px_per_ft_near": round(d_m / 0.3048, 1),
               "px_per_m_length": round(d_l, 1),
               "court_W_px": round(15.24 * d_m, 0), "court_L_px": round(28.65 * d_l, 0),
               "iou_vs_accum": round(iou_acc, 3) if iou_acc else None,
               "iou_vs_v3": round(iou_v3, 3),
               "edge_dist_px": {"v3_near_vs_world_x0": round(d_near, 1) if d_near else None,
                                "v3_baseline_vs_world_y0": round(d_base, 1) if d_base else None},
               "v3": {k: info_v3.get(k) for k in ("containment", "coverage", "baseline_angle_deg", "ratio_dev_pct")}},
              open(str(OUT / f"{a.seg}_f{a.idx}_homog_scale.json"), "w"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
